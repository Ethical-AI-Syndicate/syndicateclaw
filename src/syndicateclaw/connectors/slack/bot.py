from __future__ import annotations

import asyncio
import hashlib
import hmac
import time
from typing import Any

import httpx
import structlog
from fastapi import APIRouter, HTTPException, Request

from syndicateclaw.connectors.base import ConnectorBase, ConnectorMessage, Platform
from syndicateclaw.connectors.telegram.bot import _parse_command

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["connectors-slack"])


def _verify_slack_signature(
    signing_secret: str,
    body_bytes: bytes,
    headers: Any,
) -> bool:
    timestamp = headers.get("X-Slack-Request-Timestamp", "")
    signature = headers.get("X-Slack-Signature", "")
    if not timestamp or not signature:
        return False

    try:
        ts = int(timestamp)
    except ValueError:
        return False

    if abs(int(time.time()) - ts) > 300:
        return False

    payload = f"v0:{timestamp}:{body_bytes.decode('utf-8')}"
    digest = hmac.new(
        signing_secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    computed = f"v0={digest}"
    return hmac.compare_digest(computed, signature)


class SlackConnector(ConnectorBase):
    platform = Platform.SLACK

    def __init__(self, provider_service: Any, settings: Any) -> None:
        super().__init__(provider_service)
        self.bot_token = settings.slack_bot_token or ""
        self.signing_secret = settings.slack_signing_secret or ""
        self._pending_ts: dict[str, str] = {}

    async def start(self) -> None:
        if not self.bot_token:
            self.status.connected = False
            self.status.detail = "slack_bot_token not configured"
            return

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    "https://slack.com/api/auth.test",
                    headers={"Authorization": f"Bearer {self.bot_token}"},
                )
            body = response.json()
            ok = bool(body.get("ok")) if isinstance(body, dict) else False
            self.status.connected = ok
            self.status.detail = None if ok else str(body)
        except Exception as exc:
            self.status.connected = False
            self.status.detail = str(exc)
            logger.exception("slack.start_failed")

    async def stop(self) -> None:
        self.status.connected = False

    async def send_reply(
        self,
        message: ConnectorMessage,
        text: str,
        *,
        is_streaming_complete: bool = True,
    ) -> None:
        if not self.bot_token:
            return

        existing_ts = self._pending_ts.get(message.channel_id)
        headers = {
            "Authorization": f"Bearer {self.bot_token}",
            "Content-Type": "application/json; charset=utf-8",
        }

        if existing_ts is not None and not is_streaming_complete:
            endpoint = "https://slack.com/api/chat.update"
            payload: dict[str, Any] = {
                "channel": message.channel_id,
                "ts": existing_ts,
                "text": text or " ",
            }
        else:
            endpoint = "https://slack.com/api/chat.postMessage"
            payload = {
                "channel": message.channel_id,
                "text": text or " ",
            }
            if message.thread_id:
                payload["thread_ts"] = message.thread_id

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(endpoint, headers=headers, json=payload)
            body = response.json()
            ts = body.get("ts") if isinstance(body, dict) else None
            if isinstance(ts, str) and not is_streaming_complete:
                self._pending_ts[message.channel_id] = ts
        except Exception:
            self.status.errors += 1
            logger.exception("slack.send_reply_failed")
        finally:
            if is_streaming_complete:
                self._pending_ts.pop(message.channel_id, None)

    def parse_event(self, body: dict[str, Any]) -> ConnectorMessage | None:
        event = body.get("event") if isinstance(body.get("event"), dict) else None
        if event is None:
            return None

        event_type = str(event.get("type") or "")
        if event_type not in {"app_mention", "message"}:
            return None

        if event.get("bot_id") or event.get("subtype"):
            return None

        text = str(event.get("text") or "").strip()
        if text.startswith("<@") and ">" in text:
            _, _, text = text.partition(">")
            text = text.strip()
        if not text:
            return None

        channel_id = str(event.get("channel") or "")
        user_id = str(event.get("user") or "")
        platform_message_id = str(event.get("ts") or event.get("event_ts") or "")
        if not channel_id or not user_id or not platform_message_id:
            return None

        is_command, command, command_args = _parse_command(text)
        thread_ts = event.get("thread_ts")
        thread_id = str(thread_ts) if thread_ts is not None else None

        return ConnectorMessage(
            platform=Platform.SLACK,
            platform_message_id=platform_message_id,
            channel_id=channel_id,
            user_id=user_id,
            text=text,
            raw=body,
            thread_id=thread_id,
            is_command=is_command,
            command=command,
            command_args=command_args,
        )

    def parse_slash_command(self, form: dict[str, str]) -> ConnectorMessage:
        command = form.get("command", "").strip() or "/unknown"
        command_args = (form.get("text") or "").strip() or None
        trigger = form.get("trigger_id") or f"slash-{int(time.time() * 1000)}"
        return ConnectorMessage(
            platform=Platform.SLACK,
            platform_message_id=trigger,
            channel_id=form.get("channel_id", ""),
            user_id=form.get("user_id", ""),
            text=command,
            raw=form,
            thread_id=None,
            is_command=True,
            command=command,
            command_args=command_args,
        )


@router.post("/events")
async def slack_events(request: Request) -> dict[str, Any]:
    registry = getattr(request.app.state, "connector_registry", None)
    if registry is None:
        raise HTTPException(status_code=503, detail="connector registry unavailable")

    connector = registry.get(Platform.SLACK)
    if connector is None:
        raise HTTPException(status_code=503, detail="slack connector is disabled")

    body_bytes = await request.body()
    if not _verify_slack_signature(connector.signing_secret, body_bytes, request.headers):
        raise HTTPException(status_code=401, detail="invalid slack signature")

    body_any = await request.json()
    body: dict[str, Any] = body_any if isinstance(body_any, dict) else {}
    if body.get("type") == "url_verification":
        return {"challenge": body.get("challenge", "")}

    msg = connector.parse_event(body)
    if msg is not None:
        asyncio.create_task(connector.handle_message(msg))

    return {"ok": True}


@router.post("/command")
async def slack_command(request: Request) -> dict[str, str]:
    registry = getattr(request.app.state, "connector_registry", None)
    if registry is None:
        raise HTTPException(status_code=503, detail="connector registry unavailable")

    connector = registry.get(Platform.SLACK)
    if connector is None:
        raise HTTPException(status_code=503, detail="slack connector is disabled")

    body_bytes = await request.body()
    if not _verify_slack_signature(connector.signing_secret, body_bytes, request.headers):
        raise HTTPException(status_code=401, detail="invalid slack signature")

    form = await request.form()
    payload = {key: str(value) for key, value in form.items()}
    msg = connector.parse_slash_command(payload)
    asyncio.create_task(connector.handle_message(msg))

    return {"response_type": "ephemeral", "text": "⏳ Processing…"}
