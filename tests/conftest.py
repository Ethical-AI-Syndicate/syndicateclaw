from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from syndicateclaw.models import (
    ApprovalRequest,
    ApprovalStatus,
    EdgeDefinition,
    MemoryDeletionStatus,
    MemoryLineage,
    MemoryRecord,
    MemoryType,
    NodeDefinition,
    NodeType,
    PolicyCondition,
    PolicyEffect,
    PolicyRule,
    Tool,
    ToolRiskLevel,
    WorkflowDefinition,
    WorkflowRun,
)


@pytest.fixture()
def sample_workflow_definition() -> WorkflowDefinition:
    return WorkflowDefinition.new(
        name="sample-workflow",
        version="1.0.0",
        owner="test-owner",
        description="A sample workflow for testing",
        nodes=[
            NodeDefinition(
                id="start", name="Start", node_type=NodeType.START, handler="start"
            ),
            NodeDefinition(
                id="action1", name="Action", node_type=NodeType.ACTION, handler="llm"
            ),
            NodeDefinition(
                id="decision1",
                name="Decision",
                node_type=NodeType.DECISION,
                handler="decision",
                config={"condition": "state.x == 1", "true_node": "approval1", "false_node": "end"},
            ),
            NodeDefinition(
                id="approval1",
                name="Approval",
                node_type=NodeType.APPROVAL,
                handler="approval",
                config={"description": "Needs approval", "risk_level": "MEDIUM"},
            ),
            NodeDefinition(
                id="end", name="End", node_type=NodeType.END, handler="end"
            ),
        ],
        edges=[
            EdgeDefinition(source_node_id="start", target_node_id="action1"),
            EdgeDefinition(source_node_id="action1", target_node_id="decision1"),
            EdgeDefinition(
                source_node_id="decision1",
                target_node_id="approval1",
                condition="state.x == 1",
                priority=1,
            ),
            EdgeDefinition(
                source_node_id="decision1",
                target_node_id="end",
                priority=0,
            ),
            EdgeDefinition(source_node_id="approval1", target_node_id="end"),
        ],
    )


@pytest.fixture()
def sample_workflow_run(sample_workflow_definition: WorkflowDefinition) -> WorkflowRun:
    return WorkflowRun.new(
        workflow_id=sample_workflow_definition.id,
        workflow_version=sample_workflow_definition.version,
        initiated_by="test-actor",
    )


@pytest.fixture()
def sample_tool() -> Tool:
    return Tool.new(
        name="test-tool",
        version="1.0.0",
        description="A sample tool for testing",
        owner="test-owner",
        risk_level=ToolRiskLevel.LOW,
        input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"result": {"type": "string"}}},
    )


@pytest.fixture()
def sample_memory_record() -> MemoryRecord:
    return MemoryRecord.new(
        namespace="test-ns",
        key="test-key",
        value={"data": "hello"},
        memory_type=MemoryType.SEMANTIC,
        source="unit-test",
        actor="test-actor",
        confidence=0.95,
        lineage=MemoryLineage(),
    )


@pytest.fixture()
def sample_policy_rule() -> PolicyRule:
    return PolicyRule.new(
        name="allow-low-risk-tools",
        description="Allow execution of low-risk tools",
        resource_type="tool",
        resource_pattern="test-*",
        effect=PolicyEffect.ALLOW,
        conditions=[
            PolicyCondition(field="risk_level", operator="eq", value="LOW"),
        ],
        priority=10,
        owner="test-owner",
    )


@pytest.fixture()
def sample_approval_request(sample_workflow_run: WorkflowRun) -> ApprovalRequest:
    return ApprovalRequest.new(
        run_id=sample_workflow_run.id,
        node_execution_id="node-exec-001",
        tool_name="dangerous-tool",
        action_description="Execute a high-risk tool",
        risk_level=ToolRiskLevel.HIGH,
        requested_by="test-actor",
        assigned_to=["admin@example.com"],
        expires_at=datetime.now(UTC) + timedelta(hours=24),
        context={"run_id": sample_workflow_run.id},
    )
