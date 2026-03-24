from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from pydantic import BaseModel, Field

from syndicateclaw.api.dependencies import (
    get_audit_service,
    get_current_actor,
    get_db_session,
    get_settings,
    get_workflow_engine,
)
from syndicateclaw.config import Settings
from syndicateclaw.models import (
    AuditEventType,
    EdgeDefinition,
    NodeDefinition,
    WorkflowRunStatus,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/workflows", tags=["workflows"])

# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class CreateWorkflowRequest(BaseModel):
    name: str
    version: str
    description: str = ""
    nodes: list[NodeDefinition] = Field(default_factory=list)
    edges: list[EdgeDefinition] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowResponse(BaseModel):
    model_config = {"from_attributes": True, "populate_by_name": True}

    id: str
    name: str
    version: str
    description: str | None = None
    nodes: Any = Field(default_factory=list)
    edges: Any = Field(default_factory=list)
    owner: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    created_at: datetime
    updated_at: datetime


class StartRunRequest(BaseModel):
    initial_state: dict[str, Any] = Field(default_factory=dict)
    tags: dict[str, str] = Field(default_factory=dict)


class WorkflowRunResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    workflow_id: str
    workflow_version: str
    status: WorkflowRunStatus
    state: dict[str, Any]
    parent_run_id: str | None = None
    initiated_by: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    tags: dict[str, str]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_orm_redacted(cls, obj: Any) -> WorkflowRunResponse:
        """Create response with sensitive fields redacted from state."""
        from syndicateclaw.security.redaction import redact_state

        instance = cls.model_validate(obj)
        instance.state = redact_state(
            instance.state,
            allowlist={"_run_id", "_started_at", "_completed_at", "_decision"},
        )
        return instance


class NodeExecutionResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    run_id: str
    node_id: str
    node_name: str
    status: str
    attempt: int
    input_state: dict[str, Any]
    output_state: dict[str, Any]
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    duration_ms: int | None = None
    created_at: datetime
    updated_at: datetime


class AuditTimelineEntry(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    event_type: str
    actor: str
    resource_type: str
    resource_id: str
    action: str
    details: dict[str, Any]
    created_at: datetime


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED)
async def create_workflow(
    body: CreateWorkflowRequest,
    actor: str = Depends(get_current_actor),
    db=Depends(get_db_session),
    audit=Depends(get_audit_service),
):
    from syndicateclaw.db.models import WorkflowDefinition as WFModel

    workflow = WFModel(
        name=body.name,
        version=body.version,
        description=body.description or "",
        nodes=[n.model_dump() for n in body.nodes],
        edges=[e.model_dump() for e in body.edges],
        owner=actor,
        metadata_=body.metadata,
        owning_scope_type="PLATFORM",
        owning_scope_id="platform",
    )
    db.add(workflow)
    await db.flush()
    logger.info("workflow.created", workflow_id=workflow.id, name=body.name)
    return workflow


@router.get("/", response_model=list[WorkflowResponse])
async def list_workflows(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    actor: str = Depends(get_current_actor),
    db=Depends(get_db_session),
):
    from sqlalchemy import select

    from syndicateclaw.db.models import WorkflowDefinition as WFModel

    stmt = select(WFModel).where(WFModel.owner == actor).offset(offset).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/runs", response_model=list[WorkflowRunResponse])
async def list_runs(
    status_filter: WorkflowRunStatus | None = Query(None, alias="status"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    actor: str = Depends(get_current_actor),
    db=Depends(get_db_session),
):
    from sqlalchemy import select

    from syndicateclaw.db.models import WorkflowRun as RunModel

    stmt = select(RunModel).where(RunModel.initiated_by == actor)
    if status_filter:
        stmt = stmt.where(RunModel.status == status_filter.value)
    stmt = stmt.order_by(RunModel.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    rows = list(result.scalars().all())
    return [WorkflowRunResponse.from_orm_redacted(r) for r in rows]


@router.get("/runs/{run_id}", response_model=WorkflowRunResponse)
async def get_run(
    run_id: str,
    actor: str = Depends(get_current_actor),
    db=Depends(get_db_session),
):
    from syndicateclaw.db.models import WorkflowRun as RunModel

    run = await db.get(RunModel, run_id)
    if run is None or (run.initiated_by and run.initiated_by != actor):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return WorkflowRunResponse.from_orm_redacted(run)


@router.post("/runs/{run_id}/pause", response_model=WorkflowRunResponse)
async def pause_run(
    run_id: str,
    actor: str = Depends(get_current_actor),
    db=Depends(get_db_session),
    engine=Depends(get_workflow_engine),
):
    from syndicateclaw.db.models import WorkflowRun as RunModel

    run = await db.get(RunModel, run_id)
    if run is None or (run.initiated_by and run.initiated_by != actor):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    if run.status != WorkflowRunStatus.RUNNING.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot pause run in status {run.status}",
        )
    run.status = WorkflowRunStatus.PAUSED.value
    await db.flush()
    logger.info("workflow.run_paused", run_id=run_id)
    return WorkflowRunResponse.from_orm_redacted(run)


@router.post("/runs/{run_id}/resume", response_model=WorkflowRunResponse)
async def resume_run(
    run_id: str,
    actor: str = Depends(get_current_actor),
    db=Depends(get_db_session),
    engine=Depends(get_workflow_engine),
):
    from syndicateclaw.db.models import WorkflowRun as RunModel

    run = await db.get(RunModel, run_id)
    if run is None or (run.initiated_by and run.initiated_by != actor):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    if run.status not in (WorkflowRunStatus.PAUSED.value, WorkflowRunStatus.WAITING_APPROVAL.value):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot resume run in status {run.status}",
        )
    run.status = WorkflowRunStatus.RUNNING.value
    await db.flush()
    logger.info("workflow.run_resumed", run_id=run_id)
    return WorkflowRunResponse.from_orm_redacted(run)


@router.post("/runs/{run_id}/cancel", response_model=WorkflowRunResponse)
async def cancel_run(
    run_id: str,
    actor: str = Depends(get_current_actor),
    db=Depends(get_db_session),
    engine=Depends(get_workflow_engine),
):
    from syndicateclaw.db.models import WorkflowRun as RunModel

    run = await db.get(RunModel, run_id)
    if run is None or (run.initiated_by and run.initiated_by != actor):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    terminal = {WorkflowRunStatus.COMPLETED.value, WorkflowRunStatus.CANCELLED.value}
    if run.status in terminal:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot cancel run in status {run.status}",
        )
    run.status = WorkflowRunStatus.CANCELLED.value
    await db.flush()
    logger.info("workflow.run_cancelled", run_id=run_id)
    return WorkflowRunResponse.from_orm_redacted(run)


