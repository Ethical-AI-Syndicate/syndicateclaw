from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from syndicateclaw.api.dependencies import get_current_actor, get_db_session

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])

Q_EVENT_TYPE = Query(None)
Q_ACTOR_FILTER = Query(None, alias="actor")
Q_RESOURCE_TYPE = Query(None)
Q_START_TIME = Query(None)
Q_END_TIME = Query(None)
Q_OFFSET = Query(0, ge=0)
Q_LIMIT = Query(50, ge=1, le=500)
DEP_CURRENT_ACTOR = Depends(get_current_actor)
DEP_DB_SESSION = Depends(get_db_session)

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
    event_type: str | None = Q_EVENT_TYPE,
    actor_filter: str | None = Q_ACTOR_FILTER,
    resource_type: str | None = Q_RESOURCE_TYPE,
    start_time: datetime | None = Q_START_TIME,
    end_time: datetime | None = Q_END_TIME,
    offset: int = Q_OFFSET,
    limit: int = Q_LIMIT,
    actor: str = DEP_CURRENT_ACTOR,
    db: AsyncSession = DEP_DB_SESSION,
) -> list[Any]:
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
    actor: str = DEP_CURRENT_ACTOR,
    db: AsyncSession = DEP_DB_SESSION,
) -> list[Any]:
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
    actor: str = DEP_CURRENT_ACTOR,
    db: AsyncSession = DEP_DB_SESSION,
) -> list[Any]:
    from sqlalchemy import select

    from syndicateclaw.db.models import AuditEvent as AEModel

    stmt = (
        select(AEModel)
        .where(AEModel.resource_id == run_id)
        .order_by(AEModel.created_at.asc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())
