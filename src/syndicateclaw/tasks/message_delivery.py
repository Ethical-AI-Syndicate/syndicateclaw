from __future__ import annotations

import asyncio

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from syndicateclaw.db.models import DeadLetterRecord
from syndicateclaw.services.message_service import MessageService

logger = structlog.get_logger(__name__)


async def run_message_delivery_loop(
    message_service: MessageService,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    poll_interval_seconds: int = 5,
) -> None:
    while True:
        pending = await message_service.pending_messages(limit=100)
        for msg in pending:
            delivered = False
            for attempt in range(5):
                try:
                    await message_service.mark_delivered(msg.id)
                    delivered = True
                    break
                except Exception:
                    await asyncio.sleep(2**attempt)
            if not delivered:
                await message_service.mark_delivery_failed(msg.id)
                async with session_factory() as session, session.begin():
                    session.add(
                        DeadLetterRecord(
                            event_type="agent_message",
                            event_payload={
                                "source_type": "agent_message",
                                "message_id": msg.id,
                                "status": "FAILED",
                            },
                            error_message="message delivery failed after max retries",
                            error_category="transient",
                            status="PENDING",
                        )
                    )
                logger.warning("message.delivery_failed", message_id=msg.id)
        await asyncio.sleep(poll_interval_seconds)
