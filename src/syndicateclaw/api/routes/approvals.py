from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from syndicateclaw.api.dependencies import get_current_actor, get_db_session
from syndicateclaw.models import ApprovalStatus

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/approvals", tags=["approvals"])

DEP_CURRENT_ACTOR = Depends(get_current_actor)
DEP_DB_SESSION = Depends(get_db_session)
Q_ASSIGNEE = Query(None)
Q_STATUS_FILTER = Query(None, alias="status")
Q_OFFSET = Query(0, ge=0)
Q_LIMIT = Query(50, ge=1, le=200)

# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class ApprovalResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    run_id: str
    node_execution_id: str
    tool_name: str
    action_description: str | None = None
    risk_level: str
    status: str
    requested_by: str | None = None
    assigned_to: list[str] | Any = Field(default_factory=lambda: [])
    decided_by: str | None = None
    decided_at: datetime | None = None
    decision_reason: str | None = None
    expires_at: datetime | None = None
    context: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class ApprovalDecisionRequest(BaseModel):
    reason: str = ""


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/", response_model=list[ApprovalResponse])
async def list_pending_approvals(
    assignee: str | None = Q_ASSIGNEE,
    status_filter: str | None = Q_STATUS_FILTER,
    offset: int = Q_OFFSET,
    limit: int = Q_LIMIT,
    actor: str = DEP_CURRENT_ACTOR,
    db: AsyncSession = DEP_DB_SESSION,
) -> list[Any]:
    from sqlalchemy import select

    from syndicateclaw.db.models import ApprovalRequest as ARModel

    stmt = select(ARModel)
    if status_filter:
        stmt = stmt.where(ARModel.status == status_filter)
    else:
        stmt = stmt.where(ARModel.status == ApprovalStatus.PENDING.value)
    stmt = stmt.where((ARModel.assigned_to.contains([actor])) | (ARModel.requested_by == actor))
    if assignee:
        stmt = stmt.where(ARModel.assigned_to.contains([assignee]))
    stmt = stmt.order_by(ARModel.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/{approval_id}", response_model=ApprovalResponse)
async def get_approval(
    approval_id: str,
    actor: str = DEP_CURRENT_ACTOR,
    db: AsyncSession = DEP_DB_SESSION,
) -> Any:
    from syndicateclaw.db.models import ApprovalRequest as ARModel

    approval = await db.get(ARModel, approval_id)
    if approval is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Approval request not found"
        )
    at_raw: Any = approval.assigned_to
    assigned: list[str] = [str(x) for x in at_raw] if isinstance(at_raw, list) else []
    if actor != approval.requested_by and actor not in assigned:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Approval request not found"
        )
    return approval


@router.post("/{approval_id}/approve", response_model=ApprovalResponse)
async def approve_request(
    approval_id: str,
    body: ApprovalDecisionRequest,
    actor: str = DEP_CURRENT_ACTOR,
    db: AsyncSession = DEP_DB_SESSION,
) -> Any:
    from syndicateclaw.db.models import ApprovalRequest as ARModel

    approval = await db.get(ARModel, approval_id)
    if approval is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Approval request not found"
        )
    if approval.status != ApprovalStatus.PENDING.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Approval is already in status {approval.status}",
        )

    if approval.requested_by and actor == approval.requested_by:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Self-approval prohibited: requester cannot approve their own request",
        )

    at_raw: Any = approval.assigned_to
    assigned: list[str] = [str(x) for x in at_raw] if isinstance(at_raw, list) else []
    if assigned and actor not in assigned:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Actor '{actor}' is not in the assigned approvers list",
        )

    now = datetime.now(UTC)
    if approval.expires_at and approval.expires_at < now:
        approval.status = ApprovalStatus.EXPIRED.value
        await db.flush()
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Approval request has expired")

    approval.status = ApprovalStatus.APPROVED.value
    approval.decided_by = actor
    approval.decided_at = now
    approval.decision_reason = body.reason
    await db.flush()
    logger.info("approval.approved", approval_id=approval_id, actor=actor)
    return approval


@router.post("/{approval_id}/reject", response_model=ApprovalResponse)
async def reject_request(
    approval_id: str,
    body: ApprovalDecisionRequest,
    actor: str = DEP_CURRENT_ACTOR,
    db: AsyncSession = DEP_DB_SESSION,
) -> Any:
    from syndicateclaw.db.models import ApprovalRequest as ARModel

    approval = await db.get(ARModel, approval_id)
    if approval is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Approval request not found"
        )
    if approval.status != ApprovalStatus.PENDING.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Approval is already in status {approval.status}",
        )

    if approval.requested_by and actor == approval.requested_by:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Self-rejection prohibited: requester cannot reject their own request",
        )

    at_raw: Any = approval.assigned_to
    assigned: list[str] = [str(x) for x in at_raw] if isinstance(at_raw, list) else []
    if assigned and actor not in assigned:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Actor '{actor}' is not in the assigned approvers list",
        )

    approval.status = ApprovalStatus.REJECTED.value
    approval.decided_by = actor
    approval.decided_at = datetime.now(UTC)
    approval.decision_reason = body.reason
    await db.flush()
    logger.info("approval.rejected", approval_id=approval_id, actor=actor)
    return approval


@router.get("/runs/{run_id}", response_model=list[ApprovalResponse])
async def get_approvals_for_run(
    run_id: str,
    actor: str = DEP_CURRENT_ACTOR,
    db: AsyncSession = DEP_DB_SESSION,
) -> list[Any]:
    from sqlalchemy import select

    from syndicateclaw.db.models import ApprovalRequest as ARModel

    stmt = (
        select(ARModel)
        .where(ARModel.run_id == run_id)
        .where((ARModel.assigned_to.contains([actor])) | (ARModel.requested_by == actor))
        .order_by(ARModel.created_at.asc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())
