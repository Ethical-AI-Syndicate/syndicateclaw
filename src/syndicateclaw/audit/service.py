from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from syndicateclaw.audit.dead_letter import DeadLetterQueue
from syndicateclaw.db.models import AuditEvent as AuditEventRow
from syndicateclaw.db.repository import AuditEventRepository
from syndicateclaw.models import AuditEvent, AuditEventType

logger = structlog.get_logger(__name__)


async def _resolve_principal_id(session: AsyncSession, actor: str) -> str | None:
    """Look up principal ID from actor name. Returns None if not found."""
    from syndicateclaw.db.models import Principal

    try:
        result = await session.execute(select(Principal.id).where(Principal.name == actor).limit(1))
        row = result.first()
        return row[0] if row else None
    except Exception:
        return None


async def _resolve_resource_scope(
    session: AsyncSession,
    resource_type: str,
    resource_id: str,
) -> tuple[str | None, str | None]:
    """Look up owning scope from the resource. Returns (scope_type, scope_id)."""
    table_map = {
        "workflow": "workflow_definitions",
        "workflow_definition": "workflow_definitions",
        "workflow_run": "workflow_runs",
        "run": "workflow_runs",
        "memory": "memory_records",
        "memory_record": "memory_records",
        "approval": "approval_requests",
        "approval_request": "approval_requests",
        "policy": "policy_rules",
        "policy_rule": "policy_rules",
    }
    table = table_map.get(resource_type)
    if table is None:
        return None, None
    try:
        result = await session.execute(
            text(f"SELECT owning_scope_type, owning_scope_id FROM {table} WHERE id = :rid LIMIT 1"),
            {"rid": resource_id},
        )
        row = result.first()
        if row:
            return row[0], row[1]
    except Exception:
        pass
    return None, None


class AuditService:
    """Centralised, append-only audit logging service."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        signing_key: bytes | None = None,
        dead_letter_queue: DeadLetterQueue | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._signing_key = signing_key
        self._dead_letter_queue = dead_letter_queue

    async def emit(self, event: AuditEvent) -> AuditEvent:
        """Persist an audit event and log it. Signs event details if signing key is configured.

        Populates denormalized RBAC columns (actor_principal_id, resource_scope_type,
        resource_scope_id) from the database when not already set on the event.
        """
        details = event.details
        if self._signing_key:
            from syndicateclaw.security.signing import sign_record

            details = sign_record(details, self._signing_key)

        try:
            async with self._session_factory() as session, session.begin():
                principal_id = event.actor_principal_id
                if principal_id is None:
                    principal_id = await _resolve_principal_id(session, event.actor)

                scope_type = event.resource_scope_type
                scope_id = event.resource_scope_id
                if scope_type is None:
                    scope_type, scope_id = await _resolve_resource_scope(
                        session,
                        event.resource_type,
                        event.resource_id,
                    )

                repo = AuditEventRepository(session)
                row = AuditEventRow(
                    id=event.id,
                    event_type=event.event_type.value,
                    actor=event.actor,
                    actor_principal_id=principal_id,
                    resource_type=event.resource_type,
                    resource_id=event.resource_id,
                    action=event.action,
                    details=details,
                    parent_event_id=event.parent_event_id,
                    trace_id=event.trace_id,
                    span_id=event.span_id,
                    real_actor=event.real_actor,
                    impersonation_session_id=event.impersonation_session_id,
                    resource_scope_type=scope_type,
                    resource_scope_id=scope_id,
                )
                await repo.append(row)
                logger.info(
                    "audit_event",
                    event_type=event.event_type.value,
                    actor=event.actor,
                    resource_type=event.resource_type,
                    resource_id=event.resource_id,
                    action=event.action,
                )
        except Exception as exc:
            if self._dead_letter_queue is not None:
                await self._dead_letter_queue.enqueue(event, str(exc))
                logger.warning(
                    "audit.emit_failed_dead_letter",
                    event_id=event.id,
                    error=str(exc),
                )
                return event
            raise
        return event

    async def query(
        self,
        filters: dict[str, Any] | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[AuditEvent]:
        """Query audit events with optional filters."""
        async with self._session_factory() as session:
            repo = AuditEventRepository(session)
            rows = await repo.query(filters=filters or {}, offset=offset, limit=limit)
            return [AuditEvent.model_validate(r) for r in rows]

    async def get_run_timeline(self, run_id: str) -> list[AuditEvent]:
        """Get all events for a workflow run, sorted chronologically."""
        async with self._session_factory() as session:
            repo = AuditEventRepository(session)
            rows = await repo.get_by_resource("workflow_run", run_id)
            return [AuditEvent.model_validate(r) for r in rows]

    async def get_trace(self, trace_id: str) -> list[AuditEvent]:
        """Get all events sharing a trace_id."""
        async with self._session_factory() as session:
            repo = AuditEventRepository(session)
            rows = await repo.get_by_trace(trace_id)
            return [AuditEvent.model_validate(r) for r in rows]

    @classmethod
    def create_event(
        cls,
        event_type: AuditEventType,
        actor: str,
        resource_type: str,
        resource_id: str,
        action: str,
        details: dict[str, Any] | None = None,
        trace_id: str | None = None,
        span_id: str | None = None,
    ) -> AuditEvent:
        """Factory method for creating properly structured audit events."""
        return AuditEvent.new(
            event_type=event_type,
            actor=actor,
            resource_type=resource_type,
            resource_id=resource_id,
            action=action,
            details=details or {},
            trace_id=trace_id,
            span_id=span_id,
        )
