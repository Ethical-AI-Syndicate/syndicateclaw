from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from syndicateclaw.api.dependencies import get_current_actor, get_versioning_service
from syndicateclaw.services.versioning_service import VersionNotFoundError

router = APIRouter(tags=["workflow_versions"])

DEP_CURRENT_ACTOR = Depends(get_current_actor)
DEP_VERSIONING_SERVICE = Depends(get_versioning_service)
Q_OFFSET = Query(0, ge=0)
Q_LIMIT = Query(100, ge=1, le=200)
Q_FROM = Query(..., alias="from")
Q_TO = Query(..., alias="to")


class WorkflowVersionResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    workflow_id: str
    version: int
    definition: dict[str, Any]
    changed_by: str
    changed_at: datetime
    comment: str | None = None
    created_at: datetime
    updated_at: datetime


class RollbackRequest(BaseModel):
    version: int
    comment: str | None = None


@router.get(
    "/api/v1/workflows/{workflow_id}/versions",
    response_model=list[WorkflowVersionResponse],
)
async def list_workflow_versions(
    workflow_id: str,
    offset: int = Q_OFFSET,
    limit: int = Q_LIMIT,
    actor: str = DEP_CURRENT_ACTOR,
    versioning_service: Any = DEP_VERSIONING_SERVICE,
) -> list[Any]:
    _ = actor
    rows = await versioning_service.list_versions(workflow_id, offset=offset, limit=limit)
    return list(rows)


@router.get(
    "/api/v1/workflows/{workflow_id}/versions/{version}",
    response_model=WorkflowVersionResponse,
)
async def get_workflow_version(
    workflow_id: str,
    version: int,
    actor: str = DEP_CURRENT_ACTOR,
    versioning_service: Any = DEP_VERSIONING_SERVICE,
) -> Any:
    _ = actor
    try:
        return await versioning_service.get_version(workflow_id, version)
    except VersionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/api/v1/workflows/{workflow_id}/rollback")
async def rollback_workflow_version(
    workflow_id: str,
    body: RollbackRequest,
    actor: str = DEP_CURRENT_ACTOR,
    versioning_service: Any = DEP_VERSIONING_SERVICE,
) -> dict[str, Any]:
    try:
        created = await versioning_service.rollback(
            workflow_id,
            body.version,
            actor,
            body.comment,
        )
        return {"workflow_id": workflow_id, "version": created}
    except VersionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/api/v1/workflows/{workflow_id}/diff")
async def diff_workflow_versions(
    workflow_id: str,
    from_version: int = Q_FROM,
    to_version: int = Q_TO,
    actor: str = DEP_CURRENT_ACTOR,
    versioning_service: Any = DEP_VERSIONING_SERVICE,
) -> dict[str, Any]:
    _ = actor
    try:
        result: dict[str, Any] = await versioning_service.diff(
            workflow_id,
            from_version,
            to_version,
        )
        return result
    except VersionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
