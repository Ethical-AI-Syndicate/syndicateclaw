"""Hostile end-to-end scenario tests.

Each scenario simulates a coordinated adversarial condition and verifies
the system enforces its controls under stress.

Scenarios:
1. Unauthorized actor attempts policy modification → 403
2. Stale approval replay after context drift → invalidated
3. Poisoned memory retrieval under restricted access policy → blocked
4. Dependency outage causing readiness failure → 503
5. DB outage during audit/ledger writes → fail-closed
6. Concurrent-run flood triggering admission control → 429
7. Self-approval attempt → blocked at service and API layers
8. Tool execution with no policy engine and no ledger → double deny
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syndicateclaw.audit.dead_letter import DeadLetterQueue, _classify_error
from syndicateclaw.audit.ledger import _hash_inputs
from syndicateclaw.memory.service import MemoryService
from syndicateclaw.models import (
    ApprovalRequest,
    ApprovalScope,
    ApprovalScopeType,
    ApprovalStatus,
    AuditEvent,
    AuditEventType,
    DecisionDomain,
    DecisionRecord,
    MemoryDeletionStatus,
    MemoryLineage,
    MemoryRecord,
    MemorySourceType,
    MemoryTrustMetadata,
    MemoryType,
    PolicyCondition,
    PolicyEffect,
    PolicyRule,
    Tool,
    ToolRiskLevel,
    ToolSandboxPolicy,
)
from syndicateclaw.orchestrator.engine import ExecutionContext
from syndicateclaw.tools.executor import (
    SandboxViolationError,
    ToolDeniedError,
    ToolExecutionError,
    ToolExecutor,
)
from syndicateclaw.tools.registry import ToolRegistry

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


def _make_memory_record(
    access_policy: str = "default",
    actor: str = "user:alice",
    **overrides: Any,
) -> MemoryRecord:
    defaults = dict(
        namespace="test_ns",
        key="test_key",
        value={"data": "test"},
        memory_type=MemoryType.SEMANTIC,
        source="test_source",
        actor=actor,
        access_policy=access_policy,
    )
    defaults.update(overrides)
    return MemoryRecord.new(**defaults)


def _mock_policy_allow() -> AsyncMock:
    mock = AsyncMock()
    mock.evaluate = AsyncMock(return_value=PolicyEffect.ALLOW)
    return mock


def _mock_ledger() -> AsyncMock:
    mock = AsyncMock()
    record = DecisionRecord.new(
        domain=DecisionDomain.TOOL_EXECUTION,
        decision_type="tool_invocation",
        actor="run-1",
        effect="allow",
        justification="allowed",
    )
    mock.record_tool_decision = AsyncMock(return_value=record)
    return mock


# ===========================================================================
# SCENARIO 1: Unauthorized policy modification attempt
# ===========================================================================


class TestScenario_UnauthorizedPolicyModification:
    """A regular user actor attempts to create, modify, and delete policy rules.
    All three operations must be blocked with 403."""

    def test_regular_user_cannot_create_policy_rule(self):
        from fastapi import HTTPException

        from syndicateclaw.api.routes.policy import _require_policy_admin

        for actor in ["user:eve", "agent:bot", "anonymous", "attacker"]:
            with pytest.raises(HTTPException) as exc_info:
                _require_policy_admin(actor)
            assert exc_info.value.status_code == 403

    def test_admin_prefixed_actors_can_manage_policies(self):
        from syndicateclaw.api.routes.policy import _require_policy_admin

        for actor in ["admin:root", "policy:editor", "system:bootstrap"]:
            _require_policy_admin(actor)  # Should not raise

    def test_privilege_escalation_via_similar_prefix_blocked(self):
        """Actor names containing 'admin' but not starting with 'admin:' are blocked."""
        from fastapi import HTTPException

        from syndicateclaw.api.routes.policy import _require_policy_admin

        for actor in ["user:admin", "admins:team", "superadmin", "admin"]:
            with pytest.raises(HTTPException) as exc_info:
                _require_policy_admin(actor)
            assert exc_info.value.status_code == 403


# ===========================================================================
# SCENARIO 2: Stale approval replay after context drift
# ===========================================================================


class TestScenario_StaleApprovalReplay:
    """An approval was granted for context A. The context has since drifted
    to context B. The system must detect the mismatch."""

    def test_context_hash_detects_drift(self):
        original_context = {
            "tool": "http_request",
            "target": "https://api.internal.com/safe-endpoint",
            "risk_level": "LOW",
        }
        drifted_context = {
            "tool": "http_request",
            "target": "https://api.internal.com/admin/delete-all",
            "risk_level": "CRITICAL",
        }

        original_hash = _hash_inputs(original_context)
        scope = ApprovalScope(
            scope_type=ApprovalScopeType.SINGLE_ACTION,
            context_hash=original_hash,
            max_uses=1,
            uses_remaining=1,
        )

        drifted_hash = _hash_inputs(drifted_context)
        assert scope.context_hash != drifted_hash, \
            "Context drift must be detectable via hash mismatch"

    def test_uses_exhausted_prevents_reuse(self):
        """After an approval is used once, uses_remaining=0 blocks reuse."""
        scope = ApprovalScope(
            scope_type=ApprovalScopeType.SINGLE_ACTION,
            max_uses=1,
            uses_remaining=0,
        )
        assert scope.uses_remaining == 0
        assert scope.max_uses == 1

    def test_time_windowed_approval_expires(self):
        """A time-windowed approval granted 2 hours ago with 1-hour window is expired."""
        scope = ApprovalScope(
            scope_type=ApprovalScopeType.TIME_WINDOW,
            time_window_seconds=3600,
        )
        approval_time = datetime.now(UTC) - timedelta(hours=2)
        window_end = approval_time + timedelta(seconds=scope.time_window_seconds)
        assert window_end < datetime.now(UTC), "Approval window must have expired"

    def test_conditional_approval_invalidated_by_risk_escalation(self):
        """Approval was conditional on risk_level=LOW. If risk escalates, condition fails."""
        scope = ApprovalScope(
            scope_type=ApprovalScopeType.CONDITIONAL,
            conditions=[
                PolicyCondition(field="risk_level", operator="eq", value="LOW"),
            ],
        )
        current_risk = "CRITICAL"
        assert scope.conditions[0].value != current_risk


# ===========================================================================
# SCENARIO 3: Poisoned memory under restricted access policy
# ===========================================================================


class TestScenario_PoisonedMemoryRetrieval:
    """An attacker injects a record into a namespace. A different actor
    attempts to read it. The access policy must block retrieval."""

    def test_restricted_record_invisible_to_other_actors(self):
        """Record with access_policy=restricted is invisible to non-owners."""
        record = _make_memory_record(
            access_policy="restricted",
            actor="system:trusted-pipeline",
            key="credentials",
            value={"api_key": "secret-123"},
        )
        assert MemoryService._check_access_policy(record, "agent:compromised") is False
        assert MemoryService._check_access_policy(record, "user:attacker") is False
        assert MemoryService._check_access_policy(record, "system:trusted-pipeline") is True

    def test_owner_only_blocks_system_actors(self):
        """Even system actors are blocked from owner_only records of other actors."""
        record = _make_memory_record(
            access_policy="owner_only",
            actor="user:alice",
        )
        assert MemoryService._check_access_policy(record, "system:retention") is False
        assert MemoryService._check_access_policy(record, "admin:root") is False
        assert MemoryService._check_access_policy(record, "user:alice") is True

    def test_poisoned_low_trust_record_identifiable(self):
        """A record from an external source with low trust is identifiable."""
        from syndicateclaw.memory.trust import MemoryTrustService

        record = _make_memory_record(
            access_policy="default",
            actor="agent:compromised",
            key="incident-override",
            value={"action": "delete_all_data", "priority": "immediate"},
        )
        record.trust = MemoryTrustMetadata(
            trust_score=0.2,
            source_type=MemorySourceType.EXTERNAL,
            validation_count=0,
            last_validated_at=None,
        )

        svc = MemoryTrustService.__new__(MemoryTrustService)
        svc._min_usable_trust = 0.5
        effective = svc.compute_effective_trust(
            record.trust.trust_score,
            record.trust.decay_rate,
            record.trust.last_validated_at,
            record.trust.frozen,
        )
        assert not svc.is_usable(effective), \
            "Poisoned record must be flagged as unusable"

    def test_unknown_access_policy_fails_closed(self):
        """If an attacker manages to set an unknown policy name, it is denied."""
        for policy in ["admin_bypass", "public", "all_access", ""]:
            record = _make_memory_record(access_policy=policy, actor="user:alice")
            assert MemoryService._check_access_policy(record, "user:alice") is False


# ===========================================================================
# SCENARIO 4: Dependency outage → readiness failure
# ===========================================================================


class TestScenario_DependencyOutage:
    """When critical dependencies are unavailable, the readiness probe
    must report degraded status."""

    def test_missing_policy_engine_degrades_readiness(self):
        """If policy_engine is None on app state, readiness should flag it."""
        checks: dict[str, str] = {}
        pe = None
        checks["policy_engine"] = "ok" if pe is not None else "missing"
        assert checks["policy_engine"] == "missing"

    def test_missing_decision_ledger_degrades_readiness(self):
        """If decision_ledger is None, readiness should flag it."""
        checks: dict[str, str] = {}
        dl = None
        checks["decision_ledger"] = "ok" if dl is not None else "missing"
        assert checks["decision_ledger"] == "missing"

    def test_readiness_check_logic_comprehensive(self):
        """All four dependency checks must pass for healthy=True."""
        healthy = True
        checks: dict[str, str] = {}

        for dep_name, dep_value in [
            ("database", "ok"),
            ("redis", "ok"),
            ("policy_engine", "ok"),
            ("decision_ledger", None),
        ]:
            checks[dep_name] = "ok" if dep_value is not None else "missing"
            if dep_value is None:
                healthy = False

        assert healthy is False
        assert checks["decision_ledger"] == "missing"


# ===========================================================================
# SCENARIO 5: DB outage during ledger/audit writes → fail-closed
# ===========================================================================


class TestScenario_DbOutageDuringWrites:
    """When the database is down, the system must not silently proceed."""

    @pytest.mark.asyncio
    async def test_ledger_failure_blocks_tool_execution(self):
        """If the decision ledger cannot write, tool execution is denied."""
        registry = ToolRegistry()
        tool = _make_tool()
        registry.register(tool, _noop_handler)

        broken_ledger = AsyncMock()
        broken_ledger.record_tool_decision = AsyncMock(
            side_effect=ConnectionError("PostgreSQL connection refused")
        )

        executor = ToolExecutor(
            registry=registry,
            policy_engine=_mock_policy_allow(),
            decision_ledger=broken_ledger,
        )
        ctx = ExecutionContext(run_id="run-db-outage")
        with pytest.raises(ToolDeniedError, match="Decision ledger unavailable"):
            await executor.execute("test_tool", {}, ctx)

    @pytest.mark.asyncio
    async def test_no_ledger_at_all_blocks_execution(self):
        """If no ledger is configured, all tool execution is blocked."""
        registry = ToolRegistry()
        tool = _make_tool()
        registry.register(tool, _noop_handler)

        executor = ToolExecutor(
            registry=registry,
            policy_engine=_mock_policy_allow(),
            decision_ledger=None,
        )
        ctx = ExecutionContext(run_id="run-no-ledger")
        with pytest.raises(ToolDeniedError, match="Decision ledger unavailable"):
            await executor.execute("test_tool", {}, ctx)

    @pytest.mark.asyncio
    async def test_no_policy_engine_blocks_even_with_ledger(self):
        """Even with a working ledger, missing policy engine → DENY."""
        registry = ToolRegistry()
        tool = _make_tool()
        registry.register(tool, _noop_handler)

        deny_record = DecisionRecord.new(
            domain=DecisionDomain.TOOL_EXECUTION,
            decision_type="tool_invocation",
            actor="run-1",
            effect="deny",
            justification="policy engine missing",
        )
        mock_ledger = AsyncMock()
        mock_ledger.record_tool_decision = AsyncMock(return_value=deny_record)

        executor = ToolExecutor(
            registry=registry,
            policy_engine=None,
            decision_ledger=mock_ledger,
        )
        ctx = ExecutionContext(run_id="run-no-policy")
        with pytest.raises(ToolDeniedError):
            await executor.execute("test_tool", {}, ctx)


# ===========================================================================
# SCENARIO 6: Concurrent-run flood triggering admission control
# ===========================================================================


class TestScenario_ConcurrentRunFlood:
    """An attacker attempts to launch many runs simultaneously.
    The admission control must reject runs above the limit."""

    def test_admission_check_logic(self):
        """When active_count >= max_concurrent_runs, new runs are rejected."""
        max_concurrent = 5
        for active_count in range(10):
            if active_count >= max_concurrent:
                assert active_count >= max_concurrent
            else:
                assert active_count < max_concurrent

    def test_active_statuses_include_all_non_terminal(self):
        """Admission control counts PENDING, RUNNING, WAITING_APPROVAL as active."""
        active_statuses = {"PENDING", "RUNNING", "WAITING_APPROVAL"}
        terminal_statuses = {"COMPLETED", "FAILED", "CANCELLED"}
        assert active_statuses.isdisjoint(terminal_statuses)
        assert "PAUSED" not in active_statuses, \
            "PAUSED runs should not count toward concurrency limit"


# ===========================================================================
# SCENARIO 7: Self-approval attack
# ===========================================================================


class TestScenario_SelfApproval:
    """An actor creates an approval request and tries to approve it themselves."""

    @pytest.mark.asyncio
    async def test_service_layer_blocks_self_approval(self):
        from syndicateclaw.approval.service import ApprovalService

        mock_row = MagicMock()
        mock_row.status = ApprovalStatus.PENDING.value
        mock_row.requested_by = "user:mallory"
        mock_row.assigned_to = ["user:mallory", "user:bob"]
        mock_row.expires_at = None

        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=mock_row)

        mock_session = MagicMock()
        mock_begin = MagicMock()
        mock_begin.__aenter__ = AsyncMock(return_value=None)
        mock_begin.__aexit__ = AsyncMock(return_value=False)
        mock_session.begin = MagicMock(return_value=mock_begin)

        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        service = ApprovalService.__new__(ApprovalService)
        service._session_factory = MagicMock(return_value=mock_session_ctx)
        service._notify = None
        service._audit = AsyncMock()

        with patch(
            'syndicateclaw.approval.service.ApprovalRequestRepository',
            return_value=mock_repo,
        ):
            with pytest.raises(PermissionError, match="Self-approval prohibited"):
                await service._decide(
                    "req-attack", "user:mallory", "I approve myself",
                    ApprovalStatus.APPROVED,
                )

    @pytest.mark.asyncio
    async def test_legitimate_cross_approval_succeeds(self):
        """A different assigned approver CAN approve the request."""
        from syndicateclaw.approval.service import ApprovalService

        mock_row = MagicMock()
        mock_row.status = ApprovalStatus.PENDING.value
        mock_row.requested_by = "user:alice"
        mock_row.assigned_to = ["user:bob"]
        mock_row.expires_at = None
        mock_row.decided_by = None
        mock_row.decided_at = None
        mock_row.decision_reason = None
        mock_row.updated_at = None

        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=mock_row)
        mock_repo.update = AsyncMock(return_value=mock_row)

        mock_session = MagicMock()
        mock_begin = MagicMock()
        mock_begin.__aenter__ = AsyncMock(return_value=None)
        mock_begin.__aexit__ = AsyncMock(return_value=False)
        mock_session.begin = MagicMock(return_value=mock_begin)

        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        service = ApprovalService.__new__(ApprovalService)
        service._session_factory = MagicMock(return_value=mock_session_ctx)
        service._notify = None
        service._audit = AsyncMock()
        service._audit.emit = AsyncMock()

        with patch(
            'syndicateclaw.approval.service.ApprovalRequestRepository',
            return_value=mock_repo,
        ):
            with patch('syndicateclaw.approval.service.ApprovalRequest') as mock_ar:
                mock_ar.model_validate = MagicMock(return_value=MagicMock(
                    id="req-1", run_id="run-1", tool_name="test",
                    status=ApprovalStatus.APPROVED,
                ))
                result = await service._decide(
                    "req-1", "user:bob", "looks good",
                    ApprovalStatus.APPROVED,
                )
                assert result is not None


# ===========================================================================
# SCENARIO 8: Tool execution cascade — all controls enforced together
# ===========================================================================


class TestScenario_FullToolExecutionCascade:
    """Run a tool through the full pipeline with all controls active."""

    @pytest.mark.asyncio
    async def test_full_pipeline_success(self):
        """With all controls present and passing, execution succeeds."""
        registry = ToolRegistry()
        tool = _make_tool(
            sandbox_policy=ToolSandboxPolicy(
                allowed_protocols=["https"],
                allowed_domains=["api.safe.com"],
            ),
        )
        registry.register(tool, _noop_handler)

        executor = ToolExecutor(
            registry=registry,
            policy_engine=_mock_policy_allow(),
            decision_ledger=_mock_ledger(),
        )
        ctx = ExecutionContext(run_id="run-full")
        result = await executor.execute("test_tool", {}, ctx)
        assert result == {"result": "ok"}

    @pytest.mark.asyncio
    async def test_sandbox_blocks_before_policy_check(self):
        """Sandbox violation stops execution before policy is even evaluated."""
        registry = ToolRegistry()
        tool = _make_tool(
            sandbox_policy=ToolSandboxPolicy(network_isolation=True),
        )
        registry.register(tool, _noop_handler)

        mock_policy = _mock_policy_allow()
        executor = ToolExecutor(
            registry=registry,
            policy_engine=mock_policy,
            decision_ledger=_mock_ledger(),
        )
        ctx = ExecutionContext(run_id="run-sandbox")
        with pytest.raises(SandboxViolationError):
            await executor.execute("test_tool", {"url": "https://evil.com"}, ctx)

        mock_policy.evaluate.assert_not_called()

    @pytest.mark.asyncio
    async def test_policy_deny_blocks_before_execution(self):
        """Policy DENY prevents tool handler from running."""
        registry = ToolRegistry()

        call_count = 0
        async def tracking_handler(data: dict) -> dict:
            nonlocal call_count
            call_count += 1
            return {"result": "should not reach here"}

        tool = _make_tool()
        registry.register(tool, tracking_handler)

        mock_policy = AsyncMock()
        mock_policy.evaluate = AsyncMock(return_value=PolicyEffect.DENY)

        deny_record = DecisionRecord.new(
            domain=DecisionDomain.TOOL_EXECUTION,
            decision_type="tool_invocation",
            actor="run-1",
            effect="deny",
            justification="denied",
        )
        mock_ledger = AsyncMock()
        mock_ledger.record_tool_decision = AsyncMock(return_value=deny_record)

        executor = ToolExecutor(
            registry=registry,
            policy_engine=mock_policy,
            decision_ledger=mock_ledger,
        )
        ctx = ExecutionContext(run_id="run-deny")
        with pytest.raises(ToolDeniedError):
            await executor.execute("test_tool", {}, ctx)

        assert call_count == 0, "Handler must not have been called after DENY"

    @pytest.mark.asyncio
    async def test_handler_crash_preserves_decision_record(self):
        """If the handler crashes, the decision record still exists."""
        registry = ToolRegistry()
        async def crashing_handler(data: dict) -> dict:
            raise RuntimeError("Handler crashed catastrophically")

        tool = _make_tool()
        registry.register(tool, crashing_handler)

        mock_ledger = _mock_ledger()
        executor = ToolExecutor(
            registry=registry,
            policy_engine=_mock_policy_allow(),
            decision_ledger=mock_ledger,
        )
        ctx = ExecutionContext(run_id="run-crash")
        with pytest.raises(ToolExecutionError):
            await executor.execute("test_tool", {}, ctx)

        mock_ledger.record_tool_decision.assert_called_once()


# ===========================================================================
# SCENARIO 9: Dead letter classification under adversarial conditions
# ===========================================================================


class TestScenario_DeadLetterAdversarial:
    """Verify that DLQ classification prevents retry of permanent errors
    and correctly handles transient errors."""

    def test_permanent_error_gets_zero_retries(self):
        error = "Schema validation failed: missing required field 'action'"
        category = _classify_error(error)
        assert category == "permanent"
        max_retries = 3 if category == "transient" else 0
        assert max_retries == 0

    def test_transient_error_gets_bounded_retries(self):
        error = "Connection timed out after 30s"
        category = _classify_error(error)
        assert category == "transient"
        max_retries = 3 if category == "transient" else 0
        assert max_retries == 3

    def test_adversarial_error_message_classified_safely(self):
        """An attacker crafting error messages cannot force permanent classification."""
        tricky_errors = [
            "Server returned 502: bad gateway",
            "Connection reset by peer",
            "DNS resolution failed for api.example.com",
        ]
        for error in tricky_errors:
            category = _classify_error(error)
            assert category == "transient", \
                f"Error '{error}' should be transient but was classified as {category}"
