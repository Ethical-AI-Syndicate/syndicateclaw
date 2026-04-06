from __future__ import annotations

from typing import Any

import pytest

from syndicateclaw.models import (
    EdgeDefinition,
    NodeDefinition,
    NodeType,
    WorkflowDefinition,
    WorkflowRun,
    WorkflowRunStatus,
)
from syndicateclaw.orchestrator.engine import (
    ExecutionContext,
    NodeResult,
    WorkflowEngine,
    safe_eval_condition,
)
from syndicateclaw.orchestrator.handlers import BUILTIN_HANDLERS

# ---------------------------------------------------------------------------
# safe_eval_condition tests
# ---------------------------------------------------------------------------


class TestSafeEvalCondition:
    def test_safe_eval_simple_equality(self) -> None:
        assert safe_eval_condition("state.x == 1", {"x": 1}) is True
        assert safe_eval_condition("state.x == 1", {"x": 2}) is False

    def test_safe_eval_string_comparison(self) -> None:
        assert safe_eval_condition("state.name == 'foo'", {"name": "foo"}) is True
        assert safe_eval_condition("state.name == 'foo'", {"name": "bar"}) is False

    def test_safe_eval_in_list(self) -> None:
        assert safe_eval_condition("state.x in [1, 2, 3]", {"x": 2}) is True
        assert safe_eval_condition("state.x in [1, 2, 3]", {"x": 5}) is False

    def test_safe_eval_and_or(self) -> None:
        assert safe_eval_condition("state.x == 1 and state.y == 2", {"x": 1, "y": 2}) is True
        assert safe_eval_condition("state.x == 1 and state.y == 2", {"x": 1, "y": 3}) is False
        assert safe_eval_condition("state.x == 1 or state.y == 2", {"x": 1, "y": 3}) is True
        assert safe_eval_condition("state.x == 1 or state.y == 2", {"x": 0, "y": 3}) is False

    def test_safe_eval_not(self) -> None:
        assert safe_eval_condition("not state.x == 1", {"x": 2}) is True
        assert safe_eval_condition("not state.x == 1", {"x": 1}) is False

    def test_safe_eval_greater_less(self) -> None:
        assert safe_eval_condition("state.x > 5", {"x": 10}) is True
        assert safe_eval_condition("state.x > 5", {"x": 3}) is False
        assert safe_eval_condition("state.x < 5", {"x": 3}) is True
        assert safe_eval_condition("state.x >= 5", {"x": 5}) is True
        assert safe_eval_condition("state.x <= 5", {"x": 5}) is True

    def test_safe_eval_parentheses(self) -> None:
        result = safe_eval_condition(
            "(state.x == 1 or state.y == 2) and state.z == 3",
            {"x": 1, "y": 0, "z": 3},
        )
        assert result is True

        result = safe_eval_condition(
            "(state.x == 1 or state.y == 2) and state.z == 3",
            {"x": 0, "y": 0, "z": 3},
        )
        assert result is False

    def test_safe_eval_rejects_injection(self) -> None:
        with pytest.raises(ValueError):
            safe_eval_condition("__import__('os').system('rm -rf /')", {})

        with pytest.raises(ValueError):
            safe_eval_condition("eval('1+1')", {})

    def test_safe_eval_empty_expression(self) -> None:
        with pytest.raises(ValueError, match="Unexpected end of expression"):
            safe_eval_condition("", {})


# ---------------------------------------------------------------------------
# WorkflowEngine tests
# ---------------------------------------------------------------------------


