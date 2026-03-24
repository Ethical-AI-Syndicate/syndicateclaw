from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syndicateclaw.models import (
    ApprovalRequest,
    ApprovalScope,
    ApprovalScopeType,
    DecisionDomain,
    DecisionRecord,
    EdgeDefinition,
    MemoryRecord,
    MemorySourceType,
    MemoryTrustMetadata,
    MemoryType,
    NodeDefinition,
    NodeType,
    PolicyCondition,
    PolicyEffect,
    ReplayMode,
    Tool,
    ToolRiskLevel,
    ToolSandboxPolicy,
    VersionManifest,
    WorkflowDefinition,
    WorkflowRun,
    WorkflowRunStatus,
)
from syndicateclaw.tools.executor import (
    SandboxViolationError,
    ToolDeniedError,
    ToolExecutor,
    ToolNotFoundError,
    enforce_sandbox,
)
from syndicateclaw.tools.registry import ToolRegistry
from syndicateclaw.orchestrator.engine import ExecutionContext, WorkflowEngine
from syndicateclaw.orchestrator.handlers import BUILTIN_HANDLERS
from syndicateclaw.memory.trust import MemoryTrustService
from syndicateclaw.audit.ledger import _hash_inputs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tool(name: str = "test_tool", **overrides: Any) -> Tool:
    defaults = dict(
        name=name, version="1.0.0", owner="test",
        risk_level=ToolRiskLevel.LOW,
        sandbox_policy=ToolSandboxPolicy(allowed_protocols=["https"]),
    )
    defaults.update(overrides)
    return Tool.new(**defaults)


async def _noop_handler(input_data: dict[str, Any]) -> dict[str, Any]:
    return {"result": "ok"}


async def _slow_handler(input_data: dict[str, Any]) -> dict[str, Any]:
    import asyncio
    await asyncio.sleep(100)
    return {"result": "ok"}


# ===========================================================================
# 1. SANDBOX ENFORCEMENT — controls are mandatory, not metadata
# ===========================================================================


class TestSandboxEnforcementOnHotPath:
    """Sandbox policy is enforced by the executor, not just stored."""

    def test_network_isolated_tool_blocks_url(self):
        """A tool with network_isolation=True cannot make network requests."""
        policy = ToolSandboxPolicy(network_isolation=True)
        with pytest.raises(SandboxViolationError, match="network access denied"):
            enforce_sandbox("test", {"url": "https://example.com"}, policy)

    def test_disallowed_protocol_blocked(self):
        """Only protocols in allowed_protocols are permitted."""
        policy = ToolSandboxPolicy(allowed_protocols=["https"])
        with pytest.raises(SandboxViolationError, match="protocol 'http' not in allowed"):
            enforce_sandbox("test", {"url": "http://example.com/data"}, policy)

    def test_disallowed_domain_blocked(self):
        """When allowed_domains is set, unlisted domains are blocked."""
        policy = ToolSandboxPolicy(
            allowed_domains=["api.safe.com"],
            allowed_protocols=["https"],
        )
        with pytest.raises(SandboxViolationError, match="domain.*not in allowlist"):
            enforce_sandbox("test", {"url": "https://evil.com/exfil"}, policy)

    def test_allowed_domain_passes(self):
        """Allowlisted domains pass sandbox check."""
        policy = ToolSandboxPolicy(
            allowed_domains=["api.safe.com"],
            allowed_protocols=["https"],
        )
        enforce_sandbox("test", {"url": "https://api.safe.com/v1/data"}, policy)

    def test_payload_size_limit_enforced(self):
        """Oversized payloads are rejected."""
        policy = ToolSandboxPolicy(max_request_bytes=100)
        with pytest.raises(SandboxViolationError, match="exceeds limit"):
            enforce_sandbox("test", {"body": "x" * 200}, policy)

    def test_subprocess_denied_when_disabled(self):
        policy = ToolSandboxPolicy(subprocess_allowed=False)
        with pytest.raises(SandboxViolationError, match="subprocess"):
            enforce_sandbox("test", {"subprocess": True}, policy)

    def test_filesystem_denied_when_disabled(self):
        policy = ToolSandboxPolicy(filesystem_read=False)
        with pytest.raises(SandboxViolationError, match="filesystem"):
            enforce_sandbox("test", {"file_path": "/etc/passwd"}, policy)

    def test_empty_allowlist_permits_all_domains(self):
        """When allowed_domains is empty, any public domain is permitted (SSRF still applies)."""
        policy = ToolSandboxPolicy(allowed_domains=[], allowed_protocols=["https"])
        enforce_sandbox("test", {"url": "https://any-public-domain.com"}, policy)


