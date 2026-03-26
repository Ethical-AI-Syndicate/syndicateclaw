"""DB-backed tool executor integration tests."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from ulid import ULID

from syndicateclaw.audit.ledger import DecisionLedger
from syndicateclaw.audit.service import AuditService
from syndicateclaw.models import PolicyEffect, PolicyRule, Tool, ToolRiskLevel
from syndicateclaw.orchestrator.engine import ExecutionContext
from syndicateclaw.policy.engine import PolicyEngine
from syndicateclaw.tools.executor import ToolDeniedError, ToolExecutor, ToolTimeoutError
from syndicateclaw.tools.registry import ToolRegistry

pytestmark = pytest.mark.integration


async def _echo_handler(data: dict[str, Any]) -> dict[str, Any]:
    return {"echo": data}


async def test_tool_executor_policy_deny_blocks_execution(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    uid = str(ULID())
    pe = PolicyEngine(session_factory)
    await pe.add_rule(
        PolicyRule.new(
            name=f"deny-tool-{uid}",
            resource_type="tool",
            resource_pattern=f"block-{uid}*",
            effect=PolicyEffect.DENY,
            conditions=[],
            priority=100,
            owner="test",
        ),
        actor="admin:test",
    )
    tool_name = f"block-{uid}"
    reg = ToolRegistry()
    reg.register(
        Tool.new(name=tool_name, version="1.0", owner="o", risk_level=ToolRiskLevel.LOW),
        _echo_handler,
    )
    ledger = DecisionLedger(session_factory)
    ex = ToolExecutor(reg, policy_engine=pe, decision_ledger=ledger)
    ctx = ExecutionContext(run_id=str(ULID()), node_id="n1", config={"actor": "alice"})
    with pytest.raises(ToolDeniedError):
        await ex.execute(tool_name, {}, ctx)


async def test_tool_executor_timeout_raises_correctly(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    uid = str(ULID())
    pe = PolicyEngine(session_factory)
    await pe.add_rule(
        PolicyRule.new(
            name=f"allow-{uid}",
            resource_type="tool",
            resource_pattern=f"slow-{uid}*",
            effect=PolicyEffect.ALLOW,
            conditions=[],
            priority=10,
            owner="test",
        ),
        actor="admin:test",
    )

    async def slow(_data: dict[str, Any]) -> dict[str, Any]:
        await asyncio.sleep(5)
        return {}

    tool_name = f"slow-{uid}"
    reg = ToolRegistry()
    reg.register(
        Tool.new(
            name=tool_name,
            version="1.0",
            owner="o",
            risk_level=ToolRiskLevel.LOW,
            timeout_seconds=1,
        ),
        slow,
    )
    ledger = DecisionLedger(session_factory)
    audit = AuditService(session_factory)
    ex = ToolExecutor(
        reg,
        policy_engine=pe,
        decision_ledger=ledger,
        audit_service=audit,
    )
    ctx = ExecutionContext(run_id=str(ULID()), node_id="n1", config={"actor": "bob"})
    with pytest.raises(ToolTimeoutError):
        await ex.execute(tool_name, {}, ctx)


async def test_tool_executor_audit_decision_ledger_entry_created(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    uid = str(ULID())
    pe = PolicyEngine(session_factory)
    await pe.add_rule(
        PolicyRule.new(
            name=f"allow-exec-{uid}",
            resource_type="tool",
            resource_pattern=f"ok-{uid}*",
            effect=PolicyEffect.ALLOW,
            conditions=[],
            priority=10,
            owner="test",
        ),
        actor="admin:test",
    )
    tool_name = f"ok-{uid}"
    reg = ToolRegistry()
    reg.register(
        Tool.new(name=tool_name, version="1.0", owner="o", risk_level=ToolRiskLevel.LOW),
        _echo_handler,
    )
    ledger = DecisionLedger(session_factory)
    ex = ToolExecutor(reg, policy_engine=pe, decision_ledger=ledger)
    ctx = ExecutionContext(run_id=str(ULID()), node_id="n1", config={"actor": "carol"})
    await ex.execute(tool_name, {"x": 1}, ctx)
    decisions = await ledger.get_run_decisions(ctx.run_id)
    assert any(d.inputs.get("tool_name") == tool_name for d in decisions)
