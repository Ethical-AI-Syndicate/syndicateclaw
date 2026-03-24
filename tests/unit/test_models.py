from __future__ import annotations

import pytest
from pydantic import ValidationError

from syndicateclaw.models import (
    AuditEventType,
    BaseEntity,
    EdgeDefinition,
    MemoryRecord,
    MemoryType,
    NodeDefinition,
    NodeType,
    PolicyCondition,
    ToolAuditConfig,
    WorkflowDefinition,
    WorkflowRunStatus,
)


class TestBaseEntity:
    def test_base_entity_generates_ulid(self):
        entity = BaseEntity()
        assert isinstance(entity.id, str)
        assert len(entity.id) == 26  # ULID string length

    def test_base_entity_new_classmethod(self):
        entity = BaseEntity.new()
        assert isinstance(entity.id, str)
        assert len(entity.id) == 26
        assert entity.created_at is not None
        assert entity.updated_at is not None
        assert entity.created_at == entity.updated_at


class TestWorkflowDefinition:
    def test_workflow_definition_serialization(self):
        wf = WorkflowDefinition.new(
            name="roundtrip",
            version="2.0",
            owner="tester",
            nodes=[
                NodeDefinition(
                    id="s", name="Start", node_type=NodeType.START, handler="start"
                ),
                NodeDefinition(
                    id="e", name="End", node_type=NodeType.END, handler="end"
                ),
            ],
            edges=[EdgeDefinition(source_node_id="s", target_node_id="e")],
        )
        data = wf.model_dump()
        restored = WorkflowDefinition.model_validate(data)

        assert restored.name == wf.name
        assert restored.version == wf.version
        assert restored.owner == wf.owner
        assert len(restored.nodes) == 2
        assert len(restored.edges) == 1
        assert restored.id == wf.id


class TestNodeDefinition:
    def test_node_definition_validation_valid(self):
        node = NodeDefinition(
            id="n1", name="Node", node_type=NodeType.ACTION, handler="my_handler"
        )
        assert node.id == "n1"
        assert node.node_type == NodeType.ACTION

    def test_node_definition_validation_missing_required(self):
        with pytest.raises(ValidationError):
            NodeDefinition(id="n1", name="Node", node_type=NodeType.ACTION)  # type: ignore[call-arg]

    def test_node_definition_all_types(self):
        for nt in NodeType:
            node = NodeDefinition(id=f"n-{nt.value}", name=nt.value, node_type=nt, handler="h")
            assert node.node_type == nt


class TestEdgeDefinition:
    def test_edge_definition_defaults(self):
        edge = EdgeDefinition(source_node_id="a", target_node_id="b")
        assert edge.priority == 0
        assert edge.condition is None


class TestToolAuditConfig:
    def test_tool_audit_config_defaults(self):
        config = ToolAuditConfig()
        assert config.log_input is True
        assert config.log_output is True
        assert config.redact_fields == []


class TestMemoryRecordConfidence:
    def test_memory_record_confidence_valid_zero(self):
        record = MemoryRecord.new(
            namespace="ns",
            key="k",
            value="v",
            memory_type=MemoryType.EPISODIC,
            source="test",
            actor="test",
            confidence=0.0,
        )
        assert record.confidence == 0.0

    def test_memory_record_confidence_valid_one(self):
        record = MemoryRecord.new(
            namespace="ns",
            key="k",
            value="v",
            memory_type=MemoryType.EPISODIC,
            source="test",
            actor="test",
            confidence=1.0,
        )
        assert record.confidence == 1.0

    def test_memory_record_confidence_too_low(self):
        with pytest.raises(ValidationError):
            MemoryRecord.new(
                namespace="ns",
                key="k",
                value="v",
                memory_type=MemoryType.EPISODIC,
                source="test",
                actor="test",
                confidence=-0.1,
            )

    def test_memory_record_confidence_too_high(self):
        with pytest.raises(ValidationError):
            MemoryRecord.new(
                namespace="ns",
                key="k",
                value="v",
                memory_type=MemoryType.EPISODIC,
                source="test",
                actor="test",
                confidence=1.1,
            )


class TestPolicyCondition:
    @pytest.mark.parametrize("op", ["eq", "neq", "in", "not_in", "gt", "lt", "matches"])
    def test_policy_condition_operators(self, op: str):
        cond = PolicyCondition(field="risk_level", operator=op, value="LOW")
        assert cond.operator == op


class TestWorkflowRunStatus:
    def test_workflow_run_status_transitions(self):
        expected = {"PENDING", "RUNNING", "PAUSED", "WAITING_APPROVAL", "COMPLETED", "FAILED", "CANCELLED"}
        actual = {s.value for s in WorkflowRunStatus}
        assert actual == expected


class TestAuditEventType:
    def test_audit_event_type_completeness(self):
        expected_prefixes = {
            "WORKFLOW_CREATED", "WORKFLOW_STARTED", "WORKFLOW_COMPLETED",
            "WORKFLOW_FAILED", "WORKFLOW_PAUSED", "WORKFLOW_RESUMED", "WORKFLOW_CANCELLED",
            "NODE_STARTED", "NODE_COMPLETED", "NODE_FAILED", "NODE_SKIPPED", "NODE_RETRIED",
            "TOOL_REGISTERED", "TOOL_UPDATED", "TOOL_DISABLED",
            "TOOL_EXECUTION_STARTED", "TOOL_EXECUTION_COMPLETED",
            "TOOL_EXECUTION_FAILED", "TOOL_EXECUTION_TIMED_OUT",
            "MEMORY_CREATED", "MEMORY_UPDATED", "MEMORY_ACCESSED",
            "MEMORY_DELETED", "MEMORY_EXPIRED",
            "MEMORY_TRUST_DECAYED", "MEMORY_CONFLICT_DETECTED", "MEMORY_VALIDATED",
            "POLICY_CREATED", "POLICY_UPDATED", "POLICY_DELETED",
            "POLICY_EVALUATED", "POLICY_DENIED",
            "APPROVAL_REQUESTED", "APPROVAL_APPROVED",
            "APPROVAL_REJECTED", "APPROVAL_EXPIRED",
            "HTTP_REQUEST",
            "DECISION_RECORDED",
            "INPUT_SNAPSHOT_CAPTURED", "REPLAY_STARTED", "REPLAY_DIVERGENCE_DETECTED",
            "INFERENCE_STARTED", "INFERENCE_COMPLETED", "INFERENCE_FAILED",
            "INFERENCE_STREAM_STARTED", "INFERENCE_STREAM_COMPLETED", "INFERENCE_STREAM_FAILED",
        }
        actual = {e.value for e in AuditEventType}
        assert expected_prefixes == actual
