from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from syndicateclaw.api.dependencies import (
    get_current_actor,
    get_db_session,
    get_streaming_token_service,
)
from syndicateclaw.db.models import AuditEvent

router = APIRouter(prefix="/api/v1/runs", tags=["runs"])

DEP_CURRENT_ACTOR = Depends(get_current_actor)
DEP_STREAMING_TOKEN_SERVICE = Depends(get_streaming_token_service)
DEP_DB_SESSION = Depends(get_db_session)
Q_SINCE = Query(None)


@router.post("/{run_id}/streaming-token")
async def issue_streaming_token(
    run_id: str,
    actor: str = DEP_CURRENT_ACTOR,
    streaming_token_service: Any = DEP_STREAMING_TOKEN_SERVICE,
) -> dict[str, str]:
    token = await streaming_token_service.issue(run_id=run_id, actor=actor)
    return {
        "streaming_token": token.token,
        "expires_at": token.expires_at.isoformat(),
    }


@router.get("/{run_id}/events")
async def get_run_events(
    run_id: str,
    since: datetime | None = Q_SINCE,
    actor: str = DEP_CURRENT_ACTOR,
    db: AsyncSession = DEP_DB_SESSION,
) -> dict[str, Any]:
    _ = actor
    stmt = select(AuditEvent).where(
        AuditEvent.resource_type == "workflow_run",
        AuditEvent.resource_id == run_id,
    )
    if since is not None:
        stmt = stmt.where(AuditEvent.created_at > since)
    stmt = stmt.order_by(AuditEvent.created_at.asc())
    result = await db.execute(stmt)
    events = list(result.scalars().all())
    return {
        "events": [
            {
                "id": event.id,
                "event_type": event.event_type,
                "actor": event.actor,
                "resource_type": event.resource_type,
                "resource_id": event.resource_id,
                "action": event.action,
                "details": event.details,
                "created_at": event.created_at.isoformat(),
            }
            for event in events
        ],
        "count": len(events),
    }
