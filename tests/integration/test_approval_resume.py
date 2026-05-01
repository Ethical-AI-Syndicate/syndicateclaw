from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from ulid import ULID

from syndicateclaw.audit.service import AuditService
from syndicateclaw.db.models import ApprovalRequest as ApprovalRequestRow
from syndicateclaw.db.models import AuditEvent as AuditEventRow
from syndicateclaw.db.models import NodeExecution as NodeExecutionRow
from syndicateclaw.db.models import WorkflowDefinition as WorkflowDefinitionRow
from syndicateclaw.db.models import WorkflowRun as WorkflowRunRow
from syndicateclaw.models import (
    AuditEventType,
    EdgeDefinition,
    NodeDefinition,
    NodeExecutionStatus,
    NodeType,
    PolicyEffect,
    Tool,
    ToolRiskLevel,
    ToolSandboxPolicy,
    WorkflowDefinition,
    WorkflowRun,
    WorkflowRunStatus,
)
from syndicateclaw.orchestrator.engine import (
    ExecutionContext,
    NodeHandler,
    NodeResult,
    WaitForApprovalError,
    WorkflowEngine,
)
from syndicateclaw.orchestrator.handlers import BUILTIN_HANDLERS
from syndicateclaw.tools.registry import ToolRegistry

pytestmark = [pytest.mark.integration]


@dataclass
class _Decision:
    effect: PolicyEffect


def _workflow() -> WorkflowDefinition:
    return WorkflowDefinition.new(
        name=f"approval-resume-{ULID()}",
        version="1.0",
        owner="actor",
        nodes=[
            NodeDefinition(id="a", name="A", node_type=NodeType.START, handler="a"),
            NodeDefinition(
                id="b",
                name="B",
                node_type=NodeType.ACTION,
                handler="llm",
                config={"prompt": "call danger", "allow_tool_calls": True},
            ),
            NodeDefinition(id="c", name="C", node_type=NodeType.ACTION, handler="c"),
            NodeDefinition(id="end", name="End", node_type=NodeType.END, handler="end"),
        ],
        edges=[
            EdgeDefinition(source_node_id="a", target_node_id="b"),
            EdgeDefinition(source_node_id="b", target_node_id="c"),
            EdgeDefinition(source_node_id="c", target_node_id="end"),
        ],
    )


def _tool() -> Tool:
    return Tool(
        name="danger",
        version="1.0.0",
        description="danger tool",
        input_schema={"type": "object", "properties": {}},
        output_schema={"type": "object", "properties": {}},
        owner="actor",
        risk_level=ToolRiskLevel.HIGH,
        timeout_seconds=5,
        side_effects=["write"],
        sandbox_policy=ToolSandboxPolicy(),
    )


def _tool_executor() -> SimpleNamespace:
    registry = ToolRegistry()

    async def handler(_payload: dict[str, Any]) -> dict[str, str]:
        return {"done": "true"}

    registry.register(_tool(), handler)
    policy_engine = AsyncMock()
    policy_engine.evaluate.return_value = _Decision(PolicyEffect.REQUIRE_APPROVAL)
    return SimpleNamespace(
        _registry=registry,
        _policy_engine=policy_engine,
        execute=AsyncMock(return_value={"done": "true"}),
    )


def _provider() -> AsyncMock:
    provider = AsyncMock()
    provider.infer_chat.return_value = SimpleNamespace(
        content="ready",
        model_id="model",
        tool_calls=[{"name": "danger", "arguments": {}}],
    )
    return provider


async def _a_handler(state: dict[str, Any], _ctx: ExecutionContext) -> NodeResult:
    state["a"] = "completed"
    return NodeResult(output_state=state)


async def _c_handler(state: dict[str, Any], _ctx: ExecutionContext) -> NodeResult:
    state["c"] = "executed"
    return NodeResult(output_state=state)


