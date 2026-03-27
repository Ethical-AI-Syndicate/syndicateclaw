from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from syndicateclaw.db.models import InferenceEnvelope


async def cleanup_expired_idempotency_rows(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    ttl_seconds: int,
) -> int:
    """Delete idempotency envelopes older than ``ttl_seconds`` and return row count."""
    cutoff = datetime.now(UTC) - timedelta(seconds=ttl_seconds)
    async with session_factory() as session, session.begin():
        result = await session.execute(
            delete(InferenceEnvelope).where(InferenceEnvelope.updated_at < cutoff)
        )
    return int(result.rowcount or 0)
