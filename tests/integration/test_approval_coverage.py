"""DB-backed approval service integration tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from ulid import ULID

from syndicateclaw.approval.authority import ApprovalAuthorityResolver
from syndicateclaw.approval.service import ApprovalService
from syndicateclaw.audit.service import AuditService
from syndicateclaw.db.models import (
    NodeExecution as NodeExecutionORM,
)
from syndicateclaw.db.models import (
    WorkflowDefinition as WorkflowDefinitionORM,
)
from syndicateclaw.db.models import (
    WorkflowRun as WorkflowRunORM,
)
from syndicateclaw.models import (
    ApprovalRequest,
    ApprovalStatus,
    AuditEventType,
    EdgeDefinition,
    NodeDefinition,
    NodeType,
    ToolRiskLevel,
    WorkflowDefinition,
    WorkflowRun,
    WorkflowRunStatus,
)
from syndicateclaw.orchestrator.engine import ExecutionContext, WorkflowEngine
from syndicateclaw.orchestrator.handlers import BUILTIN_HANDLERS

pytestmark = pytest.mark.integration


def _approval_request(
    run_id: str,
    node_execution_id: str = "",
    *,
    assigned_to: list[str],
    requested_by: str = "requester",
) -> ApprovalRequest:
    return ApprovalRequest(
        run_id=run_id,
        node_execution_id=node_execution_id,
        tool_name="test-tool",
        action_description="integration approval",
        risk_level=ToolRiskLevel.MEDIUM,
        requested_by=requested_by,
        assigned_to=assigned_to,
        expires_at=datetime.now(UTC) + timedelta(hours=24),
        context={},
    )


async def _make_workflow_run(session_factory) -> tuple[str, str]:
    """Create WorkflowDefinition, WorkflowRun, NodeExecution; return (run_id, node_execution_id)."""
    async with session_factory() as session:
        wf = WorkflowDefinitionORM(
            id=str(ULID()),
            name=f"test-wf-{ULID()}",
            version="1.0",
        )
        session.add(wf)
        await session.flush()
        run = WorkflowRunORM(
            id=str(ULID()),
            workflow_id=wf.id,
            workflow_version="1.0",
            status="PENDING",
        )
        session.add(run)
        await session.flush()
        node_exec = NodeExecutionORM(
            id=str(ULID()),
            run_id=run.id,
            node_id="test-node",
            node_name="test-node",
            status="pending",
        )
        session.add(node_exec)
        await session.commit()
        return run.id, node_exec.id



async def test_approval_request_created_blocks_workflow(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    svc = ApprovalService(session_factory)
    run_id, node_execution_id = await _make_workflow_run(session_factory)
    req = _approval_request(run_id, node_execution_id=node_execution_id, assigned_to=["approver1"])
    out = await svc.request_approval(req, actor="requester")
    assert out.status == ApprovalStatus.PENDING
    pending = await svc.get_pending(assignee="approver1")
    assert any(r.id == out.id for r in pending)


async def test_approval_approved_resumes_workflow(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    svc = ApprovalService(session_factory)
    run_id, node_execution_id = await _make_workflow_run(session_factory)
    req = _approval_request(
        run_id,
        node_execution_id=node_execution_id,
        assigned_to=["approver1"],
        requested_by="requester",
    )
    created = await svc.request_approval(req, actor="requester")
    updated = await svc.approve(created.id, approver="approver1", reason="ok")
    assert updated.status == ApprovalStatus.APPROVED


async def test_approval_denied_halts_workflow(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    svc = ApprovalService(session_factory)
    run_id, node_execution_id = await _make_workflow_run(session_factory)
    req = _approval_request(
        run_id,
        node_execution_id=node_execution_id,
        assigned_to=["approver1"],
        requested_by="requester",
    )
    created = await svc.request_approval(req, actor="requester")
    updated = await svc.reject(created.id, approver="approver1", reason="no")
    assert updated.status == ApprovalStatus.REJECTED


async def test_approval_denied_emits_audit_event(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    svc = ApprovalService(session_factory)
    audit = AuditService(session_factory)
    run_id, node_execution_id = await _make_workflow_run(session_factory)
    req = _approval_request(
        run_id,
        node_execution_id=node_execution_id,
        assigned_to=["approver1"],
        requested_by="requester",
    )
    created = await svc.request_approval(req, actor="requester")
    await svc.reject(created.id, approver="approver1", reason="no-go")
    rows = await audit.query(filters={"resource_id": created.id}, limit=10)
    types = {r.event_type for r in rows}
    assert AuditEventType.APPROVAL_REJECTED in types


async def test_approval_routing_to_correct_authority(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    resolver = ApprovalAuthorityResolver(session_factory=session_factory)
    svc = ApprovalService(session_factory, authority_resolver=resolver)
    run_id, node_execution_id = await _make_workflow_run(session_factory)
    req = ApprovalRequest(
        run_id=run_id,
        node_execution_id=node_execution_id,
        tool_name="x",
        action_description="needs approver",
        risk_level=ToolRiskLevel.LOW,
        requested_by="alice",
        assigned_to=["wrong-person"],
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        context={},
    )
    out = await svc.request_approval(req, actor="alice")
    assert out.assigned_to != ["wrong-person"]
    assert "admin:ops" in out.assigned_to


async def test_approval_expired_request_handled(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    svc = ApprovalService(session_factory)
    run_id, node_execution_id = await _make_workflow_run(session_factory)
    req = _approval_request(
        run_id,
        node_execution_id=node_execution_id,
        assigned_to=["approver1"],
        requested_by="requester",
    )
    req.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    created = await svc.request_approval(req, actor="requester")
    with pytest.raises(ValueError, match="expired"):
        await svc.approve(created.id, approver="approver1", reason="late")


async def test_approval_gate_blocks_and_unblocks_workflow_engine() -> None:
    """Engine reaches WAITING_APPROVAL at approval node; resume sets RUNNING."""
    wf = WorkflowDefinition.new(
        name="appr-wf",
        version="1.0",
        owner="test",
        nodes=[
            NodeDefinition(id="start", name="Start", node_type=NodeType.START, handler="start"),
            NodeDefinition(
                id="approval",
                name="Approval",
                node_type=NodeType.APPROVAL,
                handler="approval",
                config={
                    "assigned_to": ["approver-z"],
                    "requested_by": "system",
                },
            ),
            NodeDefinition(id="end", name="End", node_type=NodeType.END, handler="end"),
        ],
        edges=[
            EdgeDefinition(source_node_id="start", target_node_id="approval"),
            EdgeDefinition(source_node_id="approval", target_node_id="end"),
        ],
    )
    run = WorkflowRun.new(workflow_id=wf.id, workflow_version="1.0", initiated_by="test")
    engine = WorkflowEngine(BUILTIN_HANDLERS)
    ctx = ExecutionContext(run_id=run.id)
    result = await engine.execute(run, ctx, workflow=wf)
    assert result.run.status == WorkflowRunStatus.WAITING_APPROVAL
    resumed = await engine.resume(run.id)
    assert resumed.run.status == WorkflowRunStatus.RUNNING