async def _seed_run(
    session_factory: async_sessionmaker[AsyncSession],
    workflow: WorkflowDefinition,
    run: WorkflowRun,
) -> None:
    async with session_factory() as session, session.begin():
        session.add(
            WorkflowDefinitionRow(
                id=workflow.id,
                name=workflow.name,
                version=workflow.version,
                owner=workflow.owner,
                description=workflow.description,
                nodes=[node.model_dump(mode="json") for node in workflow.nodes],
                edges=[edge.model_dump(mode="json") for edge in workflow.edges],
                metadata_=workflow.metadata,
            )
        )
        session.add(
            WorkflowRunRow(
                id=run.id,
                workflow_id=workflow.id,
                workflow_version=run.workflow_version,
                status=WorkflowRunStatus.PENDING.value,
                state=run.state,
                initiated_by=run.initiated_by,
                tags=run.tags,
            )
        )


async def _approve_request(
    session_factory: async_sessionmaker[AsyncSession],
    approval_id: str,
) -> None:
    async with session_factory() as session, session.begin():
        approval = await session.get(ApprovalRequestRow, approval_id)
        if approval is None:
            raise ValueError(f"Approval request {approval_id} not found")
        approval.status = "APPROVED"
        approval.decided_by = "approver"
        approval.decided_at = datetime.now(UTC)
        approval.decision_reason = "ok"


async def test_require_approval_persists_checkpoint_audit_and_resumes_once(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    workflow = _workflow()
    run = WorkflowRun.new(
        workflow_id=workflow.id,
        workflow_version=workflow.version,
        initiated_by="actor",
    )
    await _seed_run(session_factory, workflow, run)

    tool_executor = _tool_executor()
    provider = _provider()
    audit = AuditService(session_factory)
    handlers = {
        **BUILTIN_HANDLERS,
        "a": cast(NodeHandler, _a_handler),
        "c": cast(NodeHandler, _c_handler),
    }
    engine = WorkflowEngine(
        handlers,
        audit_service=audit,
        session_factory=session_factory,
    )
    ctx = ExecutionContext(
        run_id=run.id,
        provider_service=provider,
        tool_executor=tool_executor,
        audit_service=audit,
    )

    with pytest.raises(WaitForApprovalError) as raised:
        await engine.execute(run, ctx, workflow=workflow)

    approval_id = raised.value.approval_id
    tool_executor.execute.assert_not_awaited()

    async with session_factory() as session:
        run_row = await session.get(WorkflowRunRow, run.id)
        approval_row = await session.get(ApprovalRequestRow, approval_id)
        node_rows = list(
            (
                await session.execute(
                    select(NodeExecutionRow)
                    .where(NodeExecutionRow.run_id == run.id)
                    .order_by(NodeExecutionRow.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
        audit_rows = list(
            (
                await session.execute(
                    select(AuditEventRow).where(
                        AuditEventRow.event_type == AuditEventType.APPROVAL_REQUIRED.value,
                        AuditEventRow.resource_id == run.id,
                    )
                )
            )
            .scalars()
            .all()
        )

    assert run_row is not None
    assert run_row.status == WorkflowRunStatus.WAITING_APPROVAL.value
    assert run_row.state["_resume_from"] == "b"
    assert approval_row is not None
    assert approval_row.status == "PENDING"
    assert approval_row.tool_name == "danger"
    assert audit_rows
    assert [(node.node_id, node.status) for node in node_rows] == [
        ("a", NodeExecutionStatus.COMPLETED.value),
        ("b", NodeExecutionStatus.WAITING_APPROVAL.value),
    ]

    await _approve_request(session_factory, approval_id)
    resumed = await engine.resume_after_approval(
        run_id=run.id,
        approval_id=approval_id,
        workflow=workflow,
        context=ctx,
    )

    tool_executor.execute.assert_awaited_once()
    assert resumed.run.status == WorkflowRunStatus.COMPLETED
    async with session_factory() as session:
        completed = await session.get(WorkflowRunRow, run.id)
        approval_after = await session.get(ApprovalRequestRow, approval_id)

    assert completed is not None
    assert completed.state["a"] == "completed"
    assert completed.state["c"] == "executed"
    assert approval_after is not None
    assert approval_after.context["consumed_at"]

    with pytest.raises(ValueError, match="already been consumed"):
        await engine.resume_after_approval(
            run_id=run.id,
            approval_id=approval_id,
            workflow=workflow,
            context=ctx,
        )
    tool_executor.execute.assert_awaited_once()