class TestWorkflowEngine:
    async def test_workflow_engine_execute_simple(self) -> None:
        workflow = WorkflowDefinition.new(
            name="test",
            version="1.0",
            owner="test",
            nodes=[
                NodeDefinition(id="start", name="Start", node_type=NodeType.START, handler="start"),
                NodeDefinition(id="end", name="End", node_type=NodeType.END, handler="end"),
            ],
            edges=[EdgeDefinition(source_node_id="start", target_node_id="end")],
        )
        run = WorkflowRun.new(workflow_id=workflow.id, workflow_version="1.0", initiated_by="test")
        engine = WorkflowEngine(BUILTIN_HANDLERS)
        context = ExecutionContext(run_id=run.id)
        result = await engine.execute(run, context, workflow=workflow)

        assert result.run.status == WorkflowRunStatus.COMPLETED
        assert result.run.completed_at is not None
        assert len(result.node_executions) == 2

    async def test_workflow_engine_decision_node(self) -> None:
        workflow = WorkflowDefinition.new(
            name="decision-test",
            version="1.0",
            owner="test",
            nodes=[
                NodeDefinition(id="start", name="Start", node_type=NodeType.START, handler="start"),
                NodeDefinition(
                    id="decide",
                    name="Decide",
                    node_type=NodeType.DECISION,
                    handler="decision",
                    config={
                        "condition": "state.route == 'a'",
                        "true_node": "end_a",
                        "false_node": "end_b",
                    },
                ),
                NodeDefinition(id="end_a", name="End A", node_type=NodeType.END, handler="end"),
                NodeDefinition(id="end_b", name="End B", node_type=NodeType.END, handler="end"),
            ],
            edges=[
                EdgeDefinition(source_node_id="start", target_node_id="decide"),
                EdgeDefinition(source_node_id="decide", target_node_id="end_a"),
                EdgeDefinition(source_node_id="decide", target_node_id="end_b"),
            ],
        )

        run = WorkflowRun.new(
            workflow_id=workflow.id,
            workflow_version="1.0",
            initiated_by="test",
            state={"route": "a"},
        )
        engine = WorkflowEngine(BUILTIN_HANDLERS)
        context = ExecutionContext(run_id=run.id)
        result = await engine.execute(run, context, workflow=workflow)

        assert result.run.status == WorkflowRunStatus.COMPLETED
        executed_node_ids = [ne.node_id for ne in result.node_executions]
        assert "end_a" in executed_node_ids
        assert "end_b" not in executed_node_ids

    async def test_workflow_engine_missing_handler(self) -> None:
        workflow = WorkflowDefinition.new(
            name="missing-handler",
            version="1.0",
            owner="test",
            nodes=[
                NodeDefinition(id="start", name="Start", node_type=NodeType.START, handler="start"),
                NodeDefinition(
                    id="bad",
                    name="Bad",
                    node_type=NodeType.ACTION,
                    handler="nonexistent_handler",
                ),
                NodeDefinition(id="end", name="End", node_type=NodeType.END, handler="end"),
            ],
            edges=[
                EdgeDefinition(source_node_id="start", target_node_id="bad"),
                EdgeDefinition(source_node_id="bad", target_node_id="end"),
            ],
        )
        run = WorkflowRun.new(workflow_id=workflow.id, workflow_version="1.0", initiated_by="test")
        engine = WorkflowEngine(BUILTIN_HANDLERS)
        context = ExecutionContext(run_id=run.id)
        result = await engine.execute(run, context, workflow=workflow)

        assert result.run.status == WorkflowRunStatus.FAILED
        assert "nonexistent_handler" in (result.run.error or "")

    async def test_workflow_engine_pause_resume(self) -> None:
        async def pause_handler(state: dict[str, Any], ctx: ExecutionContext) -> NodeResult:
            from syndicateclaw.orchestrator.engine import PauseExecutionError

            raise PauseExecutionError("Pausing for test")

        handlers = {**BUILTIN_HANDLERS, "pause_me": pause_handler}

        workflow = WorkflowDefinition.new(
            name="pause-test",
            version="1.0",
            owner="test",
            nodes=[
                NodeDefinition(id="start", name="Start", node_type=NodeType.START, handler="start"),
                NodeDefinition(
                    id="pause_node",
                    name="Pause",
                    node_type=NodeType.ACTION,
                    handler="pause_me",
                ),
                NodeDefinition(id="end", name="End", node_type=NodeType.END, handler="end"),
            ],
            edges=[
                EdgeDefinition(source_node_id="start", target_node_id="pause_node"),
                EdgeDefinition(source_node_id="pause_node", target_node_id="end"),
            ],
        )
        run = WorkflowRun.new(workflow_id=workflow.id, workflow_version="1.0", initiated_by="test")
        engine = WorkflowEngine(handlers)
        context = ExecutionContext(run_id=run.id)

        result = await engine.execute(run, context, workflow=workflow)
        assert result.run.status == WorkflowRunStatus.PAUSED

        resumed = await engine.resume(run.id)
        assert resumed.run.status == WorkflowRunStatus.RUNNING
