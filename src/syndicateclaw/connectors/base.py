from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, ClassVar

import structlog

from syndicateclaw.runtime.execution.interceptor import ProtectedExecutionProvider, protected_execution, ExecutionAction
from syndicateclaw.inference.errors import InferenceApprovalRequiredError, InferenceDeniedError
from syndicateclaw.inference.types import ChatInferenceRequest, ChatMessage

logger = structlog.get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Platform(StrEnum):
    TELEGRAM = "telegram"
    DISCORD = "discord"
    SLACK = "slack"
    WEBHOOK = "webhook"


@dataclass(slots=True)
class ConnectorMessage:
    platform: Platform
    platform_message_id: str
    channel_id: str
    user_id: str
    text: str
    raw: dict[str, Any]
    thread_id: str | None = None
    is_command: bool = False
    command: str | None = None
    command_args: str | None = None
    received_at: datetime = field(default_factory=_utcnow)

    @property
    def actor(self) -> str:
        return f"connector:{self.platform.value}:{self.user_id}"

    @property
    def memory_namespace(self) -> str:
        return f"connector:{self.platform.value}:{self.channel_id}"


@dataclass(slots=True)
class ConnectorStatus:
    platform: Platform
    connected: bool = False
    webhook_url: str | None = None
    last_event_at: datetime | None = None
    events_received: int = 0
    errors: int = 0
    detail: str | None = None


class ConnectorBase(ABC):
    platform: ClassVar[Platform]

    def __init__(
        self, 
        provider_service: Any,
        protected_execution_provider: ProtectedExecutionProvider = None,
    ) -> None:
        self.provider_service = provider_service
        self.protected_execution_provider = protected_execution_provider
        self._status = ConnectorStatus(platform=self.platform)

    @property
    def status(self) -> ConnectorStatus:
        return self._status

    @abstractmethod
    async def start(self) -> None:
        """Initialize connector integration (bot registration/webhook setup)."""

    @abstractmethod
    async def stop(self) -> None:
        """Tear down connector integration."""

    @abstractmethod
    @protected_execution(ExecutionAction.CONNECTOR_REPLY_SEND)
    async def send_reply(
        self,
        message: ConnectorMessage,
        text: str,
        *,
        is_streaming_complete: bool = True,
    ) -> None:
        """Send a connector response back to platform."""

    @protected_execution(ExecutionAction.CONNECTOR_MESSAGE_HANDLE)
    async def handle_message(self, message: ConnectorMessage) -> None:
        self._status.events_received += 1
        self._status.last_event_at = _utcnow()

        try:
            if message.is_command:
                await self.handle_command(message)
                return

            metadata = {
                "platform": message.platform.value,
                "channel": message.channel_id,
                "user": message.user_id,
                "message_id": message.platform_message_id,
            }

            req_data: dict[str, Any] = {
                "messages": [ChatMessage(role="user", content=message.text)],
                "actor": message.actor,
                "scope_type": "NAMESPACE",
                "scope_id": message.memory_namespace,
                "trace_id": message.platform_message_id,
            }
            if "metadata" in ChatInferenceRequest.model_fields:
                req_data["metadata"] = metadata
            req = ChatInferenceRequest(**req_data)

            buffer = ""
            last_flush = 0
            async for delta in self.provider_service.stream_chat(req):
                buffer += delta
                if len(buffer) - last_flush >= 80:
                    await self.send_reply(
                        message,
                        buffer,
                        is_streaming_complete=False,
                    )
                    last_flush = len(buffer)

            await self.send_reply(message, buffer, is_streaming_complete=True)
        except InferenceDeniedError as exc:
            await self.send_reply(message, f"⛔ Request denied: {exc}")
        except InferenceApprovalRequiredError:
            await self.send_reply(message, "⏳ Requires approval…")
        except Exception as exc:  # pragma: no cover - safety net
            self._status.errors += 1
            logger.exception(
                "connector.handle_message_failed",
                platform=self.platform.value,
                channel_id=message.channel_id,
            )
            await self.send_reply(message, f"❌ Error: {exc}")

    async def handle_command(self, message: ConnectorMessage) -> None:
        command = (message.command or "").strip().lower()

        if command == "/help":
            await self.send_reply(
                message,
                "Commands:\n/help\n/status\n/run <workflow_name>",
            )
            return

        if command == "/status":
            state = "connected" if self._status.connected else "disconnected"
            await self.send_reply(
                message,
                (
                    f"{self.platform.value}: {state}\n"
                    f"events={self._status.events_received}\n"
                    f"errors={self._status.errors}"
                ),
            )
            return

        if command == "/run":
            workflow = (message.command_args or "").strip()
            if not workflow:
                await self.send_reply(message, "Usage: /run <workflow_name>")
                return
            await self.send_reply(
                message,
                f"Workflow trigger accepted: {workflow} (execution wiring pending)",
            )
            return

        await self.send_reply(message, "Unknown command. Try /help.")
