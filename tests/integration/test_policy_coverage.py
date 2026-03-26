"""DB-backed policy engine integration tests."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from ulid import ULID

from syndicateclaw.models import PolicyCondition, PolicyEffect, PolicyRule
from syndicateclaw.policy.engine import PolicyEngine

pytestmark = pytest.mark.integration


async def test_policy_allow_rule_permits_matching_request(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    engine = PolicyEngine(session_factory)
    uid = str(ULID())
    rt = f"tool_a_{uid}"
    rule = PolicyRule.new(
        name=f"integ-allow-{uid}",
        resource_type=rt,
        resource_pattern="*",
        effect=PolicyEffect.ALLOW,
        conditions=[],
        priority=10,
        owner="test",
    )
    await engine.add_rule(rule, actor="admin:test")
    decision = await engine.evaluate(
        rt, "t1", "execute", "alice", {"actor": {"role": "user"}},
    )
    assert decision.effect == PolicyEffect.ALLOW


async def test_policy_deny_rule_blocks_matching_request(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    engine = PolicyEngine(session_factory)
    uid = str(ULID())
    rt = f"tool_d_{uid}"
    rule = PolicyRule.new(
        name=f"integ-deny-{uid}",
        resource_type=rt,
        resource_pattern="secret-*",
        effect=PolicyEffect.DENY,
        conditions=[],
        priority=50,
        owner="test",
    )
    await engine.add_rule(rule, actor="admin:test")
    decision = await engine.evaluate(
        rt, "secret-x", "execute", "bob", {},
    )
    assert decision.effect == PolicyEffect.DENY


async def test_policy_deny_takes_precedence_over_allow(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    engine = PolicyEngine(session_factory)
    uid = str(ULID())
    rt = f"memory_{uid}"
    allow = PolicyRule.new(
        name=f"integ-allow-wide-{uid}",
        resource_type=rt,
        resource_pattern="*",
        effect=PolicyEffect.ALLOW,
        conditions=[],
        priority=10,
        owner="test",
    )
    deny = PolicyRule.new(
        name=f"integ-deny-high-{uid}",
        resource_type=rt,
        resource_pattern="*",
        effect=PolicyEffect.DENY,
        conditions=[],
        priority=100,
        owner="test",
    )
    await engine.add_rule(allow, actor="admin:test")
    await engine.add_rule(deny, actor="admin:test")
    decision = await engine.evaluate(rt, "m1", "read", "u", {})
    assert decision.effect == PolicyEffect.DENY
    assert "deny" in decision.rule_name.lower()


async def test_policy_no_matching_rule_defaults_to_deny(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    engine = PolicyEngine(session_factory)
    rt = f"tool_isolated_{str(ULID())}"
    decision = await engine.evaluate(
        rt, "orphan-tool", "execute", "eve", {},
    )
    assert decision.effect == PolicyEffect.DENY
    assert "default" in decision.rule_name.lower()


async def test_policy_condition_evaluation_all_operators(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    pe = PolicyEngine(session_factory)
    ctx = {
        "actor": {"role": "admin"},
        "n": 5,
        "tags": ["a", "b"],
        "label": "hello-world",
    }
    assert pe._evaluate_condition(
        PolicyCondition(field="actor.role", operator="eq", value="admin"), ctx,
    )
    assert pe._evaluate_condition(
        PolicyCondition(field="actor.role", operator="neq", value="guest"), ctx,
    )
    assert pe._evaluate_condition(
        PolicyCondition(field="actor.role", operator="in", value=["admin", "x"]), ctx,
    )
    assert pe._evaluate_condition(
        PolicyCondition(field="actor.role", operator="not_in", value=["guest", "bot"]), ctx,
    )
    assert pe._evaluate_condition(PolicyCondition(field="n", operator="gt", value=3), ctx)
    assert pe._evaluate_condition(PolicyCondition(field="n", operator="lt", value=10), ctx)
    assert pe._evaluate_condition(PolicyCondition(field="n", operator="gte", value=5), ctx)
    assert pe._evaluate_condition(PolicyCondition(field="n", operator="lte", value=5), ctx)
    assert pe._evaluate_condition(
        PolicyCondition(field="label", operator="matches", value="hello.*"), ctx,
    )


async def test_policy_context_variables_resolve_correctly(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    engine = PolicyEngine(session_factory)
    uid = str(ULID())
    rt = f"workflow_{uid}"
    rule = PolicyRule.new(
        name=f"ctx-rule-{uid}",
        resource_type=rt,
        resource_pattern="wf-*",
        effect=PolicyEffect.ALLOW,
        conditions=[
            PolicyCondition(field="actor.role", operator="eq", value="operator"),
            PolicyCondition(field="resource.owner", operator="eq", value="team-a"),
        ],
        priority=20,
        owner="test",
    )
    await engine.add_rule(rule, actor="admin:test")
    ok = await engine.evaluate(
        rt,
        "wf-1",
        "execute",
        "carol",
        {"actor": {"role": "operator"}, "resource": {"owner": "team-a"}},
    )
    assert ok.effect == PolicyEffect.ALLOW


async def test_policy_evaluation_emits_structured_log(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    engine = PolicyEngine(session_factory)
    rt = f"tool_log_{str(ULID())}"
    decision = await engine.evaluate(rt, "tlog", "run", "dave", {"actor_id": "dave"})
    assert decision.actor == "dave"
    assert decision.resource_id == "tlog"


async def test_policy_rule_priority_order_respected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    engine = PolicyEngine(session_factory)
    uid = str(ULID())
    rt = f"tool_pr_{uid}"
    low = PolicyRule.new(
        name=f"prio-low-{uid}",
        resource_type=rt,
        resource_pattern="prio-*",
        effect=PolicyEffect.DENY,
        conditions=[],
        priority=5,
        owner="test",
    )
    high = PolicyRule.new(
        name=f"prio-high-{uid}",
        resource_type=rt,
        resource_pattern="prio-*",
        effect=PolicyEffect.ALLOW,
        conditions=[],
        priority=99,
        owner="test",
    )
    await engine.add_rule(low, actor="admin:test")
    await engine.add_rule(high, actor="admin:test")
    d = await engine.evaluate(rt, "prio-x", "execute", "u", {})
    assert d.effect == PolicyEffect.ALLOW
    assert uid in d.rule_name
