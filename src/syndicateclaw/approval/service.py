from __future__ import annotations

from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import async_sessionmaker

from syndicateclaw.audit.service import AuditService
from syndicateclaw.db.models import ApprovalRequest as ApprovalRequestRow
from syndicateclaw.db.repository import ApprovalRequestRepository
from syndicateclaw.approval.authority import ApprovalAuthorityResolver
from syndicateclaw.models import ApprovalRequest, ApprovalStatus, AuditEventType

logger = structlog.get_logger(__name__)

NotificationCallback = Callable[[ApprovalRequest], Coroutine[Any, Any, None]]


class ApprovalService:
    """Manages the lifecycle of human-in-the-loop approval requests."""

    def __init__(
        self,
        session_factory: async_sessionmaker,
        notification_callback: NotificationCallback | None = None,
        authority_resolver: ApprovalAuthorityResolver | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._notify = notification_callback
        self._audit = AuditService(session_factory)
        self._authority_resolver = authority_resolver

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def request_approval(
        self, request: ApprovalRequest, actor: str
    ) -> ApprovalRequest:
        """Create and persist a new approval request.

        If an authority resolver is configured, it overrides any client-supplied
        assigned_to list. The requester cannot choose their own approvers.
        """
        if not request.action_description:
            raise ValueError("action_description is required")

        request.status = ApprovalStatus.PENDING
        request.requested_by = actor

        if self._authority_resolver:
            resolved = await self._authority_resolver.resolve(
                tool_name=request.tool_name or "",
                risk_level=request.risk_level,
                requester=actor,
                context=request.context,
            )
            if request.assigned_to and request.assigned_to != resolved:
                logger.warning(
                    "approval.assigned_to_overridden",
                    original=request.assigned_to,
                    resolved=resolved,
                    requester=actor,
                )
            request.assigned_to = resolved
        elif not request.assigned_to:
            raise ValueError("assigned_to must contain at least one approver")

        async with self._session_factory() as session, session.begin():
            repo = ApprovalRequestRepository(session)
            row = ApprovalRequestRow(
                id=request.id,
                run_id=request.run_id,
                node_execution_id=request.node_execution_id,
                tool_name=request.tool_name or "",
                action_description=request.action_description,
                risk_level=request.risk_level.value,
                status=request.status.value,
                requested_by=request.requested_by,
                assigned_to=request.assigned_to,
                expires_at=request.expires_at,
                context=request.context,
            )
            await repo.create(row)

        await self._emit_audit(
            AuditEventType.APPROVAL_REQUESTED,
            actor,
            request,
            {"assigned_to": request.assigned_to},
        )

        if self._notify:
            try:
                await self._notify(request)
            except Exception:
                logger.exception("approval_notification_failed", request_id=request.id)

        return request

    async def approve(
        self, request_id: str, approver: str, reason: str
    ) -> ApprovalRequest:
        """Approve a pending request."""
        return await self._decide(request_id, approver, reason, ApprovalStatus.APPROVED)

    async def reject(
        self, request_id: str, approver: str, reason: str
    ) -> ApprovalRequest:
        """Reject a pending request."""
        return await self._decide(request_id, approver, reason, ApprovalStatus.REJECTED)

    async def expire_stale(self) -> int:
        """Expire all pending requests past their deadline. Returns the count expired."""
        now = datetime.now(UTC)
        count = 0
        async with self._session_factory() as session, session.begin():
            repo = ApprovalRequestRepository(session)
            stale = await repo.get_expired_pending(now)
            for row in stale:
                row.status = ApprovalStatus.EXPIRED.value
                row.updated_at = now
                await repo.update(row)
                count += 1

        for row in stale:
            req = ApprovalRequest.model_validate(row)
            await self._emit_audit(
                AuditEventType.APPROVAL_EXPIRED,
                "system",
                req,
                {"expired_at": now.isoformat()},
            )

        if count:
            logger.info("approvals_expired", count=count)
        return count

    async def get_pending(
        self, assignee: str | None = None
    ) -> list[ApprovalRequest]:
        """Return pending approval requests, optionally filtered by assignee."""
        async with self._session_factory() as session:
            repo = ApprovalRequestRepository(session)
            if assignee:
                rows = await repo.get_pending_by_assignee(assignee)
            else:
                rows = await repo.get_pending()
            return [ApprovalRequest.model_validate(r) for r in rows]

    async def get_by_run(self, run_id: str) -> list[ApprovalRequest]:
        """Return all approval requests for a workflow run."""
        async with self._session_factory() as session:
            repo = ApprovalRequestRepository(session)
            rows = await repo.get_by_run(run_id)
            return [ApprovalRequest.model_validate(r) for r in rows]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _decide(
        self,
        request_id: str,
        approver: str,
        reason: str,
        status: ApprovalStatus,
    ) -> ApprovalRequest:
        """Shared logic for approve/reject."""
        now = datetime.now(UTC)
        async with self._session_factory() as session, session.begin():
            repo = ApprovalRequestRepository(session)
            row = await repo.get(request_id)
            if row is None:
                raise ValueError(f"Approval request {request_id} not found")

            if row.status != ApprovalStatus.PENDING.value:
                raise ValueError(
                    f"Request {request_id} is {row.status}, not PENDING"
                )

            if approver == row.requested_by:
                raise PermissionError(
                    f"Self-approval prohibited: {approver} cannot approve their own request"
                )

            assigned = row.assigned_to or []
            if approver not in assigned:
                raise PermissionError(
                    f"{approver} is not in the assigned approvers list"
                )

            if row.expires_at and row.expires_at <= now:
                row.status = ApprovalStatus.EXPIRED.value
                row.updated_at = now
                await repo.update(row)
                raise ValueError(f"Request {request_id} has expired")

            row.status = status.value
            row.decided_by = approver
            row.decided_at = now
            row.decision_reason = reason
            row.updated_at = now
            row = await repo.update(row)
            result = ApprovalRequest.model_validate(row)

        event_type = (
            AuditEventType.APPROVAL_APPROVED
            if status == ApprovalStatus.APPROVED
            else AuditEventType.APPROVAL_REJECTED
        )
        await self._emit_audit(event_type, approver, result, {"reason": reason})
        return result

    async def _emit_audit(
        self,
        event_type: AuditEventType,
        actor: str,
        request: ApprovalRequest,
        details: dict[str, Any] | None = None,
    ) -> None:
        event = AuditService.create_event(
            event_type=event_type,
            actor=actor,
            resource_type="approval_request",
            resource_id=request.id,
            action=event_type.value,
            details={
                "run_id": request.run_id,
                "tool_name": request.tool_name,
                "status": request.status.value if isinstance(request.status, ApprovalStatus) else request.status,
                **(details or {}),
            },
        )
        await self._audit.emit(event)
