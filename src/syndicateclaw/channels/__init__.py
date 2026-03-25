from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ChannelConnector(Protocol):
    """Protocol that all channel connectors must satisfy."""

    channel_name: str

    async def send(self, message: str, recipient: str, metadata: dict[str, Any]) -> bool: ...

    async def receive(self) -> AsyncIterator[ChannelMessage]: ...


@dataclass(frozen=True, slots=True)
class ChannelMessage:
    """Immutable message received from a channel."""

    channel: str
    sender: str
    content: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)
