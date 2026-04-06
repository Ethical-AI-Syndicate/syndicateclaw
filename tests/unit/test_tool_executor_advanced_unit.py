"""Advanced unit tests for tools/executor.py — ToolExecutor methods, ApprovalRequiredError,
enforce_response_limits, _check_policy paths, _record_decision, _capture_snapshot, _emit_audit."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from syndicateclaw.models import (
    ApprovalRequest,
    AuditEventType,
    PolicyEffect,
    Tool,
    ToolRiskLevel,
    ToolSandboxPolicy,
)
from syndicateclaw.tools.executor import (
    ApprovalRequiredError,
    SandboxViolationError,
    ToolExecutor,
    ToolNotFoundError,
    enforce_response_limits,
)

# ---------------------------------------------------------------------------
# ApprovalRequiredError
# ---------------------------------------------------------------------------


def test_approval_required_error_message() -> None:
    request = MagicMock(spec=ApprovalRequest)
    request.id = "req-1"
    err = ApprovalRequiredError("my-tool", request)
    assert "my-tool" in str(err)
    assert err.name == "my-tool"
    assert err.request is request


# ---------------------------------------------------------------------------
# enforce_response_limits
# ---------------------------------------------------------------------------


def test_enforce_response_limits_within_limit() -> None:
    policy = ToolSandboxPolicy(
        network_isolation=False,
        allowed_protocols=["https"],
        allowed_domains=[],
        max_request_bytes=1024,
        max_response_bytes=10000,
        subprocess_allowed=False,
        filesystem_read=False,
        filesystem_write=False,
    )
    enforce_response_limits("tool", {"result": "ok"}, policy)  # no raise


def test_enforce_response_limits_exceeds_raises() -> None:
    policy = ToolSandboxPolicy(
        network_isolation=False,
        allowed_protocols=["https"],
        allowed_domains=[],
        max_request_bytes=1024,
        max_response_bytes=5,
        subprocess_allowed=False,
        filesystem_read=False,
        filesystem_write=False,
    )
    with pytest.raises(SandboxViolationError, match="response payload exceeds limit"):
        enforce_response_limits("tool", {"result": "long output here"}, policy)


# ---------------------------------------------------------------------------
# Helpers for ToolExecutor tests
# ---------------------------------------------------------------------------


def _make_tool(
    *,
    name: str = "test-tool",
    timeout_seconds: int = 10,
    risk_level: ToolRiskLevel = ToolRiskLevel.LOW,
) -> Tool:
    tool = MagicMock(spec=Tool)
    tool.name = name
    tool.input_schema = {}
    tool.output_schema = {}
    tool.sandbox_policy = ToolSandboxPolicy(
        network_isolation=False,
        allowed_protocols=["https"],
        allowed_domains=[],
        max_request_bytes=1024 * 1024,
        max_response_bytes=1024 * 1024,
        subprocess_allowed=False,
        filesystem_read=False,
        filesystem_write=False,
    )
    tool.side_effects = []
    tool.timeout_seconds = timeout_seconds
    tool.risk_level = risk_level
    return tool


def _make_context(
    *, run_id: str = "run-1", node_id: str = "node-1", config: dict | None = None
) -> Any:
    from syndicateclaw.orchestrator.engine import ExecutionContext

    ctx = MagicMock(spec=ExecutionContext)
    ctx.run_id = run_id
    ctx.node_id = node_id
    ctx.config = config or {}
    return ctx


def _make_registry(tool: Tool | None = None) -> MagicMock:
    from syndicateclaw.tools.registry import ToolDefinition, ToolRegistry

    registry = MagicMock(spec=ToolRegistry)
    if tool is not None:
        reg_tool = MagicMock(spec=ToolDefinition)
        reg_tool.tool = tool
        reg_tool.handler = AsyncMock(return_value={"output": "result"})
        registry.get = MagicMock(return_value=reg_tool)
    else:
        registry.get = MagicMock(return_value=None)
    return registry


# ---------------------------------------------------------------------------
# ToolExecutor._policy_actor
# ---------------------------------------------------------------------------


def test_policy_actor_from_config() -> None:
    registry = _make_registry()
    executor = ToolExecutor(registry)
    ctx = _make_context(config={"actor": "user:alice"})
    assert executor._policy_actor(ctx) == "user:alice"


def test_policy_actor_defaults_to_run_id() -> None:
    registry = _make_registry()
    executor = ToolExecutor(registry)
    ctx = _make_context(run_id="run-42")
    assert executor._policy_actor(ctx) == "run-42"


# ---------------------------------------------------------------------------
# ToolExecutor._build_tool_policy_context
# ---------------------------------------------------------------------------


def test_build_policy_context_includes_extra_config() -> None:
    registry = _make_registry()
    executor = ToolExecutor(registry)
    tool = _make_tool()
    ctx = _make_context(config={"actor": "user:1", "custom_key": "custom_val"})
    result = executor._build_tool_policy_context("test-tool", tool, {}, ctx)
    assert result["custom_key"] == "custom_val"
    assert result["tool"] == "test-tool"


def test_build_policy_context_reserved_keys_not_overwritten() -> None:
    registry = _make_registry()
    executor = ToolExecutor(registry)
    tool = _make_tool()
    # "tool" is a reserved key — config value should NOT overwrite it
    ctx = _make_context(config={"tool": "injected-tool"})
    result = executor._build_tool_policy_context("actual-tool", tool, {}, ctx)
    assert result["tool"] == "actual-tool"


# ---------------------------------------------------------------------------
# ToolExecutor._check_policy
# ---------------------------------------------------------------------------


async def test_check_policy_no_engine_returns_deny() -> None:
    registry = _make_registry()
    executor = ToolExecutor(registry, policy_engine=None)
    ctx = _make_context()
    tool = _make_tool()
    result = await executor._check_policy("tool", {}, ctx, tool)
    assert result == PolicyEffect.DENY


async def test_check_policy_engine_no_evaluate_attr_returns_allow() -> None:
    registry = _make_registry()
    policy_engine = MagicMock()
    # Delete evaluate attr so hasattr returns False
    del policy_engine.evaluate
    executor = ToolExecutor(registry, policy_engine=policy_engine)
    ctx = _make_context()
    tool = _make_tool()
    result = await executor._check_policy("tool", {}, ctx, tool)
    assert result == PolicyEffect.ALLOW


async def test_check_policy_evaluate_raises_returns_deny() -> None:
    registry = _make_registry()
    policy_engine = AsyncMock()
    policy_engine.evaluate = AsyncMock(side_effect=RuntimeError("engine down"))
    executor = ToolExecutor(registry, policy_engine=policy_engine)
    ctx = _make_context()
    tool = _make_tool()
    result = await executor._check_policy("tool", {}, ctx, tool)
    assert result == PolicyEffect.DENY


async def test_check_policy_result_with_effect_attr() -> None:
    registry = _make_registry()
    policy_engine = AsyncMock()
    policy_result = MagicMock()
    policy_result.effect = PolicyEffect.ALLOW
    policy_engine.evaluate = AsyncMock(return_value=policy_result)
    executor = ToolExecutor(registry, policy_engine=policy_engine)
    ctx = _make_context()
    tool = _make_tool()
    result = await executor._check_policy("tool", {}, ctx, tool)
    assert result == PolicyEffect.ALLOW


async def test_check_policy_result_without_effect_attr() -> None:
    registry = _make_registry()
    policy_engine = AsyncMock()
    policy_engine.evaluate = AsyncMock(return_value=PolicyEffect.ALLOW)
    executor = ToolExecutor(registry, policy_engine=policy_engine)
    ctx = _make_context()
    tool = _make_tool()
    result = await executor._check_policy("tool", {}, ctx, tool)
    assert result == PolicyEffect.ALLOW


# ---------------------------------------------------------------------------
# ToolExecutor._record_decision
# ---------------------------------------------------------------------------


async def test_record_decision_no_ledger_returns_none() -> None:
    registry = _make_registry()
    executor = ToolExecutor(registry, decision_ledger=None)
    ctx = _make_context()
    result = await executor._record_decision("tool", {}, ctx, "allow", "ok", [])
    assert result is None


async def test_record_decision_ledger_exception_returns_none() -> None:
    registry = _make_registry()
    ledger = AsyncMock()
    ledger.record_tool_decision = AsyncMock(side_effect=RuntimeError("ledger down"))
    executor = ToolExecutor(registry, decision_ledger=ledger)
    ctx = _make_context()
    result = await executor._record_decision("tool", {}, ctx, "allow", "ok", [])
    assert result is None


async def test_record_decision_success() -> None:
    registry = _make_registry()
    ledger = AsyncMock()
    decision = MagicMock()
    decision.id = "dec-1"
    ledger.record_tool_decision = AsyncMock(return_value=decision)
    executor = ToolExecutor(registry, decision_ledger=ledger)
    ctx = _make_context()
    result = await executor._record_decision("tool", {}, ctx, "allow", "ok", [])
    assert result is decision


# ---------------------------------------------------------------------------
# ToolExecutor._capture_snapshot
# ---------------------------------------------------------------------------


async def test_capture_snapshot_no_store_skips() -> None:
    registry = _make_registry()
    executor = ToolExecutor(registry, snapshot_store=None)
    ctx = _make_context()
    await executor._capture_snapshot(ctx, "tool", {}, {})  # no error


async def test_capture_snapshot_with_store_calls_capture() -> None:
    registry = _make_registry()
    snapshot_store = AsyncMock()
    snapshot_store.capture = AsyncMock()
    executor = ToolExecutor(registry, snapshot_store=snapshot_store)
    ctx = _make_context()
    await executor._capture_snapshot(ctx, "tool", {"in": 1}, {"out": 2})
    snapshot_store.capture.assert_awaited_once()


async def test_capture_snapshot_exception_is_swallowed() -> None:
    registry = _make_registry()
    snapshot_store = AsyncMock()
    snapshot_store.capture = AsyncMock(side_effect=RuntimeError("store down"))
    executor = ToolExecutor(registry, snapshot_store=snapshot_store)
    ctx = _make_context()
    await executor._capture_snapshot(ctx, "tool", {}, {})  # no raise


# ---------------------------------------------------------------------------
# ToolExecutor._emit_audit
# ---------------------------------------------------------------------------


async def test_emit_audit_with_emit_method() -> None:
    registry = _make_registry()
    audit_service = AsyncMock()
    audit_service.emit = AsyncMock()
    # Make sure "record" is not set to avoid the else branch
    del audit_service.record
    executor = ToolExecutor(registry, audit_service=audit_service)

    record = MagicMock()
    record.tool_name = "tool"
    record.model_dump = MagicMock(return_value={})
    await executor._emit_audit(AuditEventType.TOOL_EXECUTION_COMPLETED, record)
    audit_service.emit.assert_awaited_once()


async def test_emit_audit_with_record_method() -> None:
    registry = _make_registry()
    audit_service = MagicMock()
    # No emit, only record
    del audit_service.emit
    audit_service.record = AsyncMock()
    executor = ToolExecutor(registry, audit_service=audit_service)

    record = MagicMock()
    record.tool_name = "tool"
    record.model_dump = MagicMock(return_value={})
    await executor._emit_audit(AuditEventType.TOOL_EXECUTION_COMPLETED, record)
    audit_service.record.assert_awaited_once()


async def test_emit_audit_emit_exception_swallowed() -> None:
    registry = _make_registry()
    audit_service = AsyncMock()
    audit_service.emit = AsyncMock(side_effect=RuntimeError("audit down"))
    executor = ToolExecutor(registry, audit_service=audit_service)

    record = MagicMock()
    record.tool_name = "tool"
    record.model_dump = MagicMock(return_value={})
    await executor._emit_audit(AuditEventType.TOOL_EXECUTION_FAILED, record)  # no raise


async def test_emit_audit_record_exception_swallowed() -> None:
    registry = _make_registry()
    audit_service = MagicMock()
    del audit_service.emit
    audit_service.record = AsyncMock(side_effect=RuntimeError("audit down"))
    executor = ToolExecutor(registry, audit_service=audit_service)

    record = MagicMock()
    record.tool_name = "tool"
    record.model_dump = MagicMock(return_value={})
    await executor._emit_audit(AuditEventType.TOOL_EXECUTION_FAILED, record)  # no raise


# ---------------------------------------------------------------------------
# ToolExecutor.execute — ToolNotFoundError
# ---------------------------------------------------------------------------


async def test_execute_tool_not_found_raises() -> None:
    registry = _make_registry(tool=None)
    executor = ToolExecutor(registry)
    ctx = _make_context()
    with pytest.raises(ToolNotFoundError):
        await executor.execute("missing-tool", {}, ctx)
