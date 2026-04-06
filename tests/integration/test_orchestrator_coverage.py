"""Workflow engine integration-style tests (in-memory engine + audit capture)."""

from __future__ import annotations

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
from syndicateclaw.orchestrator.engine import ExecutionContext, WorkflowEngine
from syndicateclaw.orchestrator.handlers import BUILTIN_HANDLERS

pytestmark = pytest.mark.integration


class _RecordingAudit:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    async def record(self, event: AuditEvent) -> None:
        self.events.append(event)


def _linear_workflow() -> WorkflowDefinition:
    return WorkflowDefinition.new(
        name="orch-integ",
        version="1.0",
        owner="test",
        nodes=[
            NodeDefinition(id="start", name="Start", node_type=NodeType.START, handler="start"),
            NodeDefinition(id="end", name="End", node_type=NodeType.END, handler="end"),
        ],
        edges=[EdgeDefinition(source_node_id="start", target_node_id="end")],
    )


async def test_workflow_happy_path_end_to_end() -> None:
    wf = _linear_workflow()
    run = WorkflowRun.new(workflow_id=wf.id, workflow_version="1.0", initiated_by="actor-orch")
    audit = _RecordingAudit()
    engine = WorkflowEngine(BUILTIN_HANDLERS, audit_service=audit)
    ctx = ExecutionContext(run_id=run.id, audit_service=audit)
    result = await engine.execute(run, ctx, workflow=wf)
    assert result.run.status == WorkflowRunStatus.COMPLETED
    types = [e.event_type for e in audit.events]
    assert AuditEventType.WORKFLOW_STARTED in types
    assert AuditEventType.WORKFLOW_COMPLETED in types


async def test_workflow_node_failure_invokes_error_handler() -> None:
    async def boom(_state: dict[str, Any], _ctx: ExecutionContext) -> Any:
        raise RuntimeError("node failure")

    handlers = {**BUILTIN_HANDLERS, "boom": boom}
    wf = WorkflowDefinition.new(
        name="fail-wf",
        version="1.0",
        owner="test",
        nodes=[
            NodeDefinition(id="start", name="Start", node_type=NodeType.START, handler="start"),
            NodeDefinition(id="bad", name="Bad", node_type=NodeType.ACTION, handler="boom"),
            NodeDefinition(id="end", name="End", node_type=NodeType.END, handler="end"),
        ],
        edges=[
            EdgeDefinition(source_node_id="start", target_node_id="bad"),
            EdgeDefinition(source_node_id="bad", target_node_id="end"),
        ],
    )
    run = WorkflowRun.new(workflow_id=wf.id, workflow_version="1.0", initiated_by="test")
    engine = WorkflowEngine(handlers)
    ctx = ExecutionContext(run_id=run.id)
    result = await engine.execute(run, ctx, workflow=wf)
    assert result.run.status == WorkflowRunStatus.FAILED
    assert "node failure" in (result.run.error or "").lower()


async def test_workflow_pause_and_resume_preserves_state() -> None:
    from syndicateclaw.orchestrator.engine import PauseExecutionError

    async def pause_handler(state: dict[str, Any], _ctx: ExecutionContext) -> Any:
        raise PauseExecutionError("pause")

    handlers = {**BUILTIN_HANDLERS, "pause_me": pause_handler}
    wf = WorkflowDefinition.new(
        name="pause-wf",
        version="1.0",
        owner="test",
        nodes=[
            NodeDefinition(id="start", name="Start", node_type=NodeType.START, handler="start"),
            NodeDefinition(
                id="p",
                name="Pause",
                node_type=NodeType.ACTION,
                handler="pause_me",
            ),
            NodeDefinition(id="end", name="End", node_type=NodeType.END, handler="end"),
        ],
        edges=[
            EdgeDefinition(source_node_id="start", target_node_id="p"),
            EdgeDefinition(source_node_id="p", target_node_id="end"),
        ],
    )
    run = WorkflowRun.new(workflow_id=wf.id, workflow_version="1.0", initiated_by="test")
    run.state["marker"] = 42
    engine = WorkflowEngine(handlers)
    ctx = ExecutionContext(run_id=run.id)
    await engine.execute(run, ctx, workflow=wf)
    assert run.status == WorkflowRunStatus.PAUSED
    assert run.state.get("marker") == 42
    await engine.resume(run.id)
    assert run.status == WorkflowRunStatus.RUNNING


async def test_workflow_cancel_transitions_to_cancelled_state() -> None:
    from syndicateclaw.orchestrator.engine import PauseExecutionError

    async def pause_handler(state: dict[str, Any], _ctx: ExecutionContext) -> Any:
        raise PauseExecutionError("pause")

    handlers = {**BUILTIN_HANDLERS, "pause_me": pause_handler}
    wf = WorkflowDefinition.new(
        name="cancel-wf",
        version="1.0",
        owner="test",
        nodes=[
            NodeDefinition(id="start", name="Start", node_type=NodeType.START, handler="start"),
            NodeDefinition(id="p", name="P", node_type=NodeType.ACTION, handler="pause_me"),
            NodeDefinition(id="end", name="End", node_type=NodeType.END, handler="end"),
        ],
        edges=[
            EdgeDefinition(source_node_id="start", target_node_id="p"),
            EdgeDefinition(source_node_id="p", target_node_id="end"),
        ],
    )
    run = WorkflowRun.new(workflow_id=wf.id, workflow_version="1.0", initiated_by="test")
    audit = _RecordingAudit()
    engine = WorkflowEngine(handlers, audit_service=audit)
    ctx = ExecutionContext(run_id=run.id, audit_service=audit)
    await engine.execute(run, ctx, workflow=wf)
    assert run.status == WorkflowRunStatus.PAUSED
    await engine.cancel(run.id)
    rr = engine._runs.get(run.id)
    assert rr is not None
    assert rr.run.status == WorkflowRunStatus.CANCELLED


@pytest.mark.skip(
    reason=(
        "Replay re-queues run; full re-execute requires second execute() call. "
        "Unskip: v1.2 when orchestrator replay path is validated in integration harness."
    )
)
async def test_workflow_replay_reruns_from_checkpoint() -> None:
    pass
