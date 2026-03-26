from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from syndicateclaw.audit.ledger import _hash_inputs
from syndicateclaw.memory.trust import MemoryTrustService
from syndicateclaw.models import (
    ApprovalRequest,
    ApprovalScope,
    ApprovalScopeType,
    DeadLetterRecord,
    DeadLetterStatus,
    DecisionDomain,
    DecisionRecord,
    InputSnapshot,
    MemoryRecord,
    MemorySourceType,
    MemoryTrustMetadata,
    MemoryType,
    PolicyCondition,
    PolicyDecision,
    PolicyEffect,
    ReplayMode,
    Tool,
    ToolRiskLevel,
    ToolSandboxPolicy,
    VersionManifest,
    WorkflowRun,
)
from syndicateclaw.orchestrator.snapshots import _hash_response


class TestDecisionLedger:
    def test_decision_record_creation(self):
        """DecisionRecord can be created with all required fields."""
        record = DecisionRecord.new(
            domain=DecisionDomain.POLICY,
            decision_type="policy_tool_access",
            actor="user:alice",
            effect="allow",
            justification="Matched rule 'allow_read_tools' (priority 100)",
            inputs={"resource_type": "tool", "resource_id": "http_request"},
            rules_evaluated=[
                {"rule_id": "r1", "name": "allow_read_tools", "matched": True},
                {
                    "rule_id": "r2",
                    "name": "deny_write_tools",
                    "matched": False,
                    "reason": "resource pattern did not match",
                },
            ],
            matched_rule="r1",
            side_effects=["tool_executed"],
        )
        assert record.domain == DecisionDomain.POLICY
        assert record.effect == "allow"
        assert len(record.rules_evaluated) == 2
        assert record.matched_rule == "r1"

    def test_decision_record_context_hash(self):
        """Context hash is computed from inputs for integrity verification."""
        inputs = {"tool": "http_request", "action": "execute"}
        expected = hashlib.sha256(
            json.dumps(inputs, sort_keys=True, default=str).encode()
        ).hexdigest()
        actual = _hash_inputs(inputs)
        assert actual == expected

    def test_decision_record_all_domains(self):
        """All decision domains can be used."""
        for domain in DecisionDomain:
            record = DecisionRecord.new(
                domain=domain,
                decision_type="test",
                actor="test",
                effect="allow",
                justification="test",
            )
            assert record.domain == domain

    def test_decision_record_captures_non_matching_rules(self):
        """The rules_evaluated field includes rules that did NOT match, with reasons."""
        rules = [
            {
                "rule_id": "r1",
                "matched": False,
                "reason": "resource_pattern 'admin_*' did not match 'http_request'",
            },
            {
                "rule_id": "r2",
                "matched": False,
                "reason": "condition actor.role == 'admin' was False",
            },
            {"rule_id": "r3", "matched": True, "reason": None},
        ]
        record = DecisionRecord.new(
            domain=DecisionDomain.POLICY,
            decision_type="tool_access",
            actor="user:bob",
            effect="allow",
            justification="Rule r3 matched",
            rules_evaluated=rules,
            matched_rule="r3",
        )
        non_matching = [r for r in record.rules_evaluated if not r["matched"]]
        assert len(non_matching) == 2
        assert all(r["reason"] for r in non_matching)


