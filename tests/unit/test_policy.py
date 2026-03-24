from __future__ import annotations

from unittest.mock import MagicMock

from syndicateclaw.models import PolicyCondition
from syndicateclaw.policy.engine import PolicyEngine


def _make_engine() -> PolicyEngine:
    """Create a PolicyEngine with a mock session_factory (DB not used for condition eval)."""
    mock_session_factory = MagicMock()
    return PolicyEngine(mock_session_factory)


class TestPolicyConditionEvaluation:
    def test_policy_condition_eq(self):
        engine = _make_engine()
        cond = PolicyCondition(field="risk_level", operator="eq", value="LOW")
        assert engine._evaluate_condition(cond, {"risk_level": "LOW"}) is True
        assert engine._evaluate_condition(cond, {"risk_level": "HIGH"}) is False

    def test_policy_condition_neq(self):
        engine = _make_engine()
        cond = PolicyCondition(field="risk_level", operator="neq", value="CRITICAL")
        assert engine._evaluate_condition(cond, {"risk_level": "LOW"}) is True
        assert engine._evaluate_condition(cond, {"risk_level": "CRITICAL"}) is False

    def test_policy_condition_in(self):
        engine = _make_engine()
        cond = PolicyCondition(field="status", operator="in", value=["ACTIVE", "PENDING"])
        assert engine._evaluate_condition(cond, {"status": "ACTIVE"}) is True
        assert engine._evaluate_condition(cond, {"status": "DELETED"}) is False

    def test_policy_condition_gt_lt(self):
        engine = _make_engine()
        gt_cond = PolicyCondition(field="count", operator="gt", value=5)
        lt_cond = PolicyCondition(field="count", operator="lt", value=10)

        assert engine._evaluate_condition(gt_cond, {"count": 10}) is True
        assert engine._evaluate_condition(gt_cond, {"count": 3}) is False
        assert engine._evaluate_condition(lt_cond, {"count": 5}) is True
        assert engine._evaluate_condition(lt_cond, {"count": 15}) is False

    def test_policy_condition_matches_regex(self):
        engine = _make_engine()
        cond = PolicyCondition(field="name", operator="matches", value=r"^test-.*")
        assert engine._evaluate_condition(cond, {"name": "test-tool-alpha"}) is True
        assert engine._evaluate_condition(cond, {"name": "prod-tool"}) is False

    def test_policy_condition_nested_field(self):
        engine = _make_engine()
        cond = PolicyCondition(field="meta.env", operator="eq", value="staging")
        assert engine._evaluate_condition(cond, {"meta": {"env": "staging"}}) is True
        assert engine._evaluate_condition(cond, {"meta": {"env": "prod"}}) is False

    def test_policy_condition_missing_field_returns_false(self):
        engine = _make_engine()
        cond = PolicyCondition(field="nonexistent", operator="eq", value="x")
        assert engine._evaluate_condition(cond, {}) is False

    def test_policy_condition_unknown_operator(self):
        engine = _make_engine()
        cond = PolicyCondition(field="x", operator="BOGUS", value="y")
        assert engine._evaluate_condition(cond, {"x": "y"}) is False
