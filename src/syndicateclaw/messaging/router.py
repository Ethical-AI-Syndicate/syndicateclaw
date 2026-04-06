from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from syndicateclaw.db.models import AgentMessage, AuditEvent, DeadLetterRecord


class HopLimitExceededError(Exception):
    """Raised when a message exceeds the configured relay hop limit."""


class MessageRouter:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        max_hops: int,
    ) -> None:
        self._session_factory = session_factory
        self._max_hops = max_hops

    async def route(self, message: AgentMessage) -> AgentMessage:
        if message.hop_count >= self._max_hops:
            await self._mark_hop_limit_exceeded(message)
            raise HopLimitExceededError(
                f"Message {message.id} exceeded max hops ({message.hop_count})"
            )
        return message

    async def _mark_hop_limit_exceeded(self, message: AgentMessage) -> None:
        now = datetime.now(UTC)
        async with self._session_factory() as session, session.begin():
            row = await session.get(AgentMessage, message.id)
            if row is not None:
                row.status = "HOP_LIMIT_EXCEEDED"

            session.add(
                AuditEvent(
                    event_type="message.hop_limit_exceeded",
                    actor=message.sender,
                    resource_type="agent_message",
                    resource_id=message.id,
                    action="terminate",
                    details={
                        "hop_count": message.hop_count,
                        "max_hops": self._max_hops,
                    },
                )
            )
            session.add(
                DeadLetterRecord(
                    event_type="agent_message",
                    event_payload={
                        "source_type": "agent_message",
                        "message_id": message.id,
                        "hop_count": message.hop_count,
                        "max_hops": self._max_hops,
                        "at": now.isoformat(),
                    },
                    error_message="message hop limit exceeded",
                    error_category="permanent",
                    status="PENDING",
                )
            )

    def relay_payload(self, message: AgentMessage) -> dict[str, Any]:
        return {
            "conversation_id": message.conversation_id,
            "sender": message.sender,
            "recipient": message.recipient,
            "topic": message.topic,
            "message_type": message.message_type,
            "content": message.content,
            "metadata": message.metadata_,
            "priority": message.priority,
            "ttl_seconds": message.ttl_seconds,
            "hop_count": message.hop_count + 1,
            "parent_message_id": message.id,
            "expires_at": message.expires_at,
        }