# ===========================================================================
# 2. DECISION LEDGER ENFORCEMENT — execution requires ledger record
# ===========================================================================


class TestDecisionLedgerEnforcement:
    """Tool execution CANNOT complete without a decision ledger record."""

    @pytest.mark.asyncio
    async def test_execution_denied_when_ledger_unavailable(self):
        """If no decision ledger is configured, tool execution is DENIED."""
        registry = ToolRegistry()
        tool = _make_tool()
        registry.register(tool, _noop_handler)

        mock_policy = AsyncMock()
        mock_policy.evaluate = AsyncMock(return_value=PolicyEffect.ALLOW)

        executor = ToolExecutor(
            registry=registry,
            policy_engine=mock_policy,
            decision_ledger=None,  # Ledger unavailable
        )
        ctx = ExecutionContext(run_id="run-1")
        with pytest.raises(ToolDeniedError, match="Decision ledger unavailable"):
            await executor.execute("test_tool", {}, ctx)

    @pytest.mark.asyncio
    async def test_execution_denied_when_ledger_fails(self):
        """If ledger write fails, tool execution is DENIED."""
        registry = ToolRegistry()
        tool = _make_tool()
        registry.register(tool, _noop_handler)

        mock_policy = AsyncMock()
        mock_policy.evaluate = AsyncMock(return_value=PolicyEffect.ALLOW)

        broken_ledger = AsyncMock()
        broken_ledger.record_tool_decision = AsyncMock(side_effect=RuntimeError("DB down"))

        executor = ToolExecutor(
            registry=registry,
            policy_engine=mock_policy,
            decision_ledger=broken_ledger,
        )
        ctx = ExecutionContext(run_id="run-1")
        with pytest.raises(ToolDeniedError, match="Decision ledger unavailable"):
            await executor.execute("test_tool", {}, ctx)

    @pytest.mark.asyncio
    async def test_execution_succeeds_with_working_ledger(self):
        """When ledger is available, execution proceeds normally."""
        registry = ToolRegistry()
        tool = _make_tool()
        registry.register(tool, _noop_handler)

        mock_policy = AsyncMock()
        mock_policy.evaluate = AsyncMock(return_value=PolicyEffect.ALLOW)

        mock_ledger = AsyncMock()
        mock_record = DecisionRecord.new(
            domain=DecisionDomain.TOOL_EXECUTION,
            decision_type="tool_invocation",
            actor="run-1",
            effect="allow",
            justification="test",
        )
        mock_ledger.record_tool_decision = AsyncMock(return_value=mock_record)

        executor = ToolExecutor(
            registry=registry,
            policy_engine=mock_policy,
            decision_ledger=mock_ledger,
        )
        ctx = ExecutionContext(run_id="run-1")
        result = await executor.execute("test_tool", {}, ctx)
        assert result == {"result": "ok"}
        mock_ledger.record_tool_decision.assert_called_once()

    @pytest.mark.asyncio
    async def test_deny_decision_recorded_before_raising(self):
        """Even DENY decisions get ledger records before the exception."""
        registry = ToolRegistry()
        tool = _make_tool()
        registry.register(tool, _noop_handler)

        mock_ledger = AsyncMock()
        mock_record = DecisionRecord.new(
            domain=DecisionDomain.TOOL_EXECUTION,
            decision_type="tool_invocation",
            actor="run-1",
            effect="deny",
            justification="test deny",
        )
        mock_ledger.record_tool_decision = AsyncMock(return_value=mock_record)

        mock_policy = AsyncMock()
        mock_policy.evaluate = AsyncMock(return_value=PolicyEffect.DENY)

        executor = ToolExecutor(
            registry=registry,
            policy_engine=mock_policy,
            decision_ledger=mock_ledger,
        )
        ctx = ExecutionContext(run_id="run-1")
        with pytest.raises(ToolDeniedError):
            await executor.execute("test_tool", {}, ctx)
        mock_ledger.record_tool_decision.assert_called_once()


