from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import async_sessionmaker

from syndicateclaw.api.dependencies import get_approval_service, get_current_actor
from syndicateclaw.db.models import (
    NodeExecution,
    WorkflowDefinition,
    WorkflowRun,
)
from syndicateclaw.models import ApprovalRequest, ApprovalStatus, ToolRiskLevel

router = APIRouter(prefix="/api/v1/gate/approvals", tags=["gate-approvals"])

GATE_WORKFLOW_ID = "gate-sensitive-request-approval"
DEP_CURRENT_ACTOR = Depends(get_current_actor)
DEP_APPROVAL_SERVICE = Depends(get_approval_service)


class GateApprovalCreateRequest(BaseModel):
    correlation_id: str = Field(min_length=1)
    workspace_id: str | None = None
    api_key_id: str | None = None
    model: str = Field(min_length=1)
    provider: str | None = None
    provider_model: str | None = None
    path: str | None = None
    request_body_sha256: str = Field(min_length=64, max_length=64)
    action_description: str = Field(min_length=1)
    risk_level: ToolRiskLevel = ToolRiskLevel.HIGH
    assigned_to: list[str] = Field(min_length=1)
    context: dict[str, Any] = Field(default_factory=dict)
    expires_in_seconds: int = Field(default=300, ge=1, le=3600)


class GateApprovalResponse(BaseModel):
    id: str
    status: str
    correlation_id: str
    decision_reason: str | None = None


@router.post("", response_model=GateApprovalResponse, status_code=status.HTTP_201_CREATED)
async def create_gate_approval(
    body: GateApprovalCreateRequest,
    request: Request,
    actor: str = DEP_CURRENT_ACTOR,
    approval_service: Any = DEP_APPROVAL_SERVICE,
) -> GateApprovalResponse:
    session_factory = request.app.state.session_factory
    run_id, node_execution_id = await _ensure_gate_execution(session_factory, body, actor)

    context = {
        **body.context,
        "correlation_id": body.correlation_id,
        "workspace_id": body.workspace_id,
        "api_key_id": body.api_key_id,
        "model": body.model,
        "provider": body.provider,
        "provider_model": body.provider_model,
        "path": body.path,
        "request_body_sha256": body.request_body_sha256,
    }
    approval = ApprovalRequest(
        run_id=run_id,
        node_execution_id=node_execution_id,
        tool_name="syndicategate.provider_call",
        action_description=body.action_description,
        risk_level=body.risk_level,
        status=ApprovalStatus.PENDING,
        requested_by=actor,
        assigned_to=body.assigned_to,
        expires_at=datetime.now(UTC) + timedelta(seconds=body.expires_in_seconds),
        context=context,
    )
    created = await approval_service.request_approval(approval, actor, resolve_authority=False)
    return _to_response(created)


@router.get("/{approval_id}", response_model=GateApprovalResponse)
async def get_gate_approval(
    approval_id: str,
    request: Request,
    actor: str = DEP_CURRENT_ACTOR,
) -> GateApprovalResponse:
    from syndicateclaw.db.models import ApprovalRequest as ApprovalRequestRow

    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        approval = await session.get(ApprovalRequestRow, approval_id)
        if approval is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Approval request not found",
            )
        assigned = [str(x) for x in approval.assigned_to or []]
        if actor != approval.requested_by and actor not in assigned:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Approval request not found",
            )
        correlation_id = str((approval.context or {}).get("correlation_id") or approval.run_id)
        return GateApprovalResponse(
            id=approval.id,
            status=str(approval.status),
            correlation_id=correlation_id,
            decision_reason=approval.decision_reason,
        )


async def _ensure_gate_execution(
    session_factory: async_sessionmaker[Any],
    body: GateApprovalCreateRequest,
    actor: str,
) -> tuple[str, str]:
    run_id = body.correlation_id
    node_execution_id = f"{body.correlation_id}:approval"
    async with session_factory() as session, session.begin():
        workflow = await session.get(WorkflowDefinition, GATE_WORKFLOW_ID)
        if workflow is None:
            session.add(
                WorkflowDefinition(
                    id=GATE_WORKFLOW_ID,
                    name="Gate sensitive request approval",
                    version="1",
                    namespace="gate",
                    description="Synthetic workflow anchor for Gate approval enforcement",
                    nodes={},
                    edges={},
                    owner="system:gate",
                    owning_scope_type="PLATFORM",
                    owning_scope_id="platform",
                )
            )

        run = await session.get(WorkflowRun, run_id)
        if run is None:
            session.add(
                WorkflowRun(
                    id=run_id,
                    workflow_id=GATE_WORKFLOW_ID,
                    workflow_version="1",
                    status="WAITING_APPROVAL",
                    state={
                        "correlation_id": body.correlation_id,
                        "model": body.model,
                        "provider": body.provider,
                    },
                    initiated_by=actor,
                    owning_scope_type="PLATFORM",
                    owning_scope_id="platform",
                    started_at=datetime.now(UTC),
                    namespace="gate",
                )
            )

        node = await session.get(NodeExecution, node_execution_id)
        if node is None:
            session.add(
                NodeExecution(
                    id=node_execution_id,
                    run_id=run_id,
                    node_id="gate-approval",
                    node_name="Gate approval",
                    status="WAITING_APPROVAL",
                    input_state={
                        "correlation_id": body.correlation_id,
                        "request_body_sha256": body.request_body_sha256,
                    },
                )
            )
    return run_id, node_execution_id


def _to_response(approval: ApprovalRequest) -> GateApprovalResponse:
    status_value = (
        approval.status.value if hasattr(approval.status, "value") else str(approval.status)
    )
    return GateApprovalResponse(
        id=approval.id,
        status=status_value,
        correlation_id=str((approval.context or {}).get("correlation_id") or approval.run_id),
        decision_reason=approval.decision_reason,
    )
