from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from ulid import ULID

from syndicateclaw.api.dependencies import get_current_actor, get_schedule_service
from syndicateclaw.services.schedule_service import (
    InvalidScheduleError,
    ScheduleConflictError,
    ScheduleNotFoundError,
    ScheduleService,
    validate_schedule_value,
)

router = APIRouter(prefix="/api/v1/schedules", tags=["schedules"])

DEP_CURRENT_ACTOR = Depends(get_current_actor)
DEP_SCHEDULE_SERVICE = Depends(get_schedule_service)
Q_NAMESPACE = Query(None)
Q_OFFSET = Query(0)
Q_LIMIT = Query(100)


class ScheduleCreateRequest(BaseModel):
    workflow_id: str
    workflow_version: int | None = None
    name: str
    description: str | None = None
    schedule_type: str = Field(..., pattern="^(CRON|INTERVAL|ONCE)$")
    schedule_value: str
    input_state: dict[str, Any] = Field(default_factory=dict)
    max_runs: int | None = Field(None, ge=1)
    namespace: str


class ScheduleUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    schedule_type: str | None = Field(None, pattern="^(CRON|INTERVAL|ONCE)$")
    schedule_value: str | None = None
    input_state: dict[str, Any] | None = None
    max_runs: int | None = Field(None, ge=1)
    status: str | None = Field(None, pattern="^(ACTIVE|PAUSED)$")


class ScheduleResponse(BaseModel):
    id: str
    workflow_id: str
    workflow_version: int | None
    name: str
    description: str | None
    schedule_type: str
    schedule_value: str
    input_state: dict[str, Any]
    actor: str
    namespace: str
    status: str
    next_run_at: datetime
    last_run_at: datetime | None
    max_runs: int | None
    run_count: int
    locked_by: str | None
    locked_until: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


def _schedule_response(schedule: Any) -> ScheduleResponse:
    return ScheduleResponse(
        id=schedule.id,
        workflow_id=schedule.workflow_id,
        workflow_version=schedule.workflow_version,
        name=schedule.name,
        description=schedule.description,
        schedule_type=schedule.schedule_type,
        schedule_value=schedule.schedule_value,
        input_state=schedule.input_state,
        actor=schedule.actor,
        namespace=schedule.namespace,
        status=schedule.status,
        next_run_at=schedule.next_run_at,
        last_run_at=schedule.last_run_at,
        max_runs=schedule.max_runs,
        run_count=schedule.run_count,
        locked_by=schedule.locked_by,
        locked_until=schedule.locked_until,
        created_at=schedule.created_at,
        updated_at=schedule.updated_at,
    )


@router.post("", response_model=ScheduleResponse, status_code=status.HTTP_201_CREATED)
async def create_schedule(
    request: ScheduleCreateRequest,
    actor: str = DEP_CURRENT_ACTOR,
    svc: ScheduleService = DEP_SCHEDULE_SERVICE,
) -> ScheduleResponse:
    try:
        schedule = await svc.create(
            ulid_factory=ULID,
            workflow_id=request.workflow_id,
            workflow_version=request.workflow_version,
            name=request.name,
            description=request.description,
            schedule_type=request.schedule_type,
            schedule_value=request.schedule_value,
            input_state=request.input_state,
            actor=actor,
            namespace=request.namespace,
            max_runs=request.max_runs,
        )
        return _schedule_response(schedule)
    except InvalidScheduleError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except ScheduleConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e


@router.get("", response_model=list[ScheduleResponse])
async def list_schedules(
    namespace: str = Q_NAMESPACE,
    offset: int = Q_OFFSET,
    limit: int = Q_LIMIT,
    svc: ScheduleService = DEP_SCHEDULE_SERVICE,
) -> list[ScheduleResponse]:
    schedules = await svc.list(namespace=namespace, offset=offset, limit=limit)
    return [_schedule_response(s) for s in schedules]


@router.get("/{schedule_id}", response_model=ScheduleResponse)
async def get_schedule(
    schedule_id: str,
    svc: ScheduleService = DEP_SCHEDULE_SERVICE,
) -> ScheduleResponse:
    try:
        schedule = await svc.get(schedule_id)
        return _schedule_response(schedule)
    except ScheduleNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.put("/{schedule_id}", response_model=ScheduleResponse)
async def update_schedule(
    schedule_id: str,
    request: ScheduleUpdateRequest,
    svc: ScheduleService = DEP_SCHEDULE_SERVICE,
) -> ScheduleResponse:
    try:
        schedule = await svc.update(
            schedule_id,
            name=request.name,
            description=request.description,
            schedule_type=request.schedule_type,
            schedule_value=request.schedule_value,
            input_state=request.input_state,
            max_runs=request.max_runs,
            status=request.status,
        )
        return _schedule_response(schedule)
    except InvalidScheduleError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except ScheduleNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.delete(
    "/{schedule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_schedule(
    schedule_id: str,
    svc: ScheduleService = DEP_SCHEDULE_SERVICE,
) -> Response:
    try:
        await svc.delete(schedule_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except ScheduleNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.post("/{schedule_id}/pause", response_model=ScheduleResponse)
async def pause_schedule(
    schedule_id: str,
    svc: ScheduleService = DEP_SCHEDULE_SERVICE,
) -> ScheduleResponse:
    try:
        schedule = await svc.pause(schedule_id)
        return _schedule_response(schedule)
    except ScheduleNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.post("/{schedule_id}/resume", response_model=ScheduleResponse)
async def resume_schedule(
    schedule_id: str,
    svc: ScheduleService = DEP_SCHEDULE_SERVICE,
) -> ScheduleResponse:
    try:
        schedule = await svc.resume(schedule_id)
        return _schedule_response(schedule)
    except InvalidScheduleError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except ScheduleNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.get("/{schedule_id}/preview-next-run")
async def preview_next_run(
    schedule_id: str,
    svc: ScheduleService = DEP_SCHEDULE_SERVICE,
) -> dict[str, Any]:
    try:
        schedule = await svc.get(schedule_id)
        next_run = validate_schedule_value(schedule.schedule_type, schedule.schedule_value)
        return {"next_run_at": next_run.isoformat()}
    except InvalidScheduleError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except ScheduleNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