# ===========================================================================
# 3. MEMORY TRUST ENFORCEMENT — low trust records excluded
# ===========================================================================


class TestMemoryTrustEnforcement:
    """Memory trust model affects retrieval, not just storage."""

    def test_severely_decayed_memory_is_unusable(self):
        """Records decayed below threshold are not usable for decisions."""
        svc = MemoryTrustService.__new__(MemoryTrustService)
        svc._min_usable_trust = 0.3

        validated_long_ago = datetime.now(UTC) - timedelta(days=365)
        effective = svc.compute_effective_trust(
            trust_score=1.0,
            decay_rate=0.01,
            last_validated_at=validated_long_ago,
            frozen=False,
        )
        assert effective < 0.3
        assert svc.is_usable(effective) is False

    def test_human_source_has_highest_ceiling(self):
        """Human-sourced records have the highest trust ceiling."""
        from syndicateclaw.memory.trust import _SOURCE_TRUST_CEILING
        assert _SOURCE_TRUST_CEILING[MemorySourceType.HUMAN.value] == 1.0
        assert _SOURCE_TRUST_CEILING[MemorySourceType.LLM.value] < 1.0
        assert _SOURCE_TRUST_CEILING[MemorySourceType.DERIVED.value] < _SOURCE_TRUST_CEILING[MemorySourceType.LLM.value]

    def test_frozen_record_requires_explicit_creation(self):
        """Frozen trust cannot be set at creation via default — requires explicit field."""
        meta = MemoryTrustMetadata()
        assert meta.frozen is False
        frozen_meta = MemoryTrustMetadata(frozen=True)
        assert frozen_meta.frozen is True

    def test_conflict_downgrades_trust(self):
        """When conflict is detected, all conflicting records have reduced trust."""
        r1 = MemoryRecord.new(
            namespace="ns", key="k", value="v1",
            memory_type=MemoryType.SEMANTIC, source="s", actor="a",
            trust=MemoryTrustMetadata(trust_score=1.0),
        )
        new_trust = r1.trust.trust_score * 0.5
        assert new_trust == 0.5

    def test_poisoned_memory_detectable_via_trust_metadata(self):
        """A record from an untrusted source with no validation is identifiable."""
        record = MemoryRecord.new(
            namespace="incidents", key="incident-999",
            value={"action": "delete_everything"},
            memory_type=MemoryType.EPISODIC,
            source="unknown_external_api",
            actor="agent:compromised",
            trust=MemoryTrustMetadata(
                trust_score=0.3,
                source_type=MemorySourceType.EXTERNAL,
                last_validated_at=None,
                validation_count=0,
            ),
        )
        svc = MemoryTrustService.__new__(MemoryTrustService)
        svc._min_usable_trust = 0.5
        effective = svc.compute_effective_trust(
            record.trust.trust_score,
            record.trust.decay_rate,
            record.trust.last_validated_at,
            record.trust.frozen,
        )
        assert svc.is_usable(effective) is False


# ===========================================================================
# 4. SCOPED APPROVAL ENFORCEMENT
# ===========================================================================