class TestMemoryTrust:
    def test_memory_trust_metadata_defaults(self):
        meta = MemoryTrustMetadata()
        assert meta.trust_score == 1.0
        assert meta.source_type == MemorySourceType.SYSTEM
        assert meta.last_validated_at is None
        assert meta.frozen is False
        assert meta.decay_rate == 0.01

    def test_memory_record_with_trust(self):
        """MemoryRecord now includes trust metadata."""
        record = MemoryRecord.new(
            namespace="incidents",
            key="inc-123",
            value={"severity": "high"},
            memory_type=MemoryType.EPISODIC,
            source="triage_workflow",
            actor="agent:triage",
            trust=MemoryTrustMetadata(
                trust_score=0.8,
                source_type=MemorySourceType.LLM,
                decay_rate=0.05,
            ),
        )
        assert record.trust.trust_score == 0.8
        assert record.trust.source_type == MemorySourceType.LLM
        assert record.trust.decay_rate == 0.05

    def test_trust_score_bounds(self):
        with pytest.raises(ValidationError):
            MemoryTrustMetadata(trust_score=1.5)
        with pytest.raises(ValidationError):
            MemoryTrustMetadata(trust_score=-0.1)

    def test_trust_decay_computation(self):
        """Trust decays linearly over time."""
        svc = MemoryTrustService.__new__(MemoryTrustService)
        svc._min_usable_trust = 0.3

        validated_10_days_ago = datetime.now(UTC) - timedelta(days=10)
        effective = svc.compute_effective_trust(
            trust_score=1.0,
            decay_rate=0.02,
            last_validated_at=validated_10_days_ago,
            frozen=False,
        )
        assert 0.79 <= effective <= 0.81  # 1.0 - (0.02 * 10) = 0.8

    def test_trust_frozen_no_decay(self):
        """Frozen records do not decay."""
        svc = MemoryTrustService.__new__(MemoryTrustService)
        svc._min_usable_trust = 0.3

        validated_100_days_ago = datetime.now(UTC) - timedelta(days=100)
        effective = svc.compute_effective_trust(
            trust_score=0.9,
            decay_rate=0.02,
            last_validated_at=validated_100_days_ago,
            frozen=True,
        )
        assert effective == 0.9

    def test_trust_usability_threshold(self):
        svc = MemoryTrustService.__new__(MemoryTrustService)
        svc._min_usable_trust = 0.3
        assert svc.is_usable(0.5) is True
        assert svc.is_usable(0.3) is True
        assert svc.is_usable(0.29) is False
        assert svc.is_usable(0.0) is False

    def test_source_type_enum_completeness(self):
        expected = {"HUMAN", "SYSTEM", "DERIVED", "EXTERNAL", "LLM"}
        actual = {e.value for e in MemorySourceType}
        assert expected == actual

    def test_conflict_set_links_records(self):
        """Multiple records can share a conflict_set_id."""
        conflict_id = "conflict-abc"
        r1 = MemoryRecord.new(
            namespace="ns",
            key="k",
            value="v1",
            memory_type=MemoryType.SEMANTIC,
            source="s",
            actor="a",
            trust=MemoryTrustMetadata(conflict_set_id=conflict_id),
        )
        r2 = MemoryRecord.new(
            namespace="ns",
            key="k",
            value="v2",
            memory_type=MemoryType.SEMANTIC,
            source="s",
            actor="a",
            trust=MemoryTrustMetadata(conflict_set_id=conflict_id),
        )
        assert r1.trust.conflict_set_id == r2.trust.conflict_set_id


class TestReplayCorrectness:
    def test_input_snapshot_creation(self):
        snap = InputSnapshot.new(
            run_id="run-1",
            node_execution_id="node-1",
            snapshot_type="tool_response",
            source_identifier="http_request",
            request_data={"url": "https://api.example.com"},
            response_data={"status": 200, "body": "ok"},
        )
        assert snap.snapshot_type == "tool_response"
        assert snap.source_identifier == "http_request"
        assert snap.response_data["status"] == 200

    def test_content_hash_deterministic(self):
        data = {"status": 200, "body": "hello"}
        h1 = _hash_response(data)
        h2 = _hash_response(data)
        assert h1 == h2

    def test_content_hash_order_independent(self):
        """JSON canonical form means key order doesn't matter."""
        d1 = {"b": 2, "a": 1}
        d2 = {"a": 1, "b": 2}
        assert _hash_response(d1) == _hash_response(d2)

    def test_content_hash_detects_change(self):
        d1 = {"status": 200}
        d2 = {"status": 201}
        assert _hash_response(d1) != _hash_response(d2)

    def test_replay_mode_enum(self):
        assert ReplayMode.LIVE.value == "LIVE"
        assert ReplayMode.DETERMINISTIC.value == "DETERMINISTIC"

    def test_workflow_run_has_replay_mode(self):
        run = WorkflowRun.new(
            workflow_id="wf-1",
            workflow_version="1.0",
            initiated_by="test",
            replay_mode=ReplayMode.DETERMINISTIC,
        )
        assert run.replay_mode == ReplayMode.DETERMINISTIC


