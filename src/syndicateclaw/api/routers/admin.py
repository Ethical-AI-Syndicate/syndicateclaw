from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

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
    # TODO: wire pending_approvals, workflow_runs_active, memory_namespaces from DB aggregates.
    return DashboardStats(
        connectors_total=len(statuses),
        connectors_connected=sum(1 for item in statuses if item.connected),
        connectors_errors=sum(item.errors for item in statuses),
        pending_approvals=0,
        workflow_runs_active=0,
        memory_namespaces=0,
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
async def get_approval_queue(actor: str = Depends(get_current_actor)) -> list[ApprovalQueueItem]:
    _ = actor
    # TODO: query approval request queue from DB.
    return []


@router.post("/approvals/{approval_id}/decide")
async def decide_approval(
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
    # TODO: wire to ApprovalService decide/resolve API.
    return {"id": approval_id, "accepted": body.accepted, "queued": True}


@router.get("/workflows/runs", response_model=list[WorkflowRunSummary])
async def list_workflow_runs(
    limit: int = Query(default=50, ge=1, le=200),
    status: str | None = Query(default=None),
    actor: str = Depends(get_current_actor),
) -> list[WorkflowRunSummary]:
    _ = (limit, status, actor)
    # TODO: query workflow_runs with optional status filter.
    return []


@router.get("/workflows/runs/{run_id}", response_model=WorkflowRunSummary)
async def get_workflow_run(
    run_id: str, actor: str = Depends(get_current_actor)
) -> WorkflowRunSummary:
    _ = actor
    # TODO: load workflow run details by run_id.
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")


@router.get("/memory/namespaces", response_model=list[MemoryNamespaceSummary])
async def list_memory_namespaces(
    prefix: str | None = Query(default=None),
    actor: str = Depends(get_current_actor),
) -> list[MemoryNamespaceSummary]:
    _ = (prefix, actor)
    # TODO: query grouped memory namespace summary.
    return []


@router.delete("/memory/namespaces/{namespace}")
async def purge_namespace(
    namespace: str, actor: str = Depends(get_current_actor)
) -> dict[str, Any]:
    logger.warning("admin.memory_namespace_purge_requested", namespace=namespace, actor=actor)
    # TODO: wire to MemoryService namespace purge.
    return {"namespace": namespace, "purged": True}


@router.get("/audit", response_model=list[AuditEntry])
async def list_audit_events(
    limit: int = Query(default=100, ge=1, le=500),
    actor: str | None = Query(default=None),
    domain: str | None = Query(default=None),
    effect: str | None = Query(default=None),
    since: datetime | None = None,
    current_actor: str = Depends(get_current_actor),
) -> list[AuditEntry]:
    _ = (limit, actor, domain, effect, since, current_actor)
    # TODO: query decision/audit ledger events from storage.
    return []


@router.get("/providers", response_model=list[ProviderSummary])
async def list_provider_summaries(actor: str = Depends(get_current_actor)) -> list[ProviderSummary]:
    _ = actor
    # TODO: wire to ProviderService.list_providers() or provider loader snapshot.
    return []


@router.get("/api-keys", response_model=list[ApiKeySummary])
async def list_api_keys(actor: str = Depends(get_current_actor)) -> list[ApiKeySummary]:
    _ = actor
    # TODO: wire to ApiKeyService list endpoint.
    return []


@router.post("/api-keys", response_model=CreateApiKeyResponse)
async def create_api_key(
    body: CreateApiKeyRequest,
    actor: str = Depends(get_current_actor),
) -> CreateApiKeyResponse:
    _ = (body, actor)
    # TODO: wire to ApiKeyService create endpoint.
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="not implemented")


@router.delete("/api-keys/{key_id}")
async def revoke_api_key(key_id: str, actor: str = Depends(get_current_actor)) -> dict[str, Any]:
    logger.info("admin.api_key_revoke_requested", key_id=key_id, actor=actor)
    # TODO: wire to ApiKeyService revoke endpoint.
    return {"key_id": key_id, "revoked": True, "revoked_at": _utcnow().isoformat()}
