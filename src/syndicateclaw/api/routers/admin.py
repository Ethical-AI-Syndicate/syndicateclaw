from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from syndicateclaw.api.dependencies import get_current_actor

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


def _utcnow() -> datetime:
    return datetime.now(UTC)


class DashboardStats(BaseModel):
    connectors_total: int = 0
    connectors_connected: int = 0
    connectors_errors: int = 0
    pending_approvals: int = 0
    workflow_runs_active: int = 0
    memory_namespaces: int = 0


class ConnectorStatusResponse(BaseModel):
    platform: str
    connected: bool
    webhook_url: str | None = None
    last_event_at: datetime | None = None
    events_received: int = 0
    errors: int = 0
    detail: str | None = None


class ApprovalQueueItem(BaseModel):
    id: str
    actor: str
    action: str
    reason: str | None = None
    created_at: datetime
    status: str = "PENDING"


class ApprovalDecisionRequest(BaseModel):
    accepted: bool = Field(default=True)
    reason: str | None = Field(default=None)


class WorkflowRunSummary(BaseModel):
    run_id: str
    status: str
    workflow_name: str
    initiated_by: str
    created_at: datetime


class MemoryNamespaceSummary(BaseModel):
    namespace: str
    prefix: str
    records: int = 0
    last_updated_at: datetime | None = None


class AuditEntry(BaseModel):
    id: str
    actor: str
    domain: str
    effect: str
    action: str
    at: datetime
    detail: dict[str, Any] = Field(default_factory=dict)


class ProviderSummary(BaseModel):
    provider_id: str
    name: str
    enabled: bool = True
    model_count: int = 0
    status: str = "unknown"


class ApiKeySummary(BaseModel):
    key_id: str
    name: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None = None
    revoked: bool = False


class CreateApiKeyRequest(BaseModel):
    name: str
    expires_at: datetime | None = None


class CreateApiKeyResponse(BaseModel):
    key_id: str
    key: str
    created_at: datetime


@router.get("/dashboard", response_model=DashboardStats)
async def get_dashboard_stats(
    request: Request,
    actor: str = Depends(get_current_actor),
) -> DashboardStats:
    _ = actor
    registry = getattr(request.app.state, "connector_registry", None)
    statuses = registry.statuses() if registry is not None else []
    approval_service = getattr(request.app.state, "approval_service", None)
    session_factory = getattr(request.app.state, "session_factory", None)

    pending_approvals = 0
    workflow_runs_active = 0
    memory_namespaces = 0

    if approval_service is not None:
        pending_requests = await approval_service.get_pending()
        pending_approvals = len(pending_requests)

    if session_factory is not None:
        from syndicateclaw.db.models import MemoryRecord, WorkflowRun

        async with session_factory() as session:
            active_runs_stmt = (
                select(func.count())
                .select_from(WorkflowRun)
                .where(WorkflowRun.status.in_(["PENDING", "RUNNING", "PAUSED"]))
            )
            workflow_runs_active = (await session.execute(active_runs_stmt)).scalar() or 0

            namespaces_stmt = select(func.count(func.distinct(MemoryRecord.namespace))).where(
                MemoryRecord.deletion_status == "ACTIVE"
            )
            memory_namespaces = (await session.execute(namespaces_stmt)).scalar() or 0

    return DashboardStats(
        connectors_total=len(statuses),
        connectors_connected=sum(1 for item in statuses if item.connected),
        connectors_errors=sum(item.errors for item in statuses),
        pending_approvals=pending_approvals,
        workflow_runs_active=workflow_runs_active,
        memory_namespaces=memory_namespaces,
    )


@router.get("/connectors", response_model=list[ConnectorStatusResponse])
async def get_connector_statuses(
    request: Request,
    actor: str = Depends(get_current_actor),
) -> list[ConnectorStatusResponse]:
    _ = actor
    registry = getattr(request.app.state, "connector_registry", None)
    if registry is None:
        return []

    statuses = registry.statuses()
    return [
        ConnectorStatusResponse(
            platform=status_item.platform.value,
            connected=status_item.connected,
            webhook_url=status_item.webhook_url,
            last_event_at=status_item.last_event_at,
            events_received=status_item.events_received,
            errors=status_item.errors,
            detail=status_item.detail,
        )
        for status_item in statuses
    ]


@router.get("/approvals", response_model=list[ApprovalQueueItem])
async def get_approval_queue(
    request: Request,
    actor: str = Depends(get_current_actor),
) -> list[ApprovalQueueItem]:
    approval_service = getattr(request.app.state, "approval_service", None)
    if approval_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="approval service unavailable"
        )

    pending_requests = await approval_service.get_pending(actor)
    return [
        ApprovalQueueItem(
            id=item.id,
            actor=item.requested_by or "unknown",
            action=item.action_description or item.tool_name,
            reason=(item.context or {}).get("reason"),
            created_at=item.created_at,
            status=(item.status.value if hasattr(item.status, "value") else str(item.status)),
        )
        for item in pending_requests
    ]


