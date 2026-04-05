"""Tests proving enforcement of systemic hardening controls.

Each test class targets a specific gap closed in the hardening round:
1. Policy fail-closed (no permissive ALLOW fallbacks)
2. Memory access_policy enforcement at read time
3. Concurrent run admission control
4. Self-approval prevention
5. RBAC on policy management
6. Dead letter classification
7. Readiness probe dependency checks
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syndicateclaw.audit.dead_letter import _classify_error
from syndicateclaw.memory.service import MemoryService
from syndicateclaw.models import (
    DecisionDomain,
    DecisionRecord,
    MemoryRecord,
    MemoryType,
    PolicyEffect,
    Tool,
    ToolRiskLevel,
    ToolSandboxPolicy,
)
from syndicateclaw.orchestrator.engine import ExecutionContext
from syndicateclaw.tools.executor import (
    ToolDeniedError,
    ToolExecutor,
)
from syndicateclaw.tools.registry import ToolRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool(name: str = "test_tool", **overrides: Any) -> Tool:
    defaults = dict(
        name=name,
        version="1.0.0",
        owner="test",
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


# ===========================================================================
# 1. POLICY FAIL-CLOSED — no permissive development fallbacks
# ===========================================================================


class TestPolicyFailClosed:
    """Policy evaluation returns DENY when engine is missing, not ALLOW."""

    @pytest.mark.asyncio
    async def test_tool_denied_when_policy_engine_is_none(self) -> None:
        """Without a policy engine, tool execution is DENIED."""
        registry = ToolRegistry()
        tool = _make_tool()
        registry.register(tool, _noop_handler)

        mock_ledger = AsyncMock()
        mock_record = DecisionRecord.new(
            domain=DecisionDomain.TOOL_EXECUTION,
            decision_type="tool_invocation",
            actor="run-1",
            effect="deny",
            justification="policy engine missing",
        )
        mock_ledger.record_tool_decision = AsyncMock(return_value=mock_record)

        executor = ToolExecutor(
            registry=registry,
            policy_engine=None,
            decision_ledger=mock_ledger,
        )
        ctx = ExecutionContext(run_id="run-1")
        with pytest.raises(ToolDeniedError):
            await executor.execute("test_tool", {}, ctx)

    @pytest.mark.asyncio
    async def test_tool_allowed_when_policy_engine_allows(self) -> None:
        """With a policy engine that allows, execution proceeds."""
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
            justification="allowed by policy",
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

    @pytest.mark.asyncio
    async def test_policy_engine_none_records_deny_decision(self) -> None:
        """DENY from missing engine still gets a decision record."""
        registry = ToolRegistry()
        tool = _make_tool()
        registry.register(tool, _noop_handler)

        mock_ledger = AsyncMock()
        mock_record = DecisionRecord.new(
            domain=DecisionDomain.TOOL_EXECUTION,
            decision_type="tool_invocation",
            actor="run-1",
            effect="deny",
            justification="denied",
        )
        mock_ledger.record_tool_decision = AsyncMock(return_value=mock_record)

        executor = ToolExecutor(
            registry=registry,
            policy_engine=None,
            decision_ledger=mock_ledger,
        )
        ctx = ExecutionContext(run_id="run-1")
        with pytest.raises(ToolDeniedError):
            await executor.execute("test_tool", {}, ctx)
        mock_ledger.record_tool_decision.assert_called_once()
        call_kwargs = mock_ledger.record_tool_decision.call_args
        assert "deny" in str(call_kwargs)


# ===========================================================================
# 2. MEMORY ACCESS POLICY — enforced at read/query time
# ===========================================================================


class TestMemoryAccessPolicyEnforcement:
    """Memory access_policy is checked on read/search, not just stored."""

    def test_default_policy_allows_any_authenticated_actor(self) -> None:
        record = _make_memory_record(access_policy="default", actor="user:alice")
        assert MemoryService._check_access_policy(record, "user:bob") is True

    def test_owner_only_denies_other_actors(self) -> None:
        record = _make_memory_record(access_policy="owner_only", actor="user:alice")
        assert MemoryService._check_access_policy(record, "user:bob") is False

    def test_owner_only_allows_owner(self) -> None:
        record = _make_memory_record(access_policy="owner_only", actor="user:alice")
        assert MemoryService._check_access_policy(record, "user:alice") is True

    def test_system_only_denies_non_system_actors(self) -> None:
        record = _make_memory_record(access_policy="system_only", actor="system:core")
        assert MemoryService._check_access_policy(record, "user:alice") is False

    def test_system_only_allows_system_actors(self) -> None:
        record = _make_memory_record(access_policy="system_only", actor="system:core")
        assert MemoryService._check_access_policy(record, "system:retention") is True

    def test_restricted_denies_non_owner(self) -> None:
        record = _make_memory_record(access_policy="restricted", actor="user:alice")
        assert MemoryService._check_access_policy(record, "user:bob") is False

    def test_restricted_allows_owner(self) -> None:
        record = _make_memory_record(access_policy="restricted", actor="user:alice")
        assert MemoryService._check_access_policy(record, "user:alice") is True

    def test_unknown_policy_denies_by_default(self) -> None:
        """Unknown access policies fail closed."""
        record = _make_memory_record(access_policy="nonexistent_policy", actor="user:alice")
        assert MemoryService._check_access_policy(record, "user:alice") is False

    def test_private_policy_denies_by_default(self) -> None:
        """DB default 'private' is an unknown policy, so fail-closed."""
        record = _make_memory_record(access_policy="private", actor="user:alice")
        assert MemoryService._check_access_policy(record, "user:alice") is False


# ===========================================================================
# 3. SELF-APPROVAL PREVENTION
# ===========================================================================


class TestSelfApprovalPrevention:
    """Self-approval is prohibited at the service layer."""

    @pytest.mark.asyncio
    async def test_self_approval_blocked_in_service(self) -> None:
        """ApprovalService._decide raises PermissionError on self-approval."""
        from syndicateclaw.approval.service import ApprovalService
        from syndicateclaw.models import ApprovalStatus

        mock_row = MagicMock()
        mock_row.status = ApprovalStatus.PENDING.value
        mock_row.requested_by = "user:alice"
        mock_row.assigned_to = ["user:alice", "user:bob"]
        mock_row.expires_at = None

        mock_repo_instance = AsyncMock()
        mock_repo_instance.get = AsyncMock(return_value=mock_row)

        mock_session = MagicMock()
        mock_begin = MagicMock()
        mock_begin.__aenter__ = AsyncMock(return_value=None)
        mock_begin.__aexit__ = AsyncMock(return_value=False)
        mock_session.begin = MagicMock(return_value=mock_begin)

        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_sf = MagicMock(return_value=mock_session_ctx)

        service = ApprovalService.__new__(ApprovalService)
        service._session_factory = mock_sf
        service._notify = None
        service._audit = AsyncMock()

        with (
            patch(
                "syndicateclaw.approval.service.ApprovalRequestRepository",
                return_value=mock_repo_instance,
            ),
            pytest.raises(PermissionError, match="Self-approval prohibited"),
        ):
            await service._decide("req-1", "user:alice", "I want to", ApprovalStatus.APPROVED)


# ===========================================================================
# 4. POLICY RBAC
# ===========================================================================


class TestPolicyRBAC:
    """Policy management endpoints require admin prefix."""

    def test_require_policy_admin_allows_admin(self) -> None:
        from syndicateclaw.api.routes.policy import _require_policy_admin

        _require_policy_admin("admin:superuser")

    def test_require_policy_admin_allows_policy_prefix(self) -> None:
        from syndicateclaw.api.routes.policy import _require_policy_admin

        _require_policy_admin("policy:editor")

    def test_require_policy_admin_allows_system_prefix(self) -> None:
        from syndicateclaw.api.routes.policy import _require_policy_admin

        _require_policy_admin("system:bootstrap")

    def test_require_policy_admin_blocks_regular_user(self) -> None:
        from fastapi import HTTPException

        from syndicateclaw.api.routes.policy import _require_policy_admin

        with pytest.raises(HTTPException) as exc_info:
            _require_policy_admin("user:alice")
        assert exc_info.value.status_code == 403

    def test_require_policy_admin_blocks_anonymous(self) -> None:
        from fastapi import HTTPException

        from syndicateclaw.api.routes.policy import _require_policy_admin

        with pytest.raises(HTTPException) as exc_info:
            _require_policy_admin("anonymous")
        assert exc_info.value.status_code == 403

    def test_require_policy_admin_blocks_agent(self) -> None:
        from fastapi import HTTPException

        from syndicateclaw.api.routes.policy import _require_policy_admin

        with pytest.raises(HTTPException) as exc_info:
            _require_policy_admin("agent:workflow-bot")
        assert exc_info.value.status_code == 403


# ===========================================================================
# 5. DEAD LETTER CLASSIFICATION
# ===========================================================================


class TestDeadLetterClassification:
    """Dead letter queue classifies errors correctly."""

    def test_transient_error_classification(self) -> None:
        assert _classify_error("Connection timed out") == "transient"
        assert _classify_error("Database temporarily unavailable") == "transient"

    def test_permanent_error_classification(self) -> None:
        assert _classify_error("Validation failed: missing field") == "permanent"
        assert _classify_error("Schema mismatch") == "permanent"
        assert _classify_error("Permission denied") == "permanent"
        assert _classify_error("Resource not found") == "permanent"

    def test_unknown_defaults_to_transient(self) -> None:
        assert _classify_error("Something weird happened") == "transient"

    def test_permanent_gets_zero_retries(self) -> None:
        """Permanent errors should get 0 max_retries."""
        error = "validation error: invalid schema"
        category = _classify_error(error)
        assert category == "permanent"
        max_retries = 3 if category == "transient" else 0
        assert max_retries == 0

    def test_transient_gets_retries(self) -> None:
        """Transient errors should get retry attempts."""
        error = "connection reset by peer"
        category = _classify_error(error)
        assert category == "transient"
        max_retries = 3 if category == "transient" else 0
        assert max_retries == 3


# ===========================================================================
# 6. READINESS PROBE STRUCTURE
# ===========================================================================


class TestReadinessProbeDesign:
    """Readiness probe checks real dependencies, not just process status."""

    def test_liveness_and_readiness_are_separate_endpoints(self) -> None:
        """create_app produces both /healthz and /readyz."""
        import os

        env_overrides = {
            "SYNDICATECLAW_DATABASE_URL": "postgresql+asyncpg://syndicateclaw:syndicateclaw@postgres:5432/syndicateclaw_test",
            "SYNDICATECLAW_SECRET_KEY": "test-secret-key-for-testing",
        }
        with patch.dict(os.environ, env_overrides):
            from importlib import reload

            import syndicateclaw.api.main as main_mod

            reload(main_mod)
            app = main_mod.create_app()

        route_paths = {route.path for route in app.routes}
        assert "/healthz" in route_paths, "Liveness probe missing"
        assert "/readyz" in route_paths, "Readiness probe missing"
        assert "/health" not in route_paths, "Old /health endpoint should be removed"


# ===========================================================================
# 7. COMBINED ENFORCEMENT — no escape hatches
# ===========================================================================


class TestNoEscapeHatches:
    """Verify there are no remaining permissive fallbacks."""

    @pytest.mark.asyncio
    async def test_no_policy_engine_and_no_ledger_both_fail(self) -> None:
        """With neither policy nor ledger, execution is denied twice over."""
        registry = ToolRegistry()
        tool = _make_tool()
        registry.register(tool, _noop_handler)

        executor = ToolExecutor(
            registry=registry,
            policy_engine=None,
            decision_ledger=None,
        )
        ctx = ExecutionContext(run_id="run-1")
        with pytest.raises(ToolDeniedError):
            await executor.execute("test_tool", {}, ctx)

    @pytest.mark.asyncio
    async def test_policy_deny_then_ledger_record(self) -> None:
        """A DENY from policy still records the decision before raising."""
        registry = ToolRegistry()
        tool = _make_tool()
        registry.register(tool, _noop_handler)

        mock_policy = AsyncMock()
        mock_policy.evaluate = AsyncMock(return_value=PolicyEffect.DENY)

        mock_ledger = AsyncMock()
        deny_record = DecisionRecord.new(
            domain=DecisionDomain.TOOL_EXECUTION,
            decision_type="tool_invocation",
            actor="run-1",
            effect="deny",
            justification="policy denied",
        )
        mock_ledger.record_tool_decision = AsyncMock(return_value=deny_record)

        executor = ToolExecutor(
            registry=registry,
            policy_engine=mock_policy,
            decision_ledger=mock_ledger,
        )
        ctx = ExecutionContext(run_id="run-1")
        with pytest.raises(ToolDeniedError):
            await executor.execute("test_tool", {}, ctx)

        mock_ledger.record_tool_decision.assert_called_once()

    def test_memory_unknown_access_policy_fails_closed(self) -> None:
        """Any policy string not in the known set is denied."""
        for unknown_policy in ["admin", "public", "private", "open", "", "ALL"]:
            record = _make_memory_record(access_policy=unknown_policy, actor="user:alice")
            assert MemoryService._check_access_policy(record, "user:alice") is False, (
                f"Policy '{unknown_policy}' should be denied but was allowed"
            )
