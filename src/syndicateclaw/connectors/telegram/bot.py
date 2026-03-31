from __future__ import annotations

import asyncio
from typing import Any

import httpx
import structlog
from fastapi import APIRouter, HTTPException, Request

from syndicateclaw.connectors.base import ConnectorBase, ConnectorMessage, Platform

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["connectors-telegram"])


def _parse_command(text: str) -> tuple[bool, str | None, str | None]:
    stripped = text.strip()
    if not stripped or not stripped.startswith("/"):
        return False, None, None

    pieces = stripped.split(maxsplit=1)
    command_token = pieces[0]
    if "@" in command_token:
        command_token = command_token.split("@", 1)[0]
    command = command_token.lower()
    if not command:
        return False, None, None

    args = pieces[1].strip() if len(pieces) > 1 else None
    if args == "":
        args = None
    return True, command, args


class TelegramConnector(ConnectorBase):
    platform = Platform.TELEGRAM

    def __init__(self, provider_service: Any, settings: Any) -> None:
        super().__init__(provider_service)
        self.token = settings.telegram_bot_token or ""
        self.webhook_secret = settings.telegram_webhook_secret or ""
        self.public_base_url = settings.public_base_url or ""
        self._sent_msg_ids: dict[str, int] = {}

    async def start(self) -> None:
        if not self.token:
            self.status.connected = False
            self.status.detail = "telegram_bot_token not configured"
            return
        if not self.public_base_url:
            self.status.connected = False
            self.status.detail = "public_base_url not configured"
            return

        webhook_url = f"{self.public_base_url.rstrip('/')}/webhooks/telegram/update"
        payload: dict[str, Any] = {"url": webhook_url}
        if self.webhook_secret:
            payload["secret_token"] = self.webhook_secret

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    f"https://api.telegram.org/bot{self.token}/setWebhook",
                    json=payload,
                )
            body = response.json()
            ok = bool(body.get("ok")) if isinstance(body, dict) else False
            self.status.connected = ok
            self.status.webhook_url = webhook_url if ok else None
            self.status.detail = None if ok else str(body)
        except Exception as exc:
            self.status.connected = False
            self.status.detail = str(exc)
            logger.exception("telegram.start_failed")

    async def stop(self) -> None:
        if self.token:
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    await client.post(f"https://api.telegram.org/bot{self.token}/deleteWebhook")
            except Exception:
                logger.exception("telegram.stop_failed")
        self.status.connected = False

    async def send_reply(
        self,
        message: ConnectorMessage,
        text: str,
        *,
        is_streaming_complete: bool = True,
    ) -> None:
        if not self.token or not message.channel_id:
            return

        existing_msg_id = self._sent_msg_ids.get(message.channel_id)
        endpoint = "sendMessage"
        payload: dict[str, Any]

        if existing_msg_id is not None and not is_streaming_complete:
            endpoint = "editMessageText"
            payload = {
                "chat_id": message.channel_id,
                "message_id": existing_msg_id,
                "text": text or " ",
            }
        else:
            payload = {
                "chat_id": message.channel_id,
                "text": text or " ",
            }
            if existing_msg_id is None:
                try:
                    payload["reply_to_message_id"] = int(message.platform_message_id)
                except (TypeError, ValueError):
                    pass

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    f"https://api.telegram.org/bot{self.token}/{endpoint}",
                    json=payload,
                )
            body = response.json()
            result = body.get("result") if isinstance(body, dict) else None
            new_message_id = result.get("message_id") if isinstance(result, dict) else None
            if isinstance(new_message_id, int):
                self._sent_msg_ids[message.channel_id] = new_message_id
        except Exception:
            self.status.errors += 1
            logger.exception("telegram.send_reply_failed")
        finally:
            if is_streaming_complete:
                self._sent_msg_ids.pop(message.channel_id, None)

    def parse_update(self, body: dict[str, Any]) -> ConnectorMessage | None:
        update = body.get("message") or body.get("edited_message")
        if not isinstance(update, dict):
            return None

        text = update.get("text")
        if not isinstance(text, str) or not text.strip():
            return None

        chat = update.get("chat") or {}
        user = update.get("from") or {}

        channel_id = str(chat.get("id") or "")
        user_id = str(user.get("id") or "")
        platform_message_id = str(update.get("message_id") or "")
        if not channel_id or not user_id or not platform_message_id:
            return None

        is_command, command, command_args = _parse_command(text)

        thread = update.get("message_thread_id")
        thread_id = str(thread) if thread is not None else None

        return ConnectorMessage(
            platform=Platform.TELEGRAM,
            platform_message_id=platform_message_id,
            channel_id=channel_id,
            user_id=user_id,
            text=text.strip(),
            raw=body,
            thread_id=thread_id,
            is_command=is_command,
            command=command,
            command_args=command_args,
        )


@router.post("/update")
async def telegram_update(request: Request) -> dict[str, str]:
    registry = getattr(request.app.state, "connector_registry", None)
    if registry is None:
        return {"ok": "true"}

    connector = registry.get(Platform.TELEGRAM)
    if connector is None:
        return {"ok": "true"}

    header_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if connector.webhook_secret and header_secret != connector.webhook_secret:
        raise HTTPException(status_code=401, detail="invalid telegram secret token")

    body = await request.json()
    if not isinstance(body, dict):
        return {"ok": "true"}

    msg = connector.parse_update(body)
    if msg is not None:
        asyncio.create_task(connector.handle_message(msg))

    return {"ok": "true"}