@router.post("/runs/{run_id}/replay", response_model=WorkflowRunResponse)
async def replay_run(
    run_id: str,
    actor: str = Depends(get_current_actor),
    db=Depends(get_db_session),
    engine=Depends(get_workflow_engine),
):
    from syndicateclaw.db.models import WorkflowRun as RunModel

    run = await db.get(RunModel, run_id)
    if run is None or (run.initiated_by and run.initiated_by != actor):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    replayable = {
        WorkflowRunStatus.COMPLETED.value,
        WorkflowRunStatus.FAILED.value,
        WorkflowRunStatus.CANCELLED.value,
    }
    if run.status not in replayable:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot replay run in status {run.status}",
        )
    run.status = WorkflowRunStatus.PENDING.value
    run.error = None
    run.completed_at = None
    await db.flush()
    logger.info("workflow.run_replayed", run_id=run_id)
    return WorkflowRunResponse.from_orm_redacted(run)


@router.get("/runs/{run_id}/nodes", response_model=list[NodeExecutionResponse])
async def get_node_executions(
    run_id: str,
    actor: str = Depends(get_current_actor),
    db=Depends(get_db_session),
):
    from sqlalchemy import select

    from syndicateclaw.db.models import NodeExecution as NEModel

    stmt = (
        select(NEModel)
        .where(NEModel.run_id == run_id)
        .order_by(NEModel.created_at.asc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


# Parameterized /{workflow_id} routes must come AFTER all literal /runs/* routes,
# otherwise FastAPI matches "runs" as a workflow_id.

@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(
    workflow_id: str,
    actor: str = Depends(get_current_actor),
    db=Depends(get_db_session),
):
    from syndicateclaw.db.models import WorkflowDefinition as WFModel

    wf = await db.get(WFModel, workflow_id)
    if wf is None or (wf.owner and wf.owner != actor):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    return wf


@router.post(
    "/{workflow_id}/runs",
    response_model=WorkflowRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def start_run(
    workflow_id: str,
    body: StartRunRequest,
    request: Request,
    actor: str = Depends(get_current_actor),
    db=Depends(get_db_session),
    engine=Depends(get_workflow_engine),
):
    from syndicateclaw.db.models import WorkflowDefinition as WFModel

    wf = await db.get(WFModel, workflow_id)
    if wf is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")

    from syndicateclaw.db.models import WorkflowRun as RunModel

    active_statuses = {"PENDING", "RUNNING", "WAITING_APPROVAL"}
    active_count_stmt = select(func.count()).select_from(RunModel).where(
        RunModel.status.in_(active_statuses)
    )
    active_count = (await db.execute(active_count_stmt)).scalar() or 0

    settings: Settings = request.app.state.settings
    if active_count >= settings.max_concurrent_runs:
        logger.warning(
            "workflow.admission_denied",
            active_runs=active_count,
            max_concurrent=settings.max_concurrent_runs,
            actor=actor,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Concurrent run limit reached ({active_count}/{settings.max_concurrent_runs}). Retry later.",
        )

    run = RunModel(
        workflow_id=workflow_id,
        workflow_version=wf.version,
        initiated_by=actor,
        state=body.initial_state,
        tags=body.tags,
        owning_scope_type="PLATFORM",
        owning_scope_id="platform",
    )
    db.add(run)
    await db.flush()
    logger.info("workflow.run_started", run_id=run.id, workflow_id=workflow_id)
    return WorkflowRunResponse.from_orm_redacted(run)


@router.get("/runs/{run_id}/timeline", response_model=list[AuditTimelineEntry])
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