class TestVersioning:
    def test_version_manifest_creation(self):
        manifest = VersionManifest(
            workflow_version="2.1.0",
            tool_versions={"http_request": "1.0.0", "memory_write": "1.0.0"},
            policy_version="abc123",
            platform_version="0.1.0",
        )
        assert manifest.workflow_version == "2.1.0"
        assert len(manifest.tool_versions) == 2

    def test_workflow_run_with_version_manifest(self):
        manifest = VersionManifest(
            workflow_version="1.0.0",
            tool_versions={"http_request": "1.0.0"},
            policy_version="v1",
        )
        run = WorkflowRun.new(
            workflow_id="wf-1",
            workflow_version="1.0.0",
            initiated_by="test",
            version_manifest=manifest,
        )
        assert run.version_manifest is not None
        assert run.version_manifest.workflow_version == "1.0.0"
        assert run.version_manifest.tool_versions["http_request"] == "1.0.0"

    def test_version_manifest_serialization_roundtrip(self):
        manifest = VersionManifest(
            workflow_version="1.0",
            tool_versions={"t1": "1.0"},
            policy_version="p1",
        )
        data = manifest.model_dump()
        restored = VersionManifest.model_validate(data)
        assert restored.workflow_version == manifest.workflow_version
        assert restored.tool_versions == manifest.tool_versions


class TestToolSandbox:
    def test_sandbox_policy_defaults(self):
        policy = ToolSandboxPolicy()
        assert policy.allowed_domains == []
        assert policy.allowed_protocols == ["https"]
        assert policy.max_request_bytes == 1_048_576
        assert policy.max_response_bytes == 10_485_760
        assert policy.network_isolation is False
        assert policy.filesystem_read is False
        assert policy.filesystem_write is False
        assert policy.subprocess_allowed is False

    def test_tool_with_sandbox_policy(self):
        tool = Tool.new(
            name="restricted_api",
            version="1.0.0",
            owner="ops",
            sandbox_policy=ToolSandboxPolicy(
                allowed_domains=["api.example.com", "api.internal.com"],
                allowed_protocols=["https"],
                max_request_bytes=512_000,
                network_isolation=False,
            ),
        )
        assert len(tool.sandbox_policy.allowed_domains) == 2
        assert "api.example.com" in tool.sandbox_policy.allowed_domains

    def test_network_isolated_tool(self):
        tool = Tool.new(
            name="compute_only",
            version="1.0.0",
            owner="ops",
            sandbox_policy=ToolSandboxPolicy(network_isolation=True),
        )
        assert tool.sandbox_policy.network_isolation is True
        assert tool.sandbox_policy.allowed_domains == []

    def test_sandbox_policy_serialization(self):
        policy = ToolSandboxPolicy(
            allowed_domains=["example.com"],
            filesystem_read=True,
        )
        data = policy.model_dump()
        restored = ToolSandboxPolicy.model_validate(data)
        assert restored.allowed_domains == ["example.com"]
        assert restored.filesystem_read is True


