from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import structlog

from syndicateclaw.channels import ChannelMessage

logger = structlog.get_logger(__name__)


class ConsoleChannel:
    """Channel connector that logs messages via structlog.

    Useful for local development and testing — no external dependencies required.
    """

    channel_name: str = "console"

    async def send(self, message: str, recipient: str, metadata: dict | None = None) -> bool:
        metadata = metadata or {}
        logger.info(
            "console_channel_send",
            recipient=recipient,
            message=message,
            metadata=metadata,
        )
        return True

    async def receive(self) -> AsyncIterator[ChannelMessage]:
        """Yield a single sentinel message, then stop.

        Override or extend in a subclass to read from stdin or a file
        for interactive development sessions.
        """
        yield ChannelMessage(
            channel=self.channel_name,
            sender="console",
            content="<no inbound messages — console channel>",
            timestamp=datetime.now(UTC),
        )
