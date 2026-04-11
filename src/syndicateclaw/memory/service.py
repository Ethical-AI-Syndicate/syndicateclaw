from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from syndicateclaw.db.models import AuditEvent as DBAuditEvent
from syndicateclaw.db.models import MemoryRecord as DBMemoryRecord
from syndicateclaw.db.repository import AuditEventRepository, MemoryRecordRepository
from syndicateclaw.models import (
    AuditEventType,
    MemoryDeletionStatus,
    MemoryLineage,
    MemoryRecord,
)

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from syndicateclaw.memory.schema import NamespaceSchemaRegistry

logger = structlog.get_logger(__name__)


def _check_nesting_depth(obj: Any, max_depth: int, current: int) -> None:
    """Reject deeply nested structures that could cause processing issues."""
    if current > max_depth:
        raise ValueError(f"Value nesting depth exceeds maximum of {max_depth}")
    if isinstance(obj, dict):
        for v in obj.values():
            _check_nesting_depth(v, max_depth, current + 1)
    elif isinstance(obj, list):
        for item in obj:
            _check_nesting_depth(item, max_depth, current + 1)


class MemoryService:
    """Manages episodic, semantic, and structured memory with provenance
    tracking, retention rules, and access control."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        redis_client: Redis | None = None,
        *,
        max_value_bytes: int = 1_048_576,
        max_key_length: int = 256,
        max_namespace_length: int = 128,
        max_nesting_depth: int = 20,
        schema_registry: NamespaceSchemaRegistry | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._redis = redis_client
        self._max_value_bytes = max_value_bytes
        self._max_key_length = max_key_length
        self._max_namespace_length = max_namespace_length
        self._max_nesting_depth = max_nesting_depth
        self._schema_registry = schema_registry

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def write(self, record: MemoryRecord, actor: str) -> MemoryRecord:
        """Validate, persist, and audit a new memory record."""
        self._validate_provenance(record)
        self._validate_confidence(record.confidence)
        self._validate_write_guardrails(record)
        self._validate_namespace_schema(record.namespace, record.value)

        if record.ttl_seconds and not record.expires_at:
            record.expires_at = datetime.now(UTC) + timedelta(seconds=record.ttl_seconds)

        async with self._session_factory() as session, session.begin():
            repo = MemoryRecordRepository(session)
            db_record = self._domain_to_db(record)
            db_record = await repo.create(db_record)
            persisted = self._db_to_domain(db_record)

            audit_repo = AuditEventRepository(session)
            await self._emit_audit(
                audit_repo,
                AuditEventType.MEMORY_CREATED,
                actor,
                persisted,
                {"action": "write", "namespace": persisted.namespace, "key": persisted.key},
            )

        await self._invalidate_cache(record.namespace, record.key)

        logger.info(
            "memory.write",
            record_id=persisted.id,
            namespace=persisted.namespace,
            key=persisted.key,
            actor=actor,
        )
        return persisted

    async def read(self, namespace: str, key: str, actor: str) -> MemoryRecord | None:
        """Read a memory record by namespace/key, checking cache first."""
        cached = await self._get_cached(namespace, key)
        if cached is not None:
            if not self._check_access_policy(cached, actor):
                logger.warning(
                    "memory.access_denied",
                    record_id=cached.id,
                    namespace=namespace,
                    key=key,
                    actor=actor,
                    policy=cached.access_policy,
                    source="cache",
                )
                return None
            return cached

        async with self._session_factory() as session, session.begin():
            repo = MemoryRecordRepository(session)
            db_record = await repo.get_by_key(namespace, key)

            if db_record is None:
                return None

            record = self._db_to_domain(db_record)

            if record.deletion_status != MemoryDeletionStatus.ACTIVE:
                return None

            if record.expires_at and record.expires_at <= datetime.now(UTC):
                return None

            if not self._check_access_policy(record, actor):
                logger.warning(
                    "memory.access_denied",
                    record_id=record.id,
                    namespace=namespace,
                    key=key,
                    actor=actor,
                    policy=record.access_policy,
                )
                return None

            audit_repo = AuditEventRepository(session)
            await self._emit_audit(
                audit_repo,
                AuditEventType.MEMORY_ACCESSED,
                actor,
                record,
                {"action": "read", "namespace": namespace, "key": key},
            )

        if record.access_policy == "default":
            await self._set_cached(namespace, key, record)

        logger.info(
            "memory.read",
            record_id=record.id,
            namespace=namespace,
            key=key,
            actor=actor,
        )
        return record

    async def search(
        self,
        namespace: str,
        filters: dict[str, Any],
        actor: str,
        *,
        include_expired: bool = False,
    ) -> list[MemoryRecord]:
        """Query records by namespace with optional filters."""
        async with self._session_factory() as session, session.begin():
            repo = MemoryRecordRepository(session)
            db_records = await repo.get_by_namespace(namespace, include_expired=include_expired)

            now = datetime.now(UTC)
            results: list[MemoryRecord] = []
            for db_rec in db_records:
                rec = self._db_to_domain(db_rec)
                if not include_expired:
                    if rec.deletion_status != MemoryDeletionStatus.ACTIVE:
                        continue
                    if rec.expires_at and rec.expires_at <= now:
                        continue

                if not self._matches_filters(rec, filters):
                    continue

                if not self._check_access_policy(rec, actor):
                    continue

                results.append(rec)

            audit_repo = AuditEventRepository(session)
            await self._emit_audit(
                audit_repo,
                AuditEventType.MEMORY_ACCESSED,
                actor,
                None,
                {
                    "action": "search",
                    "namespace": namespace,
                    "filters": filters,
                    "result_count": len(results),
                },
            )

        logger.info(
            "memory.search",
            namespace=namespace,
            result_count=len(results),
            actor=actor,
        )
        return results

    async def update(self, record_id: str, updates: dict[str, Any], actor: str) -> MemoryRecord:
        """Update a record, appending provenance lineage."""
        async with self._session_factory() as session, session.begin():
            repo = MemoryRecordRepository(session)
            db_record = await repo.get(record_id)
            if db_record is None:
                raise ValueError(f"Memory record {record_id!r} not found")

            existing = self._db_to_domain(db_record)
            if existing.deletion_status != MemoryDeletionStatus.ACTIVE:
                raise ValueError(f"Memory record {record_id!r} is deleted")

            allowed_fields = {"value", "confidence", "tags", "ttl_seconds", "access_policy"}
            for field in updates:
                if field not in allowed_fields:
                    raise ValueError(f"Cannot update field {field!r}")

            if "confidence" in updates:
                self._validate_confidence(updates["confidence"])

            if "value" in updates:
                val_bytes = len(json.dumps(updates["value"], default=str).encode())
                if val_bytes > self._max_value_bytes:
                    raise ValueError(
                        f"Value too large: {val_bytes} bytes > {self._max_value_bytes} byte limit"
                    )
                self._validate_namespace_schema(existing.namespace, updates["value"])

            lineage = existing.lineage
            if existing.id not in lineage.parent_ids:
                lineage.parent_ids.append(existing.id)
            lineage.derivation_method = "update"

            for field, value in updates.items():
                setattr(db_record, field, value)

            if "ttl_seconds" in updates and updates["ttl_seconds"] is not None:
                db_record.expires_at = datetime.now(UTC) + timedelta(seconds=updates["ttl_seconds"])

            db_record.lineage = lineage.model_dump()
            db_record.updated_at = datetime.now(UTC)

            db_record = await repo.update(db_record)
            updated = self._db_to_domain(db_record)

            audit_repo = AuditEventRepository(session)
            await self._emit_audit(
                audit_repo,
                AuditEventType.MEMORY_UPDATED,
                actor,
                updated,
                {"action": "update", "fields": list(updates.keys())},
            )

        await self._invalidate_cache(updated.namespace, updated.key)

        logger.info(
            "memory.update",
            record_id=record_id,
            fields=list(updates.keys()),
            actor=actor,
        )
        return updated

    async def delete(self, record_id: str, actor: str, *, hard: bool = False) -> None:
        """Soft-delete (mark) or hard-delete (purge) a memory record."""
        async with self._session_factory() as session, session.begin():
            repo = MemoryRecordRepository(session)

            if hard:
                db_record = await repo.get(record_id)
                if db_record is not None:
                    record = self._db_to_domain(db_record)
                    await repo.delete(record_id)

                    audit_repo = AuditEventRepository(session)
                    await self._emit_audit(
                        audit_repo,
                        AuditEventType.MEMORY_DELETED,
                        actor,
                        record,
                        {"action": "hard_delete"},
                    )
                    await self._invalidate_cache(record.namespace, record.key)
            else:
                db_record = await repo.get(record_id)
                if db_record is None:
                    raise ValueError(f"Memory record {record_id!r} not found")

                record = self._db_to_domain(db_record)
                db_record.deletion_status = MemoryDeletionStatus.MARKED_FOR_DELETION.value
                db_record.deleted_at = datetime.now(UTC)
                db_record.updated_at = datetime.now(UTC)
                await repo.update(db_record)

                audit_repo = AuditEventRepository(session)
                await self._emit_audit(
                    audit_repo,
                    AuditEventType.MEMORY_DELETED,
                    actor,
                    record,
                    {"action": "soft_delete"},
                )
                await self._invalidate_cache(record.namespace, record.key)

        logger.info(
            "memory.delete",
            record_id=record_id,
            hard=hard,
            actor=actor,
        )

    async def enforce_retention(self) -> int:
        """Purge expired and soft-deleted records past their retention
        period. Returns the number of records purged."""
        async with self._session_factory() as session, session.begin():
            repo = MemoryRecordRepository(session)
            purged_count = await repo.purge_expired()

            if purged_count > 0:
                audit_repo = AuditEventRepository(session)
                await self._emit_audit(
                    audit_repo,
                    AuditEventType.MEMORY_EXPIRED,
                    "system:retention",
                    None,
                    {"action": "enforce_retention", "purged_count": purged_count},
                )

        logger.info("memory.enforce_retention", purged_count=purged_count)
        return purged_count

    async def get_lineage(self, record_id: str) -> list[MemoryRecord]:
        """Traverse parent_ids recursively to build the full provenance
        chain for a record."""
        chain: list[MemoryRecord] = []
        visited: set[str] = set()

        async with self._session_factory() as session, session.begin():
            repo = MemoryRecordRepository(session)
            await self._walk_lineage(repo, record_id, chain, visited)

        return chain

    async def list_namespaces(self, prefix: str | None = None) -> list[dict[str, Any]]:
        """Return grouped namespace summaries for active records."""
        stmt = (
            select(
                DBMemoryRecord.namespace,
                func.count(DBMemoryRecord.id),
                func.max(DBMemoryRecord.updated_at),
            )
            .where(DBMemoryRecord.deletion_status == MemoryDeletionStatus.ACTIVE.value)
            .group_by(DBMemoryRecord.namespace)
            .order_by(DBMemoryRecord.namespace.asc())
        )
        if prefix:
            stmt = stmt.where(DBMemoryRecord.namespace.like(f"{prefix}%"))

        async with self._session_factory() as session:
            rows = (await session.execute(stmt)).all()

        return [
            {
                "namespace": namespace,
                "prefix": namespace.split(":", 1)[0],
                "records": records,
                "last_updated_at": last_updated_at,
            }
            for namespace, records, last_updated_at in rows
        ]

    async def purge_namespace(self, namespace: str, actor: str) -> int:
        """Hard-delete all records in a namespace and emit a single audit event."""
        purged_records: list[tuple[str, str]] = []

        async with self._session_factory() as session, session.begin():
            repo = MemoryRecordRepository(session)
            rows = await repo.get_by_namespace(namespace, include_expired=True)
            for row in rows:
                purged_records.append((row.namespace, row.key))
                await repo.delete(row.id)

            if purged_records:
                audit_repo = AuditEventRepository(session)
                await self._emit_audit(
                    audit_repo,
                    AuditEventType.MEMORY_DELETED,
                    actor,
                    None,
                    {
                        "action": "purge_namespace",
                        "namespace": namespace,
                        "purged_count": len(purged_records),
                    },
                )

        for record_namespace, key in purged_records:
            await self._invalidate_cache(record_namespace, key)

        logger.warning(
            "memory.namespace_purged",
            namespace=namespace,
            purged_count=len(purged_records),
            actor=actor,
        )
        return len(purged_records)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _walk_lineage(
        self,
        repo: MemoryRecordRepository,
        record_id: str,
        chain: list[MemoryRecord],
        visited: set[str],
    ) -> None:
        if record_id in visited:
            return
        visited.add(record_id)

        db_record = await repo.get(record_id)
        if db_record is None:
            return

        record = self._db_to_domain(db_record)
        chain.append(record)

        for parent_id in record.lineage.parent_ids:
            await self._walk_lineage(repo, parent_id, chain, visited)

    @staticmethod
    def _check_access_policy(record: MemoryRecord, actor: str) -> bool:
        """Check whether the actor is allowed to read this record.

        Policy enforcement rules:
        - 'default': any authenticated actor
        - 'owner_only': only the record's original actor
        - 'system_only': only system-prefixed actors
        - 'restricted': denied unless actor matches record actor
        """
        policy = record.access_policy
        if policy == "default":
            return True
        if policy == "owner_only":
            return actor == record.actor
        if policy == "system_only":
            return actor.startswith("system:")
        if policy == "restricted":
            return actor == record.actor
        return False

    @staticmethod
    def _validate_provenance(record: MemoryRecord) -> None:
        if not record.source:
            raise ValueError("Memory record must have a source")
        if not record.actor:
            raise ValueError("Memory record must have an actor")

    @staticmethod
    def _validate_confidence(confidence: float) -> None:
        if not 0.0 <= confidence <= 1.0:
            raise ValueError(f"Confidence must be between 0.0 and 1.0, got {confidence}")

    def _validate_write_guardrails(self, record: MemoryRecord) -> None:
        """Enforce size and structure constraints on memory writes."""
        if len(record.namespace) > self._max_namespace_length:
            raise ValueError(
                f"Namespace too long: {len(record.namespace)} > {self._max_namespace_length}"
            )

        if len(record.key) > self._max_key_length:
            raise ValueError(f"Key too long: {len(record.key)} > {self._max_key_length}")

        value_bytes = len(json.dumps(record.value, default=str).encode())
        if value_bytes > self._max_value_bytes:
            raise ValueError(
                f"Value too large: {value_bytes} bytes > {self._max_value_bytes} byte limit"
            )

        if isinstance(record.value, dict):
            _check_nesting_depth(record.value, self._max_nesting_depth, 0)

    def _validate_namespace_schema(self, namespace: str, value: Any) -> None:
        """Validate value against registered namespace schema, if any."""
        if self._schema_registry is None:
            return
        self._schema_registry.validate(namespace, value)

    @staticmethod
    def _matches_filters(record: MemoryRecord, filters: dict[str, Any]) -> bool:
        for field, value in filters.items():
            record_value = getattr(record, field, None)
            if record_value != value:
                return False
        return True

    def _cache_key(self, namespace: str, key: str) -> str:
        return f"syndicateclaw:memory:{namespace}:{key}"

    async def _invalidate_cache(self, namespace: str, key: str) -> None:
        if self._redis is None:
            return
        try:
            await self._redis.delete(self._cache_key(namespace, key))
        except Exception:
            logger.warning(
                "memory.cache_invalidate_failed",
                namespace=namespace,
                key=key,
                exc_info=True,
            )

    async def _get_cached(self, namespace: str, key: str) -> MemoryRecord | None:
        if self._redis is None:
            return None
        try:
            raw = await self._redis.get(self._cache_key(namespace, key))
            if raw is None:
                return None
            return MemoryRecord.model_validate_json(raw)
        except Exception:
            logger.warning(
                "memory.cache_read_failed",
                namespace=namespace,
                key=key,
                exc_info=True,
            )
            return None

    async def _set_cached(self, namespace: str, key: str, record: MemoryRecord) -> None:
        if self._redis is None:
            return
        try:
            ttl = record.ttl_seconds or 300
            await self._redis.setex(
                self._cache_key(namespace, key),
                ttl,
                record.model_dump_json(),
            )
        except Exception:
            logger.warning(
                "memory.cache_write_failed",
                namespace=namespace,
                key=key,
                exc_info=True,
            )

    @staticmethod
    async def _emit_audit(
        audit_repo: AuditEventRepository,
        event_type: AuditEventType,
        actor: str,
        record: MemoryRecord | None,
        details: dict[str, Any],
    ) -> None:
        event = DBAuditEvent(
            event_type=event_type.value,
            actor=actor,
            resource_type="memory",
            resource_id=record.id if record else "N/A",
            action=details.get("action", event_type.value),
            details=details,
        )
        await audit_repo.append(event)

    # ------------------------------------------------------------------
    # Domain <-> DB mapping
    # ------------------------------------------------------------------

    @staticmethod
    def _domain_to_db(record: MemoryRecord) -> DBMemoryRecord:
        return DBMemoryRecord(
            id=record.id,
            namespace=record.namespace,
            key=record.key,
            value=record.value if isinstance(record.value, dict) else {"_v": record.value},
            memory_type=record.memory_type.value,
            source=record.source,
            actor=record.actor,
            confidence=record.confidence,
            access_policy=record.access_policy,
            lineage=record.lineage.model_dump(),
            ttl_seconds=record.ttl_seconds,
            expires_at=record.expires_at,
            deletion_status=record.deletion_status.value,
            deleted_at=record.deleted_at,
            tags=record.tags,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _db_to_domain(db_record: DBMemoryRecord) -> MemoryRecord:
        lineage_data = db_record.lineage or {}
        value = db_record.value
        if isinstance(value, dict) and list(value.keys()) == ["_v"]:
            value = value["_v"]

        return MemoryRecord(
            id=db_record.id,
            namespace=db_record.namespace,
            key=db_record.key,
            value=value,
            memory_type=db_record.memory_type,
            source=db_record.source or "",
            actor=db_record.actor or "",
            confidence=db_record.confidence or 1.0,
            access_policy=db_record.access_policy,
            lineage=MemoryLineage(**lineage_data),
            ttl_seconds=db_record.ttl_seconds,
            expires_at=db_record.expires_at,
            deletion_status=db_record.deletion_status,
            deleted_at=db_record.deleted_at,
            tags=db_record.tags or {},
            created_at=db_record.created_at,
            updated_at=db_record.updated_at,
        )
