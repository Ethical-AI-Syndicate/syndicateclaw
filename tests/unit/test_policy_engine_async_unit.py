"""Unit tests for policy/engine.py async paths — evaluate, add_rule, update_rule, etc."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syndicateclaw.models import PolicyCondition, PolicyEffect, PolicyRule
from syndicateclaw.policy.engine import PolicyEngine, _resolve_field, _row_to_policy_rule

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session_factory() -> Any:
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_begin = AsyncMock()
    mock_begin.__aenter__ = AsyncMock(return_value=None)
    mock_begin.__aexit__ = AsyncMock(return_value=False)
    mock_session.begin = MagicMock(return_value=mock_begin)

    return MagicMock(return_value=mock_session)


def _make_rule_row(
    *,
    name: str = "test-rule",
    resource_pattern: str = "*",
    effect: str = "ALLOW",
    conditions: Any = None,
    priority: int = 10,
    enabled: bool = True,
) -> MagicMock:
    row = MagicMock()
    row.id = "rule-1"
    row.name = name
    row.resource_pattern = resource_pattern
    row.effect = effect
    row.conditions = conditions or []
    row.priority = priority
    row.enabled = enabled
    row.description = ""
    row.resource_type = "tool"
    row.owner = "system"
    row.created_at = datetime.now(UTC)
    row.updated_at = datetime.now(UTC)
    return row


# ---------------------------------------------------------------------------
# PolicyEngine.evaluate — ALLOW path
# ---------------------------------------------------------------------------


async def test_evaluate_allow_when_rule_matches() -> None:
    factory = _make_session_factory()
    rule_row = _make_rule_row(effect="ALLOW")

    with patch("syndicateclaw.policy.engine.PolicyRuleRepository") as mock_rule_repo_cls:
        mock_rule_repo = AsyncMock()
        mock_rule_repo.get_enabled_by_resource_type = AsyncMock(return_value=[rule_row])
        mock_rule_repo_cls.return_value = mock_rule_repo

        with patch("syndicateclaw.policy.engine.PolicyDecisionRepository") as mock_dec_repo_cls:
            mock_dec_repo = AsyncMock()
            mock_dec_repo.create = AsyncMock()
            mock_dec_repo_cls.return_value = mock_dec_repo

            with patch("syndicateclaw.policy.engine.AuditService") as mock_audit_cls:
                mock_audit_cls.return_value.emit = AsyncMock()

                with patch("syndicateclaw.policy.engine.record_policy_evaluation"):
                    engine = PolicyEngine(factory)
                    decision = await engine.evaluate(
                        resource_type="tool",
                        resource_id="my-tool",
                        action="execute",
                        actor="user:1",
                        context={},
                    )

    assert decision.effect == PolicyEffect.ALLOW
    assert decision.rule_name == "test-rule"


# ---------------------------------------------------------------------------
# PolicyEngine.evaluate — default DENY (no matching rules)
# ---------------------------------------------------------------------------


async def test_evaluate_default_deny_when_no_rules_match() -> None:
    factory = _make_session_factory()

    with patch("syndicateclaw.policy.engine.PolicyRuleRepository") as mock_rule_repo_cls:
        mock_rule_repo = AsyncMock()
        mock_rule_repo.get_enabled_by_resource_type = AsyncMock(return_value=[])
        mock_rule_repo_cls.return_value = mock_rule_repo

        with patch("syndicateclaw.policy.engine.PolicyDecisionRepository") as mock_dec_repo_cls:
            mock_dec_repo = AsyncMock()
            mock_dec_repo.create = AsyncMock()
            mock_dec_repo_cls.return_value = mock_dec_repo

            with patch("syndicateclaw.policy.engine.AuditService") as mock_audit_cls:
                mock_audit_cls.return_value.emit = AsyncMock()

                with patch("syndicateclaw.policy.engine.record_policy_evaluation"):
                    engine = PolicyEngine(factory)
                    decision = await engine.evaluate(
                        resource_type="tool",
                        resource_id="unknown-tool",
                        action="execute",
                        actor="user:1",
                        context={},
                    )

    assert decision.effect == PolicyEffect.DENY
    assert decision.rule_name == "default_deny"


# ---------------------------------------------------------------------------
# PolicyEngine.evaluate — rule with conditions (dict and PolicyCondition)
# ---------------------------------------------------------------------------


async def test_evaluate_condition_dict_match() -> None:
    factory = _make_session_factory()
    rule_row = _make_rule_row(
        resource_pattern="my-*",
        effect="ALLOW",
        conditions=[{"field": "env", "operator": "eq", "value": "prod"}],
    )

    with patch("syndicateclaw.policy.engine.PolicyRuleRepository") as mock_rule_repo_cls:
        mock_rule_repo = AsyncMock()
        mock_rule_repo.get_enabled_by_resource_type = AsyncMock(return_value=[rule_row])
        mock_rule_repo_cls.return_value = mock_rule_repo

        with patch("syndicateclaw.policy.engine.PolicyDecisionRepository") as mock_dec_repo_cls:
            mock_dec_repo = AsyncMock()
            mock_dec_repo.create = AsyncMock()
            mock_dec_repo_cls.return_value = mock_dec_repo

            with patch("syndicateclaw.policy.engine.AuditService") as mock_audit_cls:
                mock_audit_cls.return_value.emit = AsyncMock()

                with patch("syndicateclaw.policy.engine.record_policy_evaluation"):
                    engine = PolicyEngine(factory)
                    decision = await engine.evaluate(
                        resource_type="tool",
                        resource_id="my-tool",
                        action="execute",
                        actor="user:1",
                        context={"env": "prod"},
                    )

    assert decision.effect == PolicyEffect.ALLOW


async def test_evaluate_condition_no_match_skips_to_default_deny() -> None:
    factory = _make_session_factory()
    rule_row = _make_rule_row(
        resource_pattern="*",
        effect="ALLOW",
        conditions=[{"field": "env", "operator": "eq", "value": "prod"}],
    )

    with patch("syndicateclaw.policy.engine.PolicyRuleRepository") as mock_rule_repo_cls:
        mock_rule_repo = AsyncMock()
        mock_rule_repo.get_enabled_by_resource_type = AsyncMock(return_value=[rule_row])
        mock_rule_repo_cls.return_value = mock_rule_repo

        with patch("syndicateclaw.policy.engine.PolicyDecisionRepository") as mock_dec_repo_cls:
            mock_dec_repo = AsyncMock()
            mock_dec_repo.create = AsyncMock()
            mock_dec_repo_cls.return_value = mock_dec_repo

            with patch("syndicateclaw.policy.engine.AuditService") as mock_audit_cls:
                mock_audit_cls.return_value.emit = AsyncMock()

                with patch("syndicateclaw.policy.engine.record_policy_evaluation"):
                    engine = PolicyEngine(factory)
                    decision = await engine.evaluate(
                        resource_type="tool",
                        resource_id="my-tool",
                        action="execute",
                        actor="user:1",
                        context={"env": "staging"},  # doesn't match "prod"
                    )

    assert decision.effect == PolicyEffect.DENY
    assert decision.rule_name == "default_deny"


async def test_evaluate_condition_as_policy_condition_object() -> None:
    factory = _make_session_factory()
    cond = PolicyCondition(field="role", operator="eq", value="admin")
    rule_row = _make_rule_row(effect="ALLOW", conditions=[cond])

    with patch("syndicateclaw.policy.engine.PolicyRuleRepository") as mock_rule_repo_cls:
        mock_rule_repo = AsyncMock()
        mock_rule_repo.get_enabled_by_resource_type = AsyncMock(return_value=[rule_row])
        mock_rule_repo_cls.return_value = mock_rule_repo

        with patch("syndicateclaw.policy.engine.PolicyDecisionRepository") as mock_dec_repo_cls:
            mock_dec_repo = AsyncMock()
            mock_dec_repo.create = AsyncMock()
            mock_dec_repo_cls.return_value = mock_dec_repo

            with patch("syndicateclaw.policy.engine.AuditService") as mock_audit_cls:
                mock_audit_cls.return_value.emit = AsyncMock()

                with patch("syndicateclaw.policy.engine.record_policy_evaluation"):
                    engine = PolicyEngine(factory)
                    decision = await engine.evaluate(
                        resource_type="tool",
                        resource_id="my-tool",
                        action="execute",
                        actor="user:1",
                        context={"role": "admin"},
                    )

    assert decision.effect == PolicyEffect.ALLOW


# ---------------------------------------------------------------------------
# PolicyEngine.evaluate — exception path (fail-closed DENY)
# ---------------------------------------------------------------------------


async def test_evaluate_exception_returns_fail_closed_deny() -> None:
    factory = _make_session_factory()

    with patch("syndicateclaw.policy.engine.PolicyRuleRepository") as mock_rule_repo_cls:
        mock_rule_repo = AsyncMock()
        mock_rule_repo.get_enabled_by_resource_type = AsyncMock(
            side_effect=RuntimeError("db crash")
        )
        mock_rule_repo_cls.return_value = mock_rule_repo

        with patch("syndicateclaw.policy.engine.AuditService") as mock_audit_cls:
            mock_audit_cls.return_value.emit = AsyncMock()

            with patch("syndicateclaw.policy.engine.record_policy_evaluation"):
                engine = PolicyEngine(factory)
                decision = await engine.evaluate(
                    resource_type="tool",
                    resource_id="my-tool",
                    action="execute",
                    actor="user:1",
                    context={},
                )

    assert decision.effect == PolicyEffect.DENY
    assert decision.rule_name == "evaluation_error"
    assert "fail-closed" in decision.reason


# ---------------------------------------------------------------------------
# PolicyEngine.add_rule
# ---------------------------------------------------------------------------


async def test_add_rule_persists_and_returns_rule() -> None:
    factory = _make_session_factory()
    rule = PolicyRule.new(
        name="new-rule",
        resource_type="tool",
        resource_pattern="*",
        effect=PolicyEffect.ALLOW,
        conditions=[],
        priority=5,
        owner="system",
    )

    with patch("syndicateclaw.policy.engine.PolicyRuleRepository") as mock_repo_cls:
        mock_repo = AsyncMock()
        mock_repo.create = AsyncMock()
        mock_repo_cls.return_value = mock_repo

        with patch("syndicateclaw.policy.engine.AuditService") as mock_audit_cls:
            mock_audit_cls.return_value.emit = AsyncMock()

            engine = PolicyEngine(factory)
            result = await engine.add_rule(rule, actor="admin:1")

    assert result is rule
    mock_repo.create.assert_awaited_once()


# ---------------------------------------------------------------------------
# PolicyEngine.update_rule
# ---------------------------------------------------------------------------


async def test_update_rule_not_found_raises() -> None:
    factory = _make_session_factory()

    with patch("syndicateclaw.policy.engine.PolicyRuleRepository") as mock_repo_cls:
        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=None)
        mock_repo_cls.return_value = mock_repo

        engine = PolicyEngine(factory)
        with pytest.raises(ValueError, match="not found"):
            await engine.update_rule("missing", {"priority": 99}, actor="admin:1")


async def test_update_rule_happy_path() -> None:
    factory = _make_session_factory()
    row = _make_rule_row()

    with patch("syndicateclaw.policy.engine.PolicyRuleRepository") as mock_repo_cls:
        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=row)
        mock_repo.update = AsyncMock(return_value=row)
        mock_repo_cls.return_value = mock_repo

        with patch("syndicateclaw.policy.engine.AuditService") as mock_audit_cls:
            mock_audit_cls.return_value.emit = AsyncMock()

            engine = PolicyEngine(factory)
            result = await engine.update_rule("rule-1", {"priority": 99}, actor="admin:1")

    assert result is not None


async def test_update_rule_condition_and_effect_serialization() -> None:
    factory = _make_session_factory()
    row = _make_rule_row()

    with patch("syndicateclaw.policy.engine.PolicyRuleRepository") as mock_repo_cls:
        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=row)
        mock_repo.update = AsyncMock(return_value=row)
        mock_repo_cls.return_value = mock_repo

        with patch("syndicateclaw.policy.engine.AuditService") as mock_audit_cls:
            mock_audit_cls.return_value.emit = AsyncMock()

            engine = PolicyEngine(factory)
            cond = PolicyCondition(field="x", operator="eq", value="y")
            await engine.update_rule(
                "rule-1",
                {"conditions": [cond], "effect": PolicyEffect.DENY},
                actor="admin:1",
            )

    # conditions converted to dict, effect to string
    assert row.conditions == [cond.model_dump()]
    assert row.effect == PolicyEffect.DENY.value


# ---------------------------------------------------------------------------
# PolicyEngine.delete_rule
# ---------------------------------------------------------------------------


async def test_delete_rule_disables_rule() -> None:
    factory = _make_session_factory()
    row = _make_rule_row(enabled=True)

    with patch("syndicateclaw.policy.engine.PolicyRuleRepository") as mock_repo_cls:
        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=row)
        mock_repo.update = AsyncMock(return_value=row)
        mock_repo_cls.return_value = mock_repo

        with patch("syndicateclaw.policy.engine.AuditService") as mock_audit_cls:
            mock_audit_cls.return_value.emit = AsyncMock()

            engine = PolicyEngine(factory)
            await engine.delete_rule("rule-1", actor="admin:1")

    assert row.enabled is False


async def test_delete_rule_not_found_raises() -> None:
    factory = _make_session_factory()

    with patch("syndicateclaw.policy.engine.PolicyRuleRepository") as mock_repo_cls:
        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=None)
        mock_repo_cls.return_value = mock_repo

        engine = PolicyEngine(factory)
        with pytest.raises(ValueError, match="not found"):
            await engine.delete_rule("missing", actor="admin:1")


# ---------------------------------------------------------------------------
# PolicyEngine.list_rules
# ---------------------------------------------------------------------------


async def test_list_rules_unfiltered() -> None:
    factory = _make_session_factory()
    row = _make_rule_row()

    with patch("syndicateclaw.policy.engine.PolicyRuleRepository") as mock_repo_cls:
        mock_repo = AsyncMock()
        mock_repo.list = AsyncMock(return_value=[row])
        mock_repo_cls.return_value = mock_repo

        engine = PolicyEngine(factory)
        rules = await engine.list_rules()

    assert len(rules) == 1
    mock_repo.list.assert_awaited_once()


async def test_list_rules_filtered_by_resource_type() -> None:
    factory = _make_session_factory()
    row = _make_rule_row()

    with patch("syndicateclaw.policy.engine.PolicyRuleRepository") as mock_repo_cls:
        mock_repo = AsyncMock()
        mock_repo.get_enabled_by_resource_type = AsyncMock(return_value=[row])
        mock_repo_cls.return_value = mock_repo

        engine = PolicyEngine(factory)
        rules = await engine.list_rules(resource_type="tool")

    mock_repo.get_enabled_by_resource_type.assert_awaited_once_with("tool")
    assert len(rules) == 1


# ---------------------------------------------------------------------------
# _resolve_field helper
# ---------------------------------------------------------------------------


def test_resolve_field_nested() -> None:
    assert _resolve_field({"a": {"b": "c"}}, "a.b") == "c"


def test_resolve_field_missing_key_returns_none() -> None:
    assert _resolve_field({"a": 1}, "b") is None


def test_resolve_field_non_dict_intermediate_returns_none() -> None:
    assert _resolve_field({"a": "not-a-dict"}, "a.b") is None


# ---------------------------------------------------------------------------
# _row_to_policy_rule helper — conditions normalization paths
# ---------------------------------------------------------------------------


def test_row_to_policy_rule_with_dict_conditions_that_is_single_condition() -> None:
    row = _make_rule_row(conditions={"field": "x", "operator": "eq", "value": "y"})
    result = _row_to_policy_rule(row)
    assert isinstance(result.conditions, list)


def test_row_to_policy_rule_with_dict_conditions_other_shape() -> None:
    row = _make_rule_row(conditions={"some": "other"})
    result = _row_to_policy_rule(row)
    assert result.conditions == []


def test_row_to_policy_rule_with_none_conditions() -> None:
    row = _make_rule_row(conditions=None)
    result = _row_to_policy_rule(row)
    assert result.conditions == []


def test_row_to_policy_rule_effect_as_enum() -> None:
    row = _make_rule_row(effect=PolicyEffect.ALLOW)
    result = _row_to_policy_rule(row)
    assert result.effect == PolicyEffect.ALLOW