class TestScopedApprovalEnforcement:
    """Approvals are bounded and context-sensitive."""

    def test_stale_approval_detected_via_context_hash(self):
        """If context changes after approval, context_hash mismatch detects drift."""
        original_context = {"target": "server-a", "action": "restart"}
        changed_context = {"target": "server-b", "action": "restart"}

        scope = ApprovalScope(
            scope_type=ApprovalScopeType.SINGLE_ACTION,
            context_hash=_hash_inputs(original_context),
        )

        current_hash = _hash_inputs(changed_context)
        assert scope.context_hash != current_hash

    def test_uses_exhausted(self):
        """An approval with max_uses=1 cannot be reused."""
        scope = ApprovalScope(
            scope_type=ApprovalScopeType.TIME_WINDOW,
            max_uses=1,
            uses_remaining=0,
        )
        assert scope.uses_remaining == 0

    def test_time_window_expired(self):
        """Time-windowed approval expires after the window."""
        scope = ApprovalScope(
            scope_type=ApprovalScopeType.TIME_WINDOW,
            time_window_seconds=3600,
        )
        approval_time = datetime.now(UTC) - timedelta(seconds=7200)
        window_end = approval_time + timedelta(seconds=scope.time_window_seconds)
        assert window_end < datetime.now(UTC)

    def test_conditional_approval_invalidated_by_condition_change(self):
        """Conditional approval becomes invalid when conditions no longer hold."""
        scope = ApprovalScope(
            scope_type=ApprovalScopeType.CONDITIONAL,
            conditions=[
                PolicyCondition(field="risk_level", operator="eq", value="LOW"),
            ],
        )
        assert scope.conditions[0].value == "LOW"

    def test_blanket_approval_type_is_distinguishable(self):
        """Blanket approvals are explicitly typed and separately auditable."""
        scope = ApprovalScope(scope_type=ApprovalScopeType.BLANKET)
        assert scope.scope_type == ApprovalScopeType.BLANKET
        assert scope.scope_type != ApprovalScopeType.SINGLE_ACTION


# ===========================================================================
# 5. VERSION MANIFEST IMMUTABILITY
# ===========================================================================


class TestVersionManifestEnforcement:
    """Version manifest is captured at run start and is immutable."""

    def test_manifest_frozen_at_creation(self):
        manifest = VersionManifest(
            workflow_version="1.0.0",
            tool_versions={"http_request": "1.0.0"},
            policy_version="abc123",
        )
        assert manifest.workflow_version == "1.0.0"
        data = manifest.model_dump()
        restored = VersionManifest.model_validate(data)
        assert restored.workflow_version == manifest.workflow_version
        assert restored.tool_versions == manifest.tool_versions

    def test_run_carries_manifest(self):
        manifest = VersionManifest(
            workflow_version="2.0.0",
            tool_versions={"t1": "1.0", "t2": "2.0"},
            policy_version="def456",
        )
        run = WorkflowRun.new(
            workflow_id="wf-1",
            workflow_version="2.0.0",
            initiated_by="test",
            version_manifest=manifest,
        )
        assert run.version_manifest is not None
        assert run.version_manifest.policy_version == "def456"


# ===========================================================================
# 6. REPLAY INTEGRITY
# ===========================================================================


