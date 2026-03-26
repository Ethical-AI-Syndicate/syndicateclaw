"""Policy engine must fail closed on any evaluation error."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from syndicateclaw.db.repository import PolicyRuleRepository
from syndicateclaw.models import PolicyEffect
from syndicateclaw.policy.engine import PolicyEngine


@pytest.mark.asyncio
async def test_policy_engine_exception_defaults_to_deny(monkeypatch: pytest.MonkeyPatch) -> None:
    """Policy evaluation errors MUST fail closed — never propagate or allow."""
    session = MagicMock()
    begin_ctx = AsyncMock()
    begin_ctx.__aenter__ = AsyncMock(return_value=None)
    begin_ctx.__aexit__ = AsyncMock(return_value=None)
    session.begin = MagicMock(return_value=begin_ctx)

    sess_ctx = AsyncMock()
    sess_ctx.__aenter__ = AsyncMock(return_value=session)
    sess_ctx.__aexit__ = AsyncMock(return_value=None)

    factory = MagicMock(return_value=sess_ctx)
    engine = PolicyEngine(factory)
    monkeypatch.setattr(engine, "_emit_audit", AsyncMock())

    async def boom(self: PolicyRuleRepository, resource_type: str) -> list:
        raise RuntimeError("simulated policy storage failure")

    monkeypatch.setattr(PolicyRuleRepository, "get_enabled_by_resource_type", boom)

    decision = await engine.evaluate("tool", "t1", "execute", "actor", {})

    assert decision.effect == PolicyEffect.DENY
    assert "fail-closed" in decision.reason
    engine._emit_audit.assert_called()
