from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from syndicateclaw.api.dependencies import get_current_actor, get_db_session

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])

# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class AuditEventResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    event_type: str
    actor: str
    resource_type: str
    resource_id: str
    action: str
    details: dict[str, Any]
    parent_event_id: str | None = None
    trace_id: str | None = None
    span_id: str | None = None
    created_at: datetime


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/", response_model=list[AuditEventResponse])
async def query_audit_events(
    event_type: str | None = Query(None),
    actor_filter: str | None = Query(None, alias="actor"),
    resource_type: str | None = Query(None),
    start_time: datetime | None = Query(None),
    end_time: datetime | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    actor: str = Depends(get_current_actor),
    db=Depends(get_db_session),
):
    from sqlalchemy import select

    from syndicateclaw.db.models import AuditEvent as AEModel

    stmt = select(AEModel)
    if event_type:
        stmt = stmt.where(AEModel.event_type == event_type)
    if actor_filter:
        stmt = stmt.where(AEModel.actor == actor_filter)
    if resource_type:
        stmt = stmt.where(AEModel.resource_type == resource_type)
    if start_time:
        stmt = stmt.where(AEModel.created_at >= start_time)
    if end_time:
        stmt = stmt.where(AEModel.created_at <= end_time)
    stmt = stmt.order_by(AEModel.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/trace/{trace_id}", response_model=list[AuditEventResponse])
async def get_events_by_trace(
    trace_id: str,
    actor: str = Depends(get_current_actor),
    db=Depends(get_db_session),
):
    from sqlalchemy import select

    from syndicateclaw.db.models import AuditEvent as AEModel

    stmt = (
        select(AEModel)
        .where(AEModel.trace_id == trace_id)
        .order_by(AEModel.created_at.asc())
    )
    result = await db.execute(stmt)
    events = list(result.scalars().all())
    if not events:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No events found for trace {trace_id}",
        )
    return events


@router.get("/runs/{run_id}/timeline", response_model=list[AuditEventResponse])
async def get_run_timeline(
    run_id: str,
    actor: str = Depends(get_current_actor),
    db=Depends(get_db_session),
):
    from sqlalchemy import select

    from syndicateclaw.db.models import AuditEvent as AEModel

    stmt = (
        select(AEModel)
        .where(AEModel.resource_id == run_id)
        .order_by(AEModel.created_at.asc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())
