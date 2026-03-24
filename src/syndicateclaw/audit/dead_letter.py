from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from syndicateclaw.db.models import DeadLetterRecord as DBDeadLetterRecord
from syndicateclaw.models import AuditEvent, DeadLetterStatus

logger = structlog.get_logger(__name__)


def _classify_error(error: str) -> str:
    """Classify an error as transient or permanent based on heuristics."""
    permanent_indicators = [
        "validation", "schema", "invalid", "malformed",
        "permission", "forbidden", "not found",
    ]
    for indicator in permanent_indicators:
        if indicator in error.lower():
            return "permanent"
    return "transient"


class DeadLetterQueue:
    """Database-backed dead letter queue for failed audit events.

    All dead-lettered events are persisted to Postgres immediately,
    surviving process restarts. Classification (transient/permanent)
    determines retry eligibility.
    """

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._session_factory = session_factory

    async def enqueue(self, event: AuditEvent, error: str) -> str:
        """Persist a failed event to the dead letter table. Returns the DLQ record ID."""
        category = _classify_error(error)

        async with self._session_factory() as session, session.begin():
            row = DBDeadLetterRecord(
                event_type=event.event_type.value if hasattr(event.event_type, 'value') else str(event.event_type),
                event_payload=event.model_dump(mode="json"),
                error_message=error,
                error_category=category,
                status=DeadLetterStatus.PENDING.value,
                retry_count=0,
                max_retries=3 if category == "transient" else 0,
            )
            session.add(row)
            await session.flush()
            record_id = row.id

        logger.warning(
            "dead_letter_enqueued",
            event_id=event.id,
            event_type=event.event_type.value if hasattr(event.event_type, 'value') else str(event.event_type),
            error=error,
            category=category,
            dlq_record_id=record_id,
        )
        return record_id

    async def retry_all(self, audit_service: Any) -> int:
        """Attempt to re-persist eligible dead-lettered events.

        Only retries transient errors that haven't exhausted their retry count.
        Returns the number successfully retried.
        """
        retried = 0

        async with self._session_factory() as session, session.begin():
            stmt = select(DBDeadLetterRecord).where(
                DBDeadLetterRecord.status == DeadLetterStatus.PENDING.value,
                DBDeadLetterRecord.error_category == "transient",
            )
            result = await session.execute(stmt)
            records = list(result.scalars().all())

        for rec in records:
            if rec.retry_count >= rec.max_retries:
                async with self._session_factory() as session, session.begin():
                    row = await session.get(DBDeadLetterRecord, rec.id)
                    if row:
                        row.status = DeadLetterStatus.FAILED.value
                        row.error_message = f"{row.error_message} | max retries exhausted"
                continue

            try:
                event = AuditEvent.model_validate(rec.event_payload)
                await audit_service.emit(event)
                retried += 1

                async with self._session_factory() as session, session.begin():
                    row = await session.get(DBDeadLetterRecord, rec.id)
                    if row:
                        row.status = DeadLetterStatus.RESOLVED.value
                        row.resolved_at = datetime.now(UTC)
                        row.resolved_by = "system:dlq_retry"

                logger.info("dead_letter_retried", dlq_id=rec.id)

            except Exception as exc:
                async with self._session_factory() as session, session.begin():
                    row = await session.get(DBDeadLetterRecord, rec.id)
                    if row:
                        row.retry_count += 1
                        row.last_retry_at = datetime.now(UTC)
                        row.error_message = f"{row.error_message} | retry_{row.retry_count}: {exc}"

                logger.error("dead_letter_retry_failed", dlq_id=rec.id, error=str(exc))

        logger.info("dead_letter_retry_complete", retried=retried)
        return retried

    async def resolve(self, record_id: str, actor: str, reason: str = "") -> None:
        """Manually resolve a dead letter record."""
        async with self._session_factory() as session, session.begin():
            row = await session.get(DBDeadLetterRecord, record_id)
            if row is None:
                raise ValueError(f"Dead letter record {record_id} not found")
            row.status = DeadLetterStatus.RESOLVED.value
            row.resolved_at = datetime.now(UTC)
            row.resolved_by = actor
            if reason:
                row.error_message = f"{row.error_message} | resolved: {reason}"

        logger.info("dead_letter_resolved", dlq_id=record_id, actor=actor)

    async def size(self) -> int:
        """Count of pending dead letter records."""
        async with self._session_factory() as session:
            stmt = select(DBDeadLetterRecord).where(
                DBDeadLetterRecord.status == DeadLetterStatus.PENDING.value,
            )
            result = await session.execute(stmt)
            return len(list(result.scalars().all()))