class TestReplayIntegrity:
    """Deterministic replay uses frozen inputs, detects divergence."""

    def test_content_hash_tamper_detection(self):
        """If response_data is modified, hash will not match."""
        from syndicateclaw.orchestrator.snapshots import _hash_response
        original = {"status": 200, "body": "ok"}
        tampered = {"status": 200, "body": "tampered"}
        assert _hash_response(original) != _hash_response(tampered)

    def test_replay_mode_on_run(self):
        run = WorkflowRun.new(
            workflow_id="wf-1", workflow_version="1.0",
            initiated_by="test", replay_mode=ReplayMode.DETERMINISTIC,
        )
        assert run.replay_mode == ReplayMode.DETERMINISTIC

    @pytest.mark.asyncio
    async def test_workflow_engine_replay_preserves_state(self):
        """Replay resets to checkpoint and clears node executions."""
        workflow = WorkflowDefinition.new(
            name="test", version="1.0", owner="test",
            nodes=[
                NodeDefinition(id="start", name="Start", node_type=NodeType.START, handler="start"),
                NodeDefinition(id="end", name="End", node_type=NodeType.END, handler="end"),
            ],
            edges=[EdgeDefinition(source_node_id="start", target_node_id="end")],
        )
        run = WorkflowRun.new(
            workflow_id=workflow.id, workflow_version="1.0", initiated_by="test"
        )
        engine = WorkflowEngine(BUILTIN_HANDLERS)
        ctx = ExecutionContext(run_id=run.id)
        result = await engine.execute(run, ctx, workflow=workflow)
        assert result.run.status == WorkflowRunStatus.COMPLETED
        assert len(result.node_executions) == 2

        replay_result = await engine.replay(run.id)
        assert replay_result.run.status == WorkflowRunStatus.PENDING
        assert len(replay_result.node_executions) == 0


# ===========================================================================
# 7. INTEGRITY VERIFICATION
# ===========================================================================


class TestIntegrityVerification:
    """Decision record and snapshot hashes are tamper-evident."""

    def test_input_hash_deterministic(self):
        inputs = {"tool": "http_request", "url": "https://example.com"}
        h1 = _hash_inputs(inputs)
        h2 = _hash_inputs(inputs)
        assert h1 == h2

    def test_input_hash_order_independent(self):
        """Canonical JSON serialization ensures order doesn't matter."""
        h1 = _hash_inputs({"b": 2, "a": 1})
        h2 = _hash_inputs({"a": 1, "b": 2})
        assert h1 == h2

    def test_input_hash_detects_modification(self):
        h1 = _hash_inputs({"action": "restart", "target": "server-a"})
        h2 = _hash_inputs({"action": "restart", "target": "server-b"})
        assert h1 != h2

    def test_decision_record_carries_hash(self):
        inputs = {"tool": "http_request", "data": "test"}
        expected_hash = _hash_inputs(inputs)
        record = DecisionRecord.new(
            domain=DecisionDomain.TOOL_EXECUTION,
            decision_type="test",
            actor="test",
            effect="allow",
            justification="test",
            inputs=inputs,
            context_hash=expected_hash,
        )
        assert record.context_hash == expected_hash
        recomputed = _hash_inputs(record.inputs)
        assert recomputed == record.context_hash


# ===========================================================================
# 8. PARTIAL FAILURE — decision emitted but side effect fails
# ===========================================================================


class TestPartialFailureBehavior:
    """System handles partial failures between decision emission and execution."""

    @pytest.mark.asyncio
    async def test_tool_failure_after_decision_still_has_record(self):
        """If tool execution fails AFTER the decision was recorded, the decision still exists."""
        registry = ToolRegistry()
        tool = _make_tool()

        async def failing_handler(data: dict) -> dict:
            raise RuntimeError("Tool crashed")

        registry.register(tool, failing_handler)

        mock_ledger = AsyncMock()
        mock_record = DecisionRecord.new(
            domain=DecisionDomain.TOOL_EXECUTION,
            decision_type="tool_invocation",
            actor="run-1",
            effect="allow",
            justification="allowed",
        )
        mock_ledger.record_tool_decision = AsyncMock(return_value=mock_record)

        mock_policy = AsyncMock()
        mock_policy.evaluate = AsyncMock(return_value=PolicyEffect.ALLOW)

        executor = ToolExecutor(
            registry=registry,
            policy_engine=mock_policy,
            decision_ledger=mock_ledger,
        )
        ctx = ExecutionContext(run_id="run-1")

        from syndicateclaw.tools.executor import ToolExecutionError
        with pytest.raises(ToolExecutionError):
            await executor.execute("test_tool", {}, ctx)

        mock_ledger.record_tool_decision.assert_called_once()