@router.post("/approvals/{approval_id}/decide")
async def decide_approval(
    request: Request,
    approval_id: str,
    body: ApprovalDecisionRequest,
    actor: str = Depends(get_current_actor),
) -> dict[str, Any]:
    logger.info(
        "admin.approval_decide_requested",
        approval_id=approval_id,
        accepted=body.accepted,
        actor=actor,
    )
    approval_service = getattr(request.app.state, "approval_service", None)
    if approval_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="approval service unavailable"
        )

    reason = body.reason or (
        "approved via admin API" if body.accepted else "rejected via admin API"
    )

    try:
        result = (
            await approval_service.approve(approval_id, actor, reason)
            if body.accepted
            else await approval_service.reject(approval_id, actor, reason)
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        detail = str(exc)
        status_code = (
            status.HTTP_404_NOT_FOUND if "not found" in detail.lower() else status.HTTP_409_CONFLICT
        )
        raise HTTPException(status_code=status_code, detail=detail) from exc

    return {
        "id": result.id,
        "accepted": body.accepted,
        "status": result.status.value if hasattr(result.status, "value") else str(result.status),
        "decided_by": result.decided_by,
        "decided_at": result.decided_at.isoformat() if result.decided_at else None,
    }


@router.get("/workflows/runs", response_model=list[WorkflowRunSummary])
async def list_workflow_runs(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    status_filter: str | None = Query(default=None, alias="status"),
    actor: str = Depends(get_current_actor),
) -> list[WorkflowRunSummary]:
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="database unavailable"
        )

    from syndicateclaw.db.models import WorkflowDefinition, WorkflowRun

    async with session_factory() as session:
        stmt = (
            select(WorkflowRun, WorkflowDefinition.name)
            .join(WorkflowDefinition, WorkflowDefinition.id == WorkflowRun.workflow_id)
            .order_by(WorkflowRun.created_at.desc())
            .limit(limit)
        )
        if status_filter:
            stmt = stmt.where(WorkflowRun.status == status_filter)

        result = await session.execute(stmt)
        rows = result.all()

    return [
        WorkflowRunSummary(
            run_id=run.id,
            status=run.status,
            workflow_name=workflow_name,
            initiated_by=run.initiated_by or "unknown",
            created_at=run.created_at,
        )
        for run, workflow_name in rows
    ]


@router.get("/workflows/runs/{run_id}", response_model=WorkflowRunSummary)
async def get_workflow_run(
    request: Request,
    run_id: str,
    actor: str = Depends(get_current_actor),
) -> WorkflowRunSummary:
    _ = actor
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="database unavailable"
        )

    from syndicateclaw.db.models import WorkflowDefinition, WorkflowRun

    async with session_factory() as session:
        stmt = (
            select(WorkflowRun, WorkflowDefinition.name)
            .join(WorkflowDefinition, WorkflowDefinition.id == WorkflowRun.workflow_id)
            .where(WorkflowRun.id == run_id)
        )
        row = (await session.execute(stmt)).first()

    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")

    run, workflow_name = row
    return WorkflowRunSummary(
        run_id=run.id,
        status=run.status,
        workflow_name=workflow_name,
        initiated_by=run.initiated_by or "unknown",
        created_at=run.created_at,
    )


@router.get("/memory/namespaces", response_model=list[MemoryNamespaceSummary])
async def list_memory_namespaces(
    request: Request,
    prefix: str | None = Query(default=None),
    actor: str = Depends(get_current_actor),
) -> list[MemoryNamespaceSummary]:
    _ = actor
    memory_service = getattr(request.app.state, "memory_service", None)
    if memory_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="memory service unavailable",
        )

    rows = await memory_service.list_namespaces(prefix)
    return [MemoryNamespaceSummary(**row) for row in rows]


@router.delete("/memory/namespaces/{namespace}")
async def purge_namespace(
    request: Request,
    namespace: str,
    actor: str = Depends(get_current_actor),
) -> dict[str, Any]:
    logger.warning("admin.memory_namespace_purge_requested", namespace=namespace, actor=actor)
    memory_service = getattr(request.app.state, "memory_service", None)
    if memory_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="memory service unavailable",
        )

    purged_count = await memory_service.purge_namespace(namespace, actor)
    return {
        "namespace": namespace,
        "purged": True,
        "purged_count": purged_count,
        "purged_at": _utcnow().isoformat(),
    }


