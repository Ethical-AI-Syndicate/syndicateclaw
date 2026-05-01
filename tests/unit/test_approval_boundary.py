from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from syndicateclaw.models import (
    AuditEvent,
    AuditEventType,
    EdgeDefinition,
    NodeDefinition,
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
    NodeResult,
    WaitForApprovalError,
    WorkflowEngine,
)
from syndicateclaw.orchestrator.handlers import BUILTIN_HANDLERS
from syndicateclaw.tools.registry import ToolRegistry


@pytest.fixture(scope="session", autouse=True)
async def seed_rbac_for_tests() -> None:
    return None


@dataclass
class _Decision:
    effect: PolicyEffect


class _RecordingAudit:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    async def record(self, event: AuditEvent) -> None:
        self.events.append(event)


class _FailingAudit:
    async def record(self, event: AuditEvent) -> None:
        if event.event_type == AuditEventType.APPROVAL_REQUIRED:
            raise RuntimeError("audit down")


def _approval_tool() -> Tool:
    return Tool(
        name="danger",
        version="1.0.0",
        description="danger tool",
        input_schema={"type": "object", "properties": {}},
        output_schema={"type": "object", "properties": {}},
        owner="test",
        risk_level=ToolRiskLevel.HIGH,
        timeout_seconds=5,
        side_effects=["unit-test-side-effect"],
        sandbox_policy=ToolSandboxPolicy(),
    )


def _workflow() -> WorkflowDefinition:
    return WorkflowDefinition.new(
        name="approval-boundary",
        version="1.0",
        owner="test",
        nodes=[
            NodeDefinition(id="a", name="A", node_type=NodeType.START, handler="a"),
            NodeDefinition(
                id="b",
                name="B",
                node_type=NodeType.ACTION,
                handler="llm",
                config={"prompt": "call tool", "allow_tool_calls": True},
            ),
            NodeDefinition(id="c", name="C", node_type=NodeType.ACTION, handler="c"),
        ],
        edges=[
            EdgeDefinition(source_node_id="a", target_node_id="b"),
            EdgeDefinition(source_node_id="b", target_node_id="c"),
        ],
    )


def _tool_executor() -> SimpleNamespace:
    registry = ToolRegistry()

    async def handler(_payload: dict[str, Any]) -> dict[str, str]:
        return {"ok": "true"}

    registry.register(_approval_tool(), handler)
    policy_engine = AsyncMock()
    policy_engine.evaluate.return_value = _Decision(PolicyEffect.REQUIRE_APPROVAL)
    return SimpleNamespace(
        _registry=registry,
        _policy_engine=policy_engine,
        execute=AsyncMock(return_value={"ok": "true"}),
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


async def test_require_approval_halts_and_propagates_without_tool_side_effect() -> None:
    audit = _RecordingAudit()
    tool_executor = _tool_executor()
    engine = WorkflowEngine(
        {**BUILTIN_HANDLERS, "a": _a_handler, "c": _c_handler},
        audit_service=audit,
    )
    run = WorkflowRun.new(workflow_id="wf-1", workflow_version="1.0", initiated_by="actor")
    ctx = ExecutionContext(
        run_id=run.id,
        provider_service=_provider(),
        tool_executor=tool_executor,
        audit_service=audit,
    )

    with pytest.raises(WaitForApprovalError) as raised:
        await engine.execute(run, ctx, workflow=_workflow())

    assert run.status == WorkflowRunStatus.WAITING_APPROVAL
    assert run.state["a"] == "completed"
    assert "c" not in run.state
    tool_executor.execute.assert_not_awaited()
    assert raised.value.approval_id
    assert raised.value.node_id == "b"
    assert raised.value.tool_name == "danger"
    assert raised.value.persisted_state["_resume_from"] == "b"
    assert any(event.event_type == AuditEventType.APPROVAL_REQUIRED for event in audit.events)


async def test_audit_failure_does_not_suppress_wait_for_approval() -> None:
    tool_executor = _tool_executor()
    engine = WorkflowEngine(
        {**BUILTIN_HANDLERS, "a": _a_handler, "c": _c_handler},
        audit_service=_FailingAudit(),
    )
    run = WorkflowRun.new(workflow_id="wf-1", workflow_version="1.0", initiated_by="actor")
    ctx = ExecutionContext(
        run_id=run.id,
        provider_service=_provider(),
        tool_executor=tool_executor,
        audit_service=_FailingAudit(),
    )

    with pytest.raises(WaitForApprovalError):
        await engine.execute(run, ctx, workflow=_workflow())

    assert run.status == WorkflowRunStatus.WAITING_APPROVAL
    tool_executor.execute.assert_not_awaited()


def test_wait_for_approval_error_is_json_serializable() -> None:
    err = WaitForApprovalError(
        approval_id="appr-1",
        tool_name="danger",
        node_id="b",
        run_id="run-1",
        persisted_state={"seen": {"value"}},
    )

    payload = err.to_dict()
    assert payload["approval_id"] == "appr-1"
    assert err.to_json()