class TestScopedApprovals:
    def test_approval_scope_defaults(self):
        scope = ApprovalScope()
        assert scope.scope_type == ApprovalScopeType.SINGLE_ACTION
        assert scope.allowed_actions == []
        assert scope.max_uses is None
        assert scope.context_hash == ""

    def test_time_windowed_approval(self):
        scope = ApprovalScope(
            scope_type=ApprovalScopeType.TIME_WINDOW,
            time_window_seconds=3600,
            allowed_actions=["http_request:GET"],
        )
        assert scope.time_window_seconds == 3600

    def test_conditional_approval_with_constraints(self):
        scope = ApprovalScope(
            scope_type=ApprovalScopeType.CONDITIONAL,
            conditions=[
                PolicyCondition(field="risk_level", operator="eq", value="LOW"),
                PolicyCondition(
                    field="actor.role", operator="in", value=["admin", "operator"]
                ),
            ],
            max_uses=5,
            uses_remaining=5,
        )
        assert len(scope.conditions) == 2
        assert scope.max_uses == 5

    def test_approval_with_redaction(self):
        scope = ApprovalScope(
            scope_type=ApprovalScopeType.SINGLE_ACTION,
            redact_fields=["input.password", "input.api_key"],
        )
        assert len(scope.redact_fields) == 2

    def test_approval_request_includes_scope(self):
        request = ApprovalRequest.new(
            run_id="run-1",
            node_execution_id="node-1",
            action_description="Execute external API call",
            risk_level=ToolRiskLevel.HIGH,
            requested_by="agent:triage",
            expires_at=datetime.now(UTC) + timedelta(hours=24),
            scope=ApprovalScope(
                scope_type=ApprovalScopeType.TIME_WINDOW,
                time_window_seconds=1800,
                allowed_actions=["http_request"],
                context_hash="abc123",
            ),
        )
        assert request.scope.scope_type == ApprovalScopeType.TIME_WINDOW
        assert request.scope.context_hash == "abc123"

    def test_blanket_approval_type(self):
        scope = ApprovalScope(scope_type=ApprovalScopeType.BLANKET)
        assert scope.scope_type == ApprovalScopeType.BLANKET

    def test_context_hash_triggers_reapproval(self):
        """Context hash should change when inputs change, triggering re-approval."""
        ctx1 = {"target": "server-a", "action": "restart"}
        ctx2 = {"target": "server-b", "action": "restart"}
        h1 = _hash_inputs(ctx1)
        h2 = _hash_inputs(ctx2)
        assert h1 != h2


class TestDeadLetterClassification:
    def test_dead_letter_record_creation(self):
        record = DeadLetterRecord.new(
            event_type="TOOL_EXECUTION_COMPLETED",
            event_payload={"tool": "http_request", "status": "completed"},
            error_message="Connection refused to audit log DB",
            error_category="transient",
        )
        assert record.status == DeadLetterStatus.PENDING
        assert record.retry_count == 0
        assert record.error_category == "transient"

    def test_dead_letter_status_lifecycle(self):
        for status in DeadLetterStatus:
            record = DeadLetterRecord.new(
                event_type="test",
                event_payload={},
                error_message="test",
                status=status,
            )
            assert record.status == status

    def test_dead_letter_permanent_classification(self):
        record = DeadLetterRecord.new(
            event_type="INVALID_EVENT",
            event_payload={"garbage": True},
            error_message="Schema validation failed",
            error_category="permanent",
            max_retries=0,
        )
        assert record.error_category == "permanent"
        assert record.max_retries == 0


class TestPolicyDecisionTraceability:
    def test_policy_decision_full_trace(self):
        decision = PolicyDecision.new(
            rule_id="r1",
            rule_name="allow_read_tools",
            effect=PolicyEffect.ALLOW,
            resource_type="tool",
            resource_id="http_request",
            actor="user:alice",
            reason="Matched allow rule",
            conditions_evaluated=[
                {
                    "field": "risk_level",
                    "operator": "eq",
                    "expected": "LOW",
                    "actual": "LOW",
                    "matched": True,
                },
            ],
            all_rules_considered=[
                {
                    "rule_id": "r1",
                    "name": "allow_read_tools",
                    "effect": "ALLOW",
                    "matched": True,
                },
                {
                    "rule_id": "r2",
                    "name": "deny_admin_tools",
                    "effect": "DENY",
                    "matched": False,
                    "reason": "resource_pattern 'admin_*' did not match 'http_request'",
                },
                {
                    "rule_id": "r3",
                    "name": "require_approval_high",
                    "effect": "REQUIRE_APPROVAL",
                    "matched": False,
                    "reason": "condition risk_level == CRITICAL was False",
                },
            ],
            input_attributes={
                "resource_type": "tool",
                "resource_id": "http_request",
                "actor": "user:alice",
                "actor.role": "developer",
                "risk_level": "LOW",
            },
        )
        assert len(decision.all_rules_considered) == 3
        non_match = [r for r in decision.all_rules_considered if not r["matched"]]
        assert len(non_match) == 2
        assert all("reason" in r for r in non_match)
        assert decision.input_attributes["actor.role"] == "developer"
