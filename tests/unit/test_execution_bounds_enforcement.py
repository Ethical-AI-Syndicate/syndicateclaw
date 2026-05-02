from __future__ import annotations

import time
from typing import Any

import pytest

from syndicateclaw.models import (
    AuditEvent,
    AuditEventType,
    EdgeDefinition,
    NodeDefinition,
    NodeType,
    WorkflowDefinition,
    WorkflowRun,
    WorkflowRunStatus,
)
from syndicateclaw.orchestrator.engine import ExecutionContext, NodeResult, WorkflowEngine
from syndicateclaw.orchestrator.exceptions import WorkflowCycleDetected


class _RecordingAudit:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    async def record(self, event: AuditEvent) -> None:
        self.events.append(event)


def _run(workflow: WorkflowDefinition) -> WorkflowRun:
    return WorkflowRun.new(
        workflow_id=workflow.id,
        workflow_version=workflow.version,
        initiated_by="bounds-test",
    )


async def _record_node(state: dict[str, Any], context: ExecutionContext) -> NodeResult:
    visited = list(state.get("handler_visited", []))
    visited.append(context.node_id)
    return NodeResult(output_state={"handler_visited": visited})


def _workflow(
    *,
    nodes: list[NodeDefinition],
    edges: list[EdgeDefinition],
    name: str = "bounds-test",
) -> WorkflowDefinition:
    return WorkflowDefinition.new(
        name=name,
        version="1.0",
        owner="test",
        nodes=nodes,
        edges=edges,
    )


def _cycle_workflow() -> WorkflowDefinition:
    return _workflow(
        name="cycle-test",
        nodes=[
            NodeDefinition(id="A", name="A", node_type=NodeType.START, handler="record"),
            NodeDefinition(id="B", name="B", node_type=NodeType.ACTION, handler="record"),
        ],
        edges=[
            EdgeDefinition(source_node_id="A", target_node_id="B"),
            EdgeDefinition(source_node_id="B", target_node_id="A"),
        ],
    )


@pytest.mark.asyncio
async def test_cycle_detection_raises_and_marks_run_failed() -> None:
    workflow = _cycle_workflow()
    run = _run(workflow)
    engine = WorkflowEngine({"record": _record_node})

    with pytest.raises(WorkflowCycleDetected) as exc_info:
        await engine.execute(run, ExecutionContext(run_id=run.id), workflow=workflow)

    assert exc_info.value.run_id == run.id
    assert exc_info.value.cycle_path == ["A", "B"]
    assert exc_info.value.step_count == 3
    assert run.status == WorkflowRunStatus.FAILED
    assert run.error == "cycle_detected"
    assert run.state["_failure_reason"] == "cycle_detected"


@pytest.mark.asyncio
async def test_step_ceiling_raises_before_completing(monkeypatch: pytest.MonkeyPatch) -> None:
    nodes = [
        NodeDefinition(
            id=f"n{i}",
            name=f"n{i}",
            node_type=NodeType.START if i == 0 else NodeType.ACTION,
            handler="record",
        )
        for i in range(1001)
    ]
    edges = [
        EdgeDefinition(source_node_id=f"n{i}", target_node_id=f"n{i + 1}") for i in range(1000)
    ]
    workflow = _workflow(name="step-limit-test", nodes=nodes, edges=edges)
    run = _run(workflow)
    dispatched: list[str] = []
    engine = WorkflowEngine({"record": _record_node})

    async def fake_execute_node(
        node: NodeDefinition,
        _run_obj: WorkflowRun,
        _run_result: Any,
        _context: ExecutionContext,
        _workflow_obj: WorkflowDefinition,
    ) -> NodeResult:
        dispatched.append(node.id)
        return NodeResult(output_state={})

    monkeypatch.setattr(engine, "_execute_node", fake_execute_node)

    with pytest.raises(WorkflowCycleDetected) as exc_info:
        await engine.execute(run, ExecutionContext(run_id=run.id), workflow=workflow)

    assert exc_info.value.step_count == 1001
    assert run.status == WorkflowRunStatus.FAILED
    assert run.error == "step_limit_exceeded"
    assert len(dispatched) == 1000
    assert "n1000" not in dispatched


def test_max_steps_above_control_ceiling_raises_at_construction() -> None:
    with pytest.raises(ValueError, match="max_steps cannot exceed 1000"):
        WorkflowEngine({}, max_steps=1001)


@pytest.mark.asyncio
async def test_clean_workflow_records_step_count_and_visited_nodes() -> None:
    workflow = _workflow(
        name="clean-bounds-test",
        nodes=[
            NodeDefinition(id="A", name="A", node_type=NodeType.START, handler="record"),
            NodeDefinition(id="B", name="B", node_type=NodeType.ACTION, handler="record"),
            NodeDefinition(id="C", name="C", node_type=NodeType.END, handler="record"),
        ],
        edges=[
            EdgeDefinition(source_node_id="A", target_node_id="B"),
            EdgeDefinition(source_node_id="B", target_node_id="C"),
        ],
    )
    run = _run(workflow)
    engine = WorkflowEngine({"record": _record_node})

    result = await engine.execute(run, ExecutionContext(run_id=run.id), workflow=workflow)

    assert run.status == WorkflowRunStatus.COMPLETED
    assert result.step_count == 3
    assert result.visited_nodes == ["A", "B", "C"]
    assert run.state["handler_visited"] == ["A", "B", "C"]


@pytest.mark.asyncio
async def test_cycle_detection_completes_under_five_seconds() -> None:
    workflow = _cycle_workflow()
    run = _run(workflow)
    engine = WorkflowEngine({"record": _record_node})

    started = time.monotonic()
    with pytest.raises(WorkflowCycleDetected):
        await engine.execute(run, ExecutionContext(run_id=run.id), workflow=workflow)
    elapsed = time.monotonic() - started

    assert elapsed < 5.0


@pytest.mark.asyncio
async def test_cycle_detection_writes_audit_event_before_raise() -> None:
    workflow = _cycle_workflow()
    run = _run(workflow)
    audit = _RecordingAudit()
    engine = WorkflowEngine({"record": _record_node}, audit_service=audit)

    with pytest.raises(WorkflowCycleDetected):
        await engine.execute(run, ExecutionContext(run_id=run.id), workflow=workflow)

    failed_events = [
        event for event in audit.events if event.event_type == AuditEventType.WORKFLOW_FAILED
    ]
    assert len(failed_events) == 1
    assert failed_events[0].details["reason"] == "cycle_detected"
    assert failed_events[0].details["cycle_path"] == ["A", "B"]


@pytest.mark.asyncio
async def test_run_persisted_failed_before_cycle_exception_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow = _cycle_workflow()
    run = _run(workflow)
    engine = WorkflowEngine({"record": _record_node})
    calls: list[tuple[str, WorkflowRunStatus, str | None]] = []

    async def fake_persist(failed_run: WorkflowRun) -> None:
        calls.append(("persist", failed_run.status, failed_run.error))

    async def fake_audit(**kwargs: Any) -> None:
        audited_run = kwargs["run"]
        calls.append(("audit", audited_run.status, audited_run.error))

    monkeypatch.setattr(engine, "_persist_run_failure", fake_persist)
    monkeypatch.setattr(engine, "_emit_workflow_failed_audit", fake_audit)

    with pytest.raises(WorkflowCycleDetected):
        await engine.execute(run, ExecutionContext(run_id=run.id), workflow=workflow)

    assert calls == [
        ("persist", WorkflowRunStatus.FAILED, "cycle_detected"),
        ("audit", WorkflowRunStatus.FAILED, "cycle_detected"),
    ]
