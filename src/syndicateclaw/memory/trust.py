from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from syndicateclaw.db.models import MemoryRecord as DBMemoryRecord
from syndicateclaw.models import (
    MemoryDeletionStatus,
    MemorySourceType,
)

logger = structlog.get_logger(__name__)

# Source types ordered by base trustworthiness
_SOURCE_TRUST_CEILING: dict[str, float] = {
    MemorySourceType.HUMAN.value: 1.0,
    MemorySourceType.SYSTEM.value: 0.95,
    MemorySourceType.EXTERNAL.value: 0.8,
    MemorySourceType.LLM.value: 0.7,
    MemorySourceType.DERIVED.value: 0.6,
}


class MemoryTrustService:
    """Manages trust scoring, decay, and conflict resolution for memory records.

    Trust model invariants:
    - Trust decays linearly from last_validated_at at the record's decay_rate
    - Frozen records (human-validated) do not decay
    - Conflict detection creates a conflict_set linking disagreeing records
    - Records below a configurable threshold are not served for decision-making
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        min_usable_trust: float = 0.3,
    ) -> None:
        self._session_factory = session_factory
        self._min_usable_trust = min_usable_trust

    def compute_effective_trust(
        self,
        trust_score: float,
        decay_rate: float,
        last_validated_at: datetime | None,
        frozen: bool,
    ) -> float:
        """Calculate current effective trust score after time decay."""
        if frozen:
            return trust_score

        if last_validated_at is None:
            return trust_score

        elapsed_days = (datetime.now(UTC) - last_validated_at).total_seconds() / 86400
        decayed = trust_score - (decay_rate * elapsed_days)
        return max(0.0, min(1.0, decayed))

    def is_usable(self, effective_trust: float) -> bool:
        """Whether a record's trust is above the usability threshold."""
        return effective_trust >= self._min_usable_trust

    async def apply_decay(self) -> int:
        """Bulk-update trust scores for all non-frozen, active records.
        Returns count of records whose trust dropped below threshold.
        """
        degraded = 0
        async with self._session_factory() as session, session.begin():
            stmt = select(DBMemoryRecord).where(
                DBMemoryRecord.deletion_status == MemoryDeletionStatus.ACTIVE.value,
                DBMemoryRecord.trust_frozen.is_(False),
                DBMemoryRecord.last_validated_at.is_not(None),
            )
            result = await session.execute(stmt)
            records = list(result.scalars().all())

            now = datetime.now(UTC)
            for rec in records:
                last_v = rec.last_validated_at
                if last_v is None:
                    continue
                elapsed_days = (now - last_v).total_seconds() / 86400
                new_score = max(
                    0.0,
                    (rec.trust_score or 1.0)
                    - ((rec.decay_rate or 0.01) * elapsed_days),
                )
                if new_score != rec.trust_score:
                    rec.trust_score = new_score
                    rec.updated_at = now
                    if new_score < self._min_usable_trust:
                        degraded += 1

        logger.info("memory.trust_decay_applied", records_processed=len(records), degraded=degraded)
        return degraded

    async def validate_record(self, record_id: str, validator: str) -> float:
        """Mark a record as validated, resetting its trust score to the ceiling
        for its source type. Returns the new trust score.
        """
        now = datetime.now(UTC)
        async with self._session_factory() as session, session.begin():
            rec = await session.get(DBMemoryRecord, record_id)
            if rec is None:
                raise ValueError(f"Memory record {record_id} not found")

            ceiling = _SOURCE_TRUST_CEILING.get(rec.source_type, 0.8)
            rec.trust_score = ceiling
            rec.last_validated_at = now
            rec.validation_count = (rec.validation_count or 0) + 1
            rec.updated_at = now

        logger.info(
            "memory.validated",
            record_id=record_id,
            validator=validator,
            new_trust=ceiling,
        )
        return ceiling

    async def freeze_record(self, record_id: str, actor: str) -> None:
        """Freeze a record so its trust no longer decays."""
        async with self._session_factory() as session, session.begin():
            rec = await session.get(DBMemoryRecord, record_id)
            if rec is None:
                raise ValueError(f"Memory record {record_id} not found")
            rec.trust_frozen = True
            rec.updated_at = datetime.now(UTC)

        logger.info("memory.frozen", record_id=record_id, actor=actor)

    async def detect_conflicts(
        self, namespace: str, key: str
    ) -> list[str]:
        """Find records that conflict (same namespace/key but different values).
        Links them via conflict_set_id and downgrades trust on all conflicting records.
        Returns list of conflict_set_ids created.
        """
        from ulid import ULID

        conflict_sets: list[str] = []

        async with self._session_factory() as session, session.begin():
            stmt = select(DBMemoryRecord).where(
                DBMemoryRecord.namespace == namespace,
                DBMemoryRecord.key == key,
                DBMemoryRecord.deletion_status == MemoryDeletionStatus.ACTIVE.value,
            )
            result = await session.execute(stmt)
            records = list(result.scalars().all())

            if len(records) <= 1:
                return []

            values_seen: dict[str, list[DBMemoryRecord]] = {}
            for rec in records:
                val_key = str(rec.value)
                values_seen.setdefault(val_key, []).append(rec)

            if len(values_seen) <= 1:
                return []

            conflict_set_id = str(ULID())
            now = datetime.now(UTC)
            for rec in records:
                rec.conflict_set_id = conflict_set_id
                if not rec.trust_frozen:
                    rec.trust_score = max(0.0, (rec.trust_score or 1.0) * 0.5)
                rec.updated_at = now
            conflict_sets.append(conflict_set_id)

        logger.warning(
            "memory.conflict_detected",
            namespace=namespace,
            key=key,
            conflict_set_id=conflict_set_id,
            record_count=len(records),
        )
        return conflict_sets

    async def get_trust_report(self, namespace: str) -> list[dict[str, Any]]:
        """Return trust scores for all active records in a namespace."""
        async with self._session_factory() as session:
            stmt = select(DBMemoryRecord).where(
                DBMemoryRecord.namespace == namespace,
                DBMemoryRecord.deletion_status == MemoryDeletionStatus.ACTIVE.value,
            )
            result = await session.execute(stmt)
            records = list(result.scalars().all())

        report = []
        for rec in records:
            effective = self.compute_effective_trust(
                rec.trust_score or 1.0,
                rec.decay_rate or 0.01,
                rec.last_validated_at,
                rec.trust_frozen or False,
            )
            report.append({
                "id": rec.id,
                "namespace": rec.namespace,
                "key": rec.key,
                "source_type": rec.source_type,
                "trust_score": rec.trust_score,
                "effective_trust": round(effective, 4),
                "usable": self.is_usable(effective),
                "frozen": rec.trust_frozen,
                "last_validated_at": (
                    rec.last_validated_at.isoformat()
                    if rec.last_validated_at
                    else None
                ),
                "conflict_set_id": rec.conflict_set_id,
            })
        return report
