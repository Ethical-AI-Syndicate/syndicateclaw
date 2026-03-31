from __future__ import annotations

import asyncio
from typing import Any

import httpx
import structlog
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import APIRouter, HTTPException, Request

from syndicateclaw.connectors.base import ConnectorBase, ConnectorMessage, Platform

logger = structlog.get_logger(__name__)

INTERACTION_TYPE_PING = 1
APPLICATION_COMMAND = 2
RESPONSE_TYPE_PONG = 1
DEFERRED_CHANNEL_MESSAGE = 5

SLASH_COMMANDS: list[dict[str, Any]] = [
    {
        "name": "chat",
        "description": "Send a message to SyndicateClaw",
        "type": 1,
        "options": [
            {
                "name": "message",
                "description": "Message content",
                "type": 3,
                "required": True,
            }
        ],
    },
    {
        "name": "run",
        "description": "Trigger a workflow",
        "type": 1,
        "options": [
            {
                "name": "workflow",
                "description": "Workflow name",
                "type": 3,
                "required": True,
            }
        ],
    },
    {
        "name": "status",
        "description": "Show connector status",
        "type": 1,
    },
    {
        "name": "help",
        "description": "List available commands",
        "type": 1,
    },
]

router = APIRouter(tags=["connectors-discord"])


def _verify_discord_signature(
    public_key_hex: str,
    signature: str,
    timestamp: str,
    body: bytes,
) -> bool:
    try:
        public_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
        public_key.verify(bytes.fromhex(signature), timestamp.encode("utf-8") + body)
        return True
    except Exception:
        return False


class DiscordConnector(ConnectorBase):
    platform = Platform.DISCORD

    def __init__(self, provider_service: Any, settings: Any) -> None:
        super().__init__(provider_service)
        self.token = settings.discord_bot_token or ""
        self.app_id = settings.discord_app_id or ""
        self.public_key = settings.discord_public_key or ""
        guilds = settings.discord_guild_ids or ""
        self.guild_ids = [part.strip() for part in guilds.split(",") if part.strip()]
        self._followup_tokens: dict[str, str] = {}

    async def start(self) -> None:
        if not self.token or not self.app_id:
            self.status.connected = False
            self.status.detail = "discord_bot_token or discord_app_id not configured"
            return

        headers = {
            "Authorization": f"Bot {self.token}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                if self.guild_ids:
                    responses = []
                    for guild_id in self.guild_ids:
                        responses.append(
                            await client.put(
                                (
                                    "https://discord.com/api/v10/applications/"
                                    f"{self.app_id}/guilds/{guild_id}/commands"
                                ),
                                headers=headers,
                                json=SLASH_COMMANDS,
                            )
                        )
                    ok = all(resp.is_success for resp in responses)
                    detail = ", ".join(str(resp.status_code) for resp in responses)
                else:
                    resp = await client.put(
                        f"https://discord.com/api/v10/applications/{self.app_id}/commands",
                        headers=headers,
                        json=SLASH_COMMANDS,
                    )
                    ok = resp.is_success
                    detail = str(resp.status_code)

            self.status.connected = ok
            self.status.detail = detail if not ok else None
        except Exception as exc:
            self.status.connected = False
            self.status.detail = str(exc)
            logger.exception("discord.start_failed")

    async def stop(self) -> None:
        self.status.connected = False

    async def send_reply(
        self,
        message: ConnectorMessage,
        text: str,
        *,
        is_streaming_complete: bool = True,
    ) -> None:
        interaction_id = message.platform_message_id
        token = self._followup_tokens.get(interaction_id)
        if not token or not self.app_id:
            return

        payload = {"content": (text or " ")[:2000]}
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                await client.patch(
                    (
                        "https://discord.com/api/v10/webhooks/"
                        f"{self.app_id}/{token}/messages/@original"
                    ),
                    json=payload,
                )
        except Exception:
            self.status.errors += 1
            logger.exception("discord.send_reply_failed")
        finally:
            if is_streaming_complete:
                self._followup_tokens.pop(interaction_id, None)

    def parse_interaction(self, body: dict[str, Any]) -> ConnectorMessage | None:
        if body.get("type") != APPLICATION_COMMAND:
            return None

        data = body.get("data") or {}
        if not isinstance(data, dict):
            return None

        command_name = str(data.get("name") or "").strip()
        if not command_name:
            return None

        interaction_id = str(body.get("id") or "")
        token = str(body.get("token") or "")
        channel_id = str(body.get("channel_id") or "")
        if not interaction_id or not token or not channel_id:
            return None

        member = body.get("member") or {}
        user_obj = member.get("user") if isinstance(member, dict) else None
        if not isinstance(user_obj, dict):
            user_obj = body.get("user") if isinstance(body.get("user"), dict) else {}
        user_id = str(user_obj.get("id") or "")
        if not user_id:
            return None

        options = data.get("options") if isinstance(data.get("options"), list) else []
        option_map = {
            str(opt.get("name")): opt.get("value")
            for opt in options
            if isinstance(opt, dict) and opt.get("name")
        }

        self._followup_tokens[interaction_id] = token

        if command_name == "chat":
            message_text = str(option_map.get("message") or "").strip()
            if not message_text:
                return None
            return ConnectorMessage(
                platform=Platform.DISCORD,
                platform_message_id=interaction_id,
                channel_id=channel_id,
                user_id=user_id,
                text=message_text,
                raw=body,
                is_command=False,
            )

        command = f"/{command_name}"
        command_args = None
        if command_name == "run":
            value = option_map.get("workflow")
            command_args = str(value).strip() if value is not None else None
            if command_args == "":
                command_args = None

        return ConnectorMessage(
            platform=Platform.DISCORD,
            platform_message_id=interaction_id,
            channel_id=channel_id,
            user_id=user_id,
            text=command,
            raw=body,
            is_command=True,
            command=command,
            command_args=command_args,
        )


@router.post("/interactions")
async def discord_interactions(request: Request) -> dict[str, Any]:
    registry = getattr(request.app.state, "connector_registry", None)
    if registry is None:
        raise HTTPException(status_code=503, detail="connector registry unavailable")

    connector = registry.get(Platform.DISCORD)
    if connector is None:
        raise HTTPException(status_code=503, detail="discord connector is disabled")

    body_bytes = await request.body()
    signature = request.headers.get("X-Signature-Ed25519", "")
    timestamp = request.headers.get("X-Signature-Timestamp", "")
    if not _verify_discord_signature(connector.public_key, signature, timestamp, body_bytes):
        raise HTTPException(status_code=401, detail="invalid discord signature")

    body_any = await request.json()
    body: dict[str, Any] = body_any if isinstance(body_any, dict) else {}

    if body.get("type") == INTERACTION_TYPE_PING:
        return {"type": RESPONSE_TYPE_PONG}

    message = connector.parse_interaction(body)
    if message is not None:
        asyncio.create_task(connector.handle_message(message))

    return {"type": DEFERRED_CHANNEL_MESSAGE}
