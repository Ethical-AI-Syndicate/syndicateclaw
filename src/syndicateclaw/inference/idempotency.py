"""Database-backed idempotency — atomic acquire via PostgreSQL UNIQUE + INSERT ON CONFLICT.

Uses the same SHA-256 canonical hash as audit evidence (syndicateclaw.inference.hashing).

Stale in-progress rows (PENDING/EXECUTING with updated_at older than ``stale_after_seconds``)
are marked FAILED with ``failure_reason='stale_in_progress'``. The idempotency_key row remains;
callers must use a new idempotency key to start a new logical inference (spec: same key+hash
→ same inference_id; a stale failure is a terminal outcome for that key).

See docs/superpowers/specs/2025-03-24-provider-integration-architecture-design.md (1.4, 4).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from ulid import ULID

from syndicateclaw.db.models import InferenceEnvelope
from syndicateclaw.inference.errors import IdempotencyConflictError
from syndicateclaw.inference.types import InferenceEnvelopeStatus

STALE_FAILURE_REASON = "stale_in_progress"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class IdempotencyStore:
    """Postgres-backed idempotency with UNIQUE(idempotency_key) and ON CONFLICT DO NOTHING."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        stale_after_seconds: float = 300.0,
    ) -> None:
        self._session_factory = session_factory
        self._stale_after_seconds = stale_after_seconds

    async def acquire(
        self,
        *,
        idempotency_key: str,
        request_hash: str,
        inference_id: str,
        system_config_version: str,
        trace_id: str | None = None,
    ) -> tuple[InferenceEnvelope, bool]:
        """Atomically insert a new envelope or return the existing row.

        ``request_hash`` must be ``canonical_json_hash(...)`` of the idempotent payload.

        Returns ``(row, is_new)``. ``is_new`` is True only when this call created the row.

        Raises:
            IdempotencyConflictError: same idempotency_key but different request_hash.
        """
        now = _utcnow()
        cutoff = now - timedelta(seconds=self._stale_after_seconds)

        async with self._session_factory() as session, session.begin():
            await session.execute(
                update(InferenceEnvelope)
                .where(
                    InferenceEnvelope.idempotency_key == idempotency_key,
                    InferenceEnvelope.status.in_(
                        [
                            InferenceEnvelopeStatus.PENDING.value,
                            InferenceEnvelopeStatus.EXECUTING.value,
                        ]
                    ),
                    InferenceEnvelope.updated_at < cutoff,
                )
                .values(
                    status=InferenceEnvelopeStatus.FAILED.value,
                    failure_reason=STALE_FAILURE_REASON,
                    updated_at=now,
                )
            )

            new_id = str(ULID())
            ins = (
                pg_insert(InferenceEnvelope)
                .values(
                    id=new_id,
                    idempotency_key=idempotency_key,
                    request_hash=request_hash,
                    inference_id=inference_id,
                    system_config_version=system_config_version,
                    status=InferenceEnvelopeStatus.PENDING.value,
                    trace_id=trace_id,
                    first_seen_at=now,
                    last_seen_at=now,
                )
                .on_conflict_do_nothing(
                    index_elements=["idempotency_key"],
                )
                .returning(InferenceEnvelope)
            )
            res = await session.execute(ins)
            inserted = res.scalars().first()
            if inserted is not None:
                return inserted, True

            stmt = (
                select(InferenceEnvelope)
                .where(InferenceEnvelope.idempotency_key == idempotency_key)
                .with_for_update()
            )
            row = (await session.execute(stmt)).scalar_one()
            if row.request_hash != request_hash:
                raise IdempotencyConflictError(
                    "idempotency_key already bound to a different request_hash",
                )
            row.last_seen_at = now
            await session.flush()
            return row, False