@router.get("/audit", response_model=list[AuditEntry])
async def list_audit_events(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    actor: str | None = Query(default=None),
    domain: str | None = Query(default=None),
    effect: str | None = Query(default=None),
    since: datetime | None = None,
    current_actor: str = Depends(get_current_actor),
) -> list[AuditEntry]:
    _ = current_actor
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database unavailable",
        )

    from syndicateclaw.db.models import AuditEvent as DBAuditEvent
    from syndicateclaw.db.models import DecisionRecord as DBDecisionRecord

    async with session_factory() as session:
        audit_stmt = select(DBAuditEvent)
        if actor:
            audit_stmt = audit_stmt.where(DBAuditEvent.actor == actor)
        if domain:
            audit_stmt = audit_stmt.where(DBAuditEvent.resource_type == domain)
        if effect:
            audit_stmt = audit_stmt.where(
                or_(DBAuditEvent.event_type == effect, DBAuditEvent.action == effect)
            )
        if since:
            audit_stmt = audit_stmt.where(DBAuditEvent.created_at >= since)
        audit_stmt = audit_stmt.order_by(DBAuditEvent.created_at.desc()).limit(limit)
        audit_rows = list((await session.execute(audit_stmt)).scalars().all())

        decision_stmt = select(DBDecisionRecord)
        if actor:
            decision_stmt = decision_stmt.where(DBDecisionRecord.actor == actor)
        if domain:
            decision_stmt = decision_stmt.where(DBDecisionRecord.domain == domain)
        if effect:
            decision_stmt = decision_stmt.where(DBDecisionRecord.effect == effect)
        if since:
            decision_stmt = decision_stmt.where(DBDecisionRecord.created_at >= since)
        decision_stmt = decision_stmt.order_by(DBDecisionRecord.created_at.desc()).limit(limit)
        decision_rows = list((await session.execute(decision_stmt)).scalars().all())

    combined: list[AuditEntry] = [
        AuditEntry(
            id=row.id,
            actor=row.actor,
            domain=row.resource_type,
            effect=row.event_type,
            action=row.action,
            at=row.created_at,
            detail=row.details or {},
        )
        for row in audit_rows
    ]
    combined.extend(
        AuditEntry(
            id=row.id,
            actor=row.actor,
            domain=row.domain,
            effect=row.effect,
            action=row.decision_type,
            at=row.created_at,
            detail={
                "justification": row.justification,
                "confidence": row.confidence,
                "inputs": row.inputs,
                "rules_evaluated": row.rules_evaluated,
                "matched_rule": row.matched_rule,
                "side_effects": row.side_effects,
                "trace_id": row.trace_id,
                "run_id": row.run_id,
                "node_execution_id": row.node_execution_id,
            },
        )
        for row in decision_rows
    )
    combined.sort(key=lambda item: item.at, reverse=True)
    return combined[:limit]


@router.get("/providers", response_model=list[ProviderSummary])
async def list_provider_summaries(
    request: Request,
    actor: str = Depends(get_current_actor),
) -> list[ProviderSummary]:
    _ = actor
    loader = getattr(request.app.state, "provider_config_loader", None)
    registry = getattr(request.app.state, "provider_registry", None)
    catalog = getattr(request.app.state, "inference_catalog", None)
    if loader is None or registry is None or catalog is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="provider services unavailable",
        )

    try:
        cfg, _ver = loader.current()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="provider config not loaded",
        ) from exc

    summaries: list[ProviderSummary] = []
    for provider in cfg.providers:
        model_ids: set[str] = set()
        for capability in provider.capabilities:
            model_ids.update(catalog.models_for_capability_and_provider(capability, provider.id))

        runtime_disabled = registry.is_runtime_disabled(provider.id)
        enabled = provider.enabled and not runtime_disabled
        provider_status = "disabled" if not enabled else registry.health_status(provider.id).value
        summaries.append(
            ProviderSummary(
                provider_id=provider.id,
                name=provider.name,
                enabled=enabled,
                model_count=len(model_ids),
                status=provider_status,
            )
        )

    return summaries


@router.get("/api-keys", response_model=list[ApiKeySummary])
async def list_api_keys(
    request: Request,
    actor: str = Depends(get_current_actor),
) -> list[ApiKeySummary]:
    _ = actor
    api_key_service = getattr(request.app.state, "api_key_service", None)
    if api_key_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="api key service unavailable",
        )

    keys = await api_key_service.list_keys()
    return [
        ApiKeySummary(
            key_id=item["id"],
            name=item.get("description") or item["id"],
            prefix=item["key_prefix"],
            created_at=item["created_at"],
            last_used_at=item.get("last_used_at"),
            revoked=item["revoked"],
        )
        for item in keys
    ]


@router.post("/api-keys", response_model=CreateApiKeyResponse)
async def create_api_key(
    request: Request,
    body: CreateApiKeyRequest,
    actor: str = Depends(get_current_actor),
) -> CreateApiKeyResponse:
    api_key_service = getattr(request.app.state, "api_key_service", None)
    if api_key_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="api key service unavailable",
        )

    try:
        key_id, raw_key = await api_key_service.create_api_key(
            actor=actor,
            description=body.name,
            expires_at=body.expires_at,
            created_by=actor,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    return CreateApiKeyResponse(
        key_id=key_id,
        key=raw_key,
        created_at=_utcnow(),
    )


@router.delete("/api-keys/{key_id}")
async def revoke_api_key(
    request: Request,
    key_id: str,
    actor: str = Depends(get_current_actor),
) -> dict[str, Any]:
    logger.info("admin.api_key_revoke_requested", key_id=key_id, actor=actor)
    api_key_service = getattr(request.app.state, "api_key_service", None)
    if api_key_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="api key service unavailable",
        )

    revoked = await api_key_service.revoke_key(key_id, actor)
    if not revoked:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="api key not found")

    return {"key_id": key_id, "revoked": True, "revoked_at": _utcnow().isoformat()}
