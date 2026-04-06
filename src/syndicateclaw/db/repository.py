from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, TypeVar, get_args

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from syndicateclaw.models import MemoryDeletionStatus

from .base import Base
from .models import (
    ApprovalRequest,
    AuditEvent,
    DeadLetterRecord,
    DecisionRecord,
    InputSnapshot,
    MemoryRecord,
    NodeExecution,
    PolicyDecision,
    PolicyRule,
    ToolExecution,
    WorkflowRun,
)

T = TypeVar("T", bound=Base)


class BaseRepository[T: Base]:
    """Generic async CRUD repository."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._model_cls: type[T] = self._resolve_model()

    def _resolve_model(self) -> type[T]:
        for base in getattr(type(self), "__orig_bases__", ()):
            args = get_args(base)
            if args and isinstance(args[0], type) and issubclass(args[0], Base):
                return args[0]  # type: ignore[return-value]
        raise TypeError("Could not resolve generic model type for repository")

    async def get(self, record_id: str) -> T | None:
        return await self.session.get(self._model_cls, record_id)

    async def create(self, entity: T) -> T:
        self.session.add(entity)
        await self.session.flush()
        await self.session.refresh(entity)
        return entity

    async def update(self, entity: T) -> T:
        merged = await self.session.merge(entity)
        await self.session.flush()
        await self.session.refresh(merged)
        return merged

    async def delete(self, record_id: str) -> None:
        stmt = delete(self._model_cls).where(self._model_cls.id == record_id)
        await self.session.execute(stmt)
        await self.session.flush()

    async def list(
        self,
        offset: int = 0,
        limit: int = 100,
        filters: dict[str, Any] | None = None,
    ) -> list[T]:
        stmt = select(self._model_cls)
        for col, val in (filters or {}).items():
            if hasattr(self._model_cls, col):
                stmt = stmt.where(getattr(self._model_cls, col) == val)
        stmt = stmt.offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class WorkflowRunRepository(BaseRepository[WorkflowRun]):
    async def get_active_runs(self) -> list[WorkflowRun]:
        stmt = select(WorkflowRun).where(WorkflowRun.status.in_(["pending", "running", "paused"]))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_runs_by_status(self, status: str) -> list[WorkflowRun]:
        stmt = select(WorkflowRun).where(WorkflowRun.status == status)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_status(self, record_id: str, status: str, error: str | None = None) -> None:
        values: dict[str, Any] = {
            "status": status,
            "updated_at": datetime.now(UTC),
        }
        if error is not None:
            values["error"] = error
        if status == "running":
            values["started_at"] = datetime.now(UTC)
        elif status in ("completed", "failed", "cancelled"):
            values["completed_at"] = datetime.now(UTC)
        stmt = update(WorkflowRun).where(WorkflowRun.id == record_id).values(**values)
        await self.session.execute(stmt)
        await self.session.flush()


class NodeExecutionRepository(BaseRepository[NodeExecution]):
    async def get_by_run(self, run_id: str) -> list[NodeExecution]:
        stmt = select(NodeExecution).where(NodeExecution.run_id == run_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_latest_for_node(self, run_id: str, node_id: str) -> NodeExecution | None:
        stmt = (
            select(NodeExecution)
            .where(NodeExecution.run_id == run_id, NodeExecution.node_id == node_id)
            .order_by(NodeExecution.attempt.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()


class ToolExecutionRepository(BaseRepository[ToolExecution]):
    async def get_by_run(self, run_id: str) -> list[ToolExecution]:
        stmt = select(ToolExecution).where(ToolExecution.run_id == run_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class MemoryRecordRepository(BaseRepository[MemoryRecord]):
    async def get_by_namespace(
        self, namespace: str, include_expired: bool = False
    ) -> list[MemoryRecord]:
        stmt = select(MemoryRecord).where(MemoryRecord.namespace == namespace)
        if not include_expired:
            now = datetime.now(UTC)
            stmt = stmt.where((MemoryRecord.expires_at.is_(None)) | (MemoryRecord.expires_at > now))
            stmt = stmt.where(MemoryRecord.deletion_status == MemoryDeletionStatus.ACTIVE.value)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_key(self, namespace: str, key: str) -> MemoryRecord | None:
        stmt = select(MemoryRecord).where(
            MemoryRecord.namespace == namespace,
            MemoryRecord.key == key,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def mark_for_deletion(self, record_id: str) -> None:
        now = datetime.now(UTC)
        stmt = (
            update(MemoryRecord)
            .where(MemoryRecord.id == record_id)
            .values(
                deletion_status=MemoryDeletionStatus.MARKED_FOR_DELETION.value,
                deleted_at=now,
                updated_at=now,
            )
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def purge_expired(self) -> int:
        now = datetime.now(UTC)
        stmt = (
            delete(MemoryRecord)
            .where(
                (MemoryRecord.deletion_status == MemoryDeletionStatus.MARKED_FOR_DELETION.value)
                | (MemoryRecord.expires_at.is_not(None) & (MemoryRecord.expires_at <= now))
            )
            .returning(MemoryRecord.id)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return len(result.all())


class PolicyRuleRepository(BaseRepository[PolicyRule]):
    async def get_enabled_by_resource_type(self, resource_type: str) -> list[PolicyRule]:
        stmt = (
            select(PolicyRule)
            .where(
                PolicyRule.resource_type == resource_type,
                PolicyRule.enabled.is_(True),
            )
            .order_by(PolicyRule.priority.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class PolicyDecisionRepository(BaseRepository[PolicyDecision]):
    pass


class ApprovalRequestRepository(BaseRepository[ApprovalRequest]):
    async def get_pending(self) -> list[ApprovalRequest]:
        stmt = select(ApprovalRequest).where(ApprovalRequest.status == "PENDING")
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_pending_by_assignee(self, assignee: str) -> list[ApprovalRequest]:
        stmt = select(ApprovalRequest).where(
            ApprovalRequest.status == "PENDING",
            ApprovalRequest.assigned_to.contains([assignee]),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_run(self, run_id: str) -> list[ApprovalRequest]:
        stmt = (
            select(ApprovalRequest)
            .where(ApprovalRequest.run_id == run_id)
            .order_by(ApprovalRequest.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_expired_pending(self, now: datetime) -> list[ApprovalRequest]:
        stmt = select(ApprovalRequest).where(
            ApprovalRequest.status == "PENDING",
            ApprovalRequest.expires_at <= now,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class AuditEventRepository:
    """Append-only repository — no update or delete operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def append(self, event: AuditEvent) -> AuditEvent:
        self.session.add(event)
        await self.session.flush()
        await self.session.refresh(event)
        return event

    async def query(
        self,
        filters: dict[str, Any] | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[AuditEvent]:
        stmt = select(AuditEvent)
        for col, val in (filters or {}).items():
            if hasattr(AuditEvent, col):
                stmt = stmt.where(getattr(AuditEvent, col) == val)
        stmt = stmt.order_by(AuditEvent.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_trace(self, trace_id: str) -> list[AuditEvent]:
        stmt = (
            select(AuditEvent)
            .where(AuditEvent.trace_id == trace_id)
            .order_by(AuditEvent.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_resource(self, resource_type: str, resource_id: str) -> list[AuditEvent]:
        stmt = (
            select(AuditEvent)
            .where(
                AuditEvent.resource_type == resource_type,
                AuditEvent.resource_id == resource_id,
            )
            .order_by(AuditEvent.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class DecisionRecordRepository:
    """Append-only repository for the decision ledger."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def append(self, record: DecisionRecord) -> DecisionRecord:
        self.session.add(record)
        await self.session.flush()
        await self.session.refresh(record)
        return record

    async def get_by_run(self, run_id: str) -> list[DecisionRecord]:
        stmt = (
            select(DecisionRecord)
            .where(DecisionRecord.run_id == run_id)
            .order_by(DecisionRecord.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_domain(
        self, domain: str, offset: int = 0, limit: int = 100
    ) -> list[DecisionRecord]:
        stmt = (
            select(DecisionRecord)
            .where(DecisionRecord.domain == domain)
            .order_by(DecisionRecord.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_trace(self, trace_id: str) -> list[DecisionRecord]:
        stmt = (
            select(DecisionRecord)
            .where(DecisionRecord.trace_id == trace_id)
            .order_by(DecisionRecord.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class InputSnapshotRepository(BaseRepository[InputSnapshot]):
    async def get_by_run(self, run_id: str) -> list[InputSnapshot]:
        stmt = (
            select(InputSnapshot)
            .where(InputSnapshot.run_id == run_id)
            .order_by(InputSnapshot.captured_at.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_node(self, run_id: str, node_execution_id: str) -> list[InputSnapshot]:
        stmt = (
            select(InputSnapshot)
            .where(
                InputSnapshot.run_id == run_id,
                InputSnapshot.node_execution_id == node_execution_id,
            )
            .order_by(InputSnapshot.captured_at.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_for_replay(self, run_id: str, source_identifier: str) -> InputSnapshot | None:
        stmt = (
            select(InputSnapshot)
            .where(
                InputSnapshot.run_id == run_id,
                InputSnapshot.source_identifier == source_identifier,
            )
            .order_by(InputSnapshot.captured_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()


class DeadLetterRecordRepository(BaseRepository[DeadLetterRecord]):
    async def get_pending(self) -> list[DeadLetterRecord]:
        stmt = (
            select(DeadLetterRecord)
            .where(DeadLetterRecord.status == "PENDING")
            .order_by(DeadLetterRecord.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_category(self, category: str) -> list[DeadLetterRecord]:
        stmt = (
            select(DeadLetterRecord)
            .where(DeadLetterRecord.error_category == category)
            .order_by(DeadLetterRecord.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def mark_resolved(self, record_id: str, resolved_by: str) -> None:
        stmt = (
            update(DeadLetterRecord)
            .where(DeadLetterRecord.id == record_id)
            .values(
                status="RETRIED",
                resolved_at=datetime.now(UTC),
                resolved_by=resolved_by,
                updated_at=datetime.now(UTC),
            )
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def mark_permanent_failure(self, record_id: str) -> None:
        stmt = (
            update(DeadLetterRecord)
            .where(DeadLetterRecord.id == record_id)
            .values(
                status="FAILED_PERMANENT",
                updated_at=datetime.now(UTC),
            )
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def increment_retry(self, record_id: str) -> None:
        stmt = (
            update(DeadLetterRecord)
            .where(DeadLetterRecord.id == record_id)
            .values(
                retry_count=DeadLetterRecord.retry_count + 1,
                last_retry_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        await self.session.execute(stmt)
        await self.session.flush()
