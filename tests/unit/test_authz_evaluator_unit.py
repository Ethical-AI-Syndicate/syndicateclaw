"""Unit tests for authz/evaluator.py — dataclass methods, scope containment,
RBACEvaluator paths, TeamContextValidator, resolve_principal_id."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from syndicateclaw.authz.evaluator import (
    Decision,
    DenyReason,
    MatchedAssignment,
    MatchedDeny,
    RBACEvaluator,
    TeamContextValidator,
    _elapsed_us,
    _scope_contains,
    resolve_principal_id,
)
from syndicateclaw.authz.route_registry import Scope

# ---------------------------------------------------------------------------
# MatchedAssignment.to_dict
# ---------------------------------------------------------------------------


def test_matched_assignment_to_dict() -> None:
    ma = MatchedAssignment(
        role_id="role-1",
        role_name="admin",
        scope_type="TENANT",
        scope_id="t-1",
        source="direct",
    )
    d = ma.to_dict()
    assert d["role_id"] == "role-1"
    assert d["role_name"] == "admin"
    assert d["scope_type"] == "TENANT"
    assert d["scope_id"] == "t-1"
    assert d["source"] == "direct"


# ---------------------------------------------------------------------------
# MatchedDeny.to_dict
# ---------------------------------------------------------------------------


def test_matched_deny_to_dict() -> None:
    md = MatchedDeny(
        deny_id="deny-1",
        permission="tool:execute",
        scope_type="NAMESPACE",
        scope_id="ns-1",
        reason="security policy",
    )
    d = md.to_dict()
    assert d["deny_id"] == "deny-1"
    assert d["permission"] == "tool:execute"
    assert d["scope_type"] == "NAMESPACE"
    assert d["scope_id"] == "ns-1"
    assert d["reason"] == "security policy"


# ---------------------------------------------------------------------------
# _scope_contains
# ---------------------------------------------------------------------------


def test_scope_contains_platform_contains_all() -> None:
    outer = Scope(scope_type="PLATFORM", scope_id="*")
    inner = Scope(scope_type="NAMESPACE", scope_id="ns-1")
    assert _scope_contains(outer, inner) is True


def test_scope_contains_unknown_outer_type_returns_false() -> None:
    outer = Scope(scope_type="UNKNOWN", scope_id="x")
    inner = Scope(scope_type="NAMESPACE", scope_id="ns-1")
    assert _scope_contains(outer, inner) is False


def test_scope_contains_unknown_inner_type_returns_false() -> None:
    outer = Scope(scope_type="TENANT", scope_id="t-1")
    inner = Scope(scope_type="UNKNOWN", scope_id="x")
    assert _scope_contains(outer, inner) is False


def test_scope_contains_same_type_same_id() -> None:
    scope = Scope(scope_type="TEAM", scope_id="team-1")
    assert _scope_contains(scope, scope) is True


def test_scope_contains_same_type_different_id() -> None:
    outer = Scope(scope_type="TEAM", scope_id="team-1")
    inner = Scope(scope_type="TEAM", scope_id="team-2")
    assert _scope_contains(outer, inner) is False


def test_scope_contains_outer_narrower_than_inner_returns_false() -> None:
    outer = Scope(scope_type="NAMESPACE", scope_id="ns-1")
    inner = Scope(scope_type="TENANT", scope_id="t-1")
    assert _scope_contains(outer, inner) is False


def test_scope_contains_tenant_contains_namespace() -> None:
    outer = Scope(scope_type="TENANT", scope_id="t-1")
    inner = Scope(scope_type="NAMESPACE", scope_id="ns-1")
    assert _scope_contains(outer, inner) is True


# ---------------------------------------------------------------------------
# _elapsed_us
# ---------------------------------------------------------------------------


def test_elapsed_us_returns_integer() -> None:
    import time
    t0 = time.monotonic()
    result = _elapsed_us(t0)
    assert isinstance(result, int)
    assert result >= 0


# ---------------------------------------------------------------------------
# RBACEvaluator helpers
# ---------------------------------------------------------------------------


def _make_session(fetchall_return=None):
    session = AsyncMock()
    result = MagicMock()
    result.fetchall.return_value = fetchall_return or []
    session.execute = AsyncMock(return_value=result)
    return session


# ---------------------------------------------------------------------------
# RBACEvaluator.evaluate — no principal
# ---------------------------------------------------------------------------


async def test_evaluate_no_principal_returns_deny() -> None:
    session = _make_session()
    ev = RBACEvaluator(session)
    result = await ev.evaluate(None, "tool:execute", None)
    assert result.decision == Decision.DENY
    assert result.deny_reason == DenyReason.NO_PRINCIPAL


# ---------------------------------------------------------------------------
# RBACEvaluator.evaluate — resource_scope=None uses platform
# ---------------------------------------------------------------------------


async def test_evaluate_none_resource_scope_uses_platform() -> None:
    session = AsyncMock()
    empty_result = MagicMock()
    empty_result.fetchall.return_value = []
    session.execute = AsyncMock(return_value=empty_result)

    ev = RBACEvaluator(session)
    # No denies, no assignments — should return NO_MATCHING_GRANT not crash
    result = await ev.evaluate("user:1", "tool:execute", None)
    assert result.decision == Decision.DENY
    assert result.deny_reason == DenyReason.NO_MATCHING_GRANT


# ---------------------------------------------------------------------------
# RBACEvaluator.evaluate — explicit deny
# ---------------------------------------------------------------------------


async def test_evaluate_explicit_deny() -> None:
    # Row format: deny_id, permission, scope_type, scope_id, reason, expires_at
    deny_row = ("deny-1", "tool:execute", "PLATFORM", "*", "blocked", None)
    session = AsyncMock()
    deny_result = MagicMock()
    deny_result.fetchall.return_value = [deny_row]
    session.execute = AsyncMock(return_value=deny_result)

    ev = RBACEvaluator(session)
    resource_scope = Scope(scope_type="PLATFORM", scope_id="*")
    result = await ev.evaluate("user:1", "tool:execute", resource_scope)
    assert result.decision == Decision.DENY
    assert result.deny_reason == DenyReason.EXPLICIT_DENY
    assert len(result.matched_denies) == 1


async def test_evaluate_expired_deny_ignored() -> None:
    past = MagicMock()
    past.timestamp.return_value = 0.0  # expired

    deny_row = ("deny-1", "tool:execute", "PLATFORM", "*", "old", past)

    session = AsyncMock()
    deny_result = MagicMock()
    deny_result.fetchall.return_value = [deny_row]
    asgn_result = MagicMock()
    asgn_result.fetchall.return_value = []
    session.execute = AsyncMock(side_effect=[deny_result, asgn_result])

    ev = RBACEvaluator(session)
    resource_scope = Scope(scope_type="PLATFORM", scope_id="*")
    result = await ev.evaluate("user:1", "tool:execute", resource_scope)
    # Deny is expired, so skip it; no assignments → NO_MATCHING_GRANT
    assert result.decision == Decision.DENY
    assert result.deny_reason == DenyReason.NO_MATCHING_GRANT


# ---------------------------------------------------------------------------
# RBACEvaluator.evaluate — no matching grant
# ---------------------------------------------------------------------------


async def test_evaluate_no_matching_grant() -> None:
    session = AsyncMock()
    empty_result = MagicMock()
    empty_result.fetchall.return_value = []
    session.execute = AsyncMock(return_value=empty_result)

    ev = RBACEvaluator(session)
    result = await ev.evaluate("user:1", "tool:execute", Scope.platform())
    assert result.decision == Decision.DENY
    assert result.deny_reason == DenyReason.NO_MATCHING_GRANT


# ---------------------------------------------------------------------------
# RBACEvaluator.evaluate — expired assignment only
# ---------------------------------------------------------------------------


async def test_evaluate_expired_assignments_only() -> None:
    # First execute call = denies (empty), second = assignments, third = role perms
    session = AsyncMock()
    results = []

    # First call: deny check — empty
    deny_result = MagicMock()
    deny_result.fetchall.return_value = []
    results.append(deny_result)

    # Second call: assignments — one expired assignment
    past = MagicMock()
    past.timestamp.return_value = 0.0  # in past
    asgn_row = ("asgn-1", "role-1", "viewer", None, None, "PLATFORM", "*", "direct", past)
    asgn_result = MagicMock()
    asgn_result.fetchall.return_value = [asgn_row]
    results.append(asgn_result)

    session.execute = AsyncMock(side_effect=results)
    ev = RBACEvaluator(session)
    result = await ev.evaluate("user:1", "tool:execute", Scope.platform())
    assert result.decision == Decision.DENY
    assert result.deny_reason == DenyReason.EXPIRED_ASSIGNMENTS_ONLY


# ---------------------------------------------------------------------------
# RBACEvaluator.evaluate — ALLOW path
# ---------------------------------------------------------------------------


async def test_evaluate_allow_when_permission_granted() -> None:
    session = AsyncMock()
    results = []

    # deny check — empty
    deny_result = MagicMock()
    deny_result.fetchall.return_value = []
    results.append(deny_result)

    # assignments — one valid assignment
    future = MagicMock()
    future.timestamp.return_value = 9999999999.0
    asgn_row = ("asgn-1", "role-1", "admin", None, None, "PLATFORM", "*", "direct", future)
    asgn_result = MagicMock()
    asgn_result.fetchall.return_value = [asgn_row]
    results.append(asgn_result)

    # role permissions expansion — returns "tool:execute"
    perm_result = MagicMock()
    perm_result.fetchall.return_value = [("tool:execute",), ("tool:read",)]
    results.append(perm_result)

    session.execute = AsyncMock(side_effect=results)
    ev = RBACEvaluator(session)
    result = await ev.evaluate("user:1", "tool:execute", Scope.platform())
    assert result.decision == Decision.ALLOW
    assert result.permission_source is not None
    assert len(result.matched_assignments) == 1


# ---------------------------------------------------------------------------
# RBACEvaluator._resolve_assignments — cache hit
# ---------------------------------------------------------------------------


async def test_resolve_assignments_cache_hit() -> None:
    session = _make_session()
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(side_effect=[b"1", b'[{"role_id": "r1"}]'])

    ev = RBACEvaluator(session, redis_client=mock_redis)
    assignments, cache_hit = await ev._resolve_assignments("user:1")
    assert cache_hit is True
    assert assignments[0]["role_id"] == "r1"
    session.execute.assert_not_called()


async def test_resolve_assignments_cache_miss_no_version() -> None:
    session = _make_session(fetchall_return=[])
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.set = AsyncMock()

    ev = RBACEvaluator(session, redis_client=mock_redis)
    assignments, cache_hit = await ev._resolve_assignments("user:1")
    assert cache_hit is False


async def test_resolve_assignments_cache_miss_no_data() -> None:
    session = _make_session(fetchall_return=[])
    mock_redis = AsyncMock()
    # version exists but data missing
    mock_redis.get = AsyncMock(side_effect=[b"1", None])
    mock_redis.set = AsyncMock()

    ev = RBACEvaluator(session, redis_client=mock_redis)
    assignments, cache_hit = await ev._resolve_assignments("user:1")
    assert cache_hit is False


async def test_resolve_assignments_cache_get_exception_returns_none() -> None:
    session = _make_session(fetchall_return=[])
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(side_effect=RuntimeError("redis down"))
    mock_redis.set = AsyncMock()

    ev = RBACEvaluator(session, redis_client=mock_redis)
    assignments, cache_hit = await ev._resolve_assignments("user:1")
    assert cache_hit is False


# ---------------------------------------------------------------------------
# RBACEvaluator._cache_set — Redis paths
# ---------------------------------------------------------------------------


async def test_cache_set_creates_version_when_missing() -> None:
    session = _make_session()
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)  # no version yet
    mock_redis.set = AsyncMock()

    ev = RBACEvaluator(session, redis_client=mock_redis)
    await ev._cache_set("user:1", [{"role_id": "r1", "expired": False}])
    mock_redis.set.assert_called()


async def test_cache_set_uses_existing_version() -> None:
    session = _make_session()
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=b"2")
    mock_redis.set = AsyncMock()

    ev = RBACEvaluator(session, redis_client=mock_redis)
    await ev._cache_set("user:1", [{"role_id": "r1"}])
    # Should not call set for version since it already exists
    # Only one set call for the data
    assert mock_redis.set.call_count == 1


async def test_cache_set_exception_is_swallowed() -> None:
    session = _make_session()
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(side_effect=RuntimeError("redis down"))

    ev = RBACEvaluator(session, redis_client=mock_redis)
    # Should not raise
    await ev._cache_set("user:1", [])


async def test_cache_set_no_redis_noop() -> None:
    session = _make_session()
    ev = RBACEvaluator(session, redis_client=None)
    # Should not raise
    await ev._cache_set("user:1", [{"role_id": "r1"}])


# ---------------------------------------------------------------------------
# RBACEvaluator._expand_role_permissions — internal cache
# ---------------------------------------------------------------------------


async def test_expand_role_permissions_uses_local_cache() -> None:
    session = AsyncMock()
    perm_result = MagicMock()
    perm_result.fetchall.return_value = [("tool:execute",)]
    session.execute = AsyncMock(return_value=perm_result)

    ev = RBACEvaluator(session)
    # First call hits DB
    perms1 = await ev._expand_role_permissions("admin")
    assert "tool:execute" in perms1
    # Second call uses local cache
    perms2 = await ev._expand_role_permissions("admin")
    assert perms2 is perms1
    session.execute.assert_called_once()


# ---------------------------------------------------------------------------
# TeamContextValidator
# ---------------------------------------------------------------------------


async def test_team_context_validator_no_context_single_team_ok() -> None:
    result_mock = MagicMock()
    result_mock.fetchall.return_value = [("team-1",)]
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result_mock)

    validator = TeamContextValidator(session)
    valid, err = await validator.validate("user:1", None)
    assert valid is True
    assert err is None


async def test_team_context_validator_no_context_multiple_teams_invalid() -> None:
    result_mock = MagicMock()
    result_mock.fetchall.return_value = [("team-1",), ("team-2",)]
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result_mock)

    validator = TeamContextValidator(session)
    valid, err = await validator.validate("user:1", None)
    assert valid is False
    assert err == "principal_has_multiple_teams"


async def test_team_context_validator_with_valid_context() -> None:
    result_mock = MagicMock()
    result_mock.fetchall.return_value = [("team-1",), ("team-2",)]
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result_mock)

    validator = TeamContextValidator(session)
    valid, err = await validator.validate("user:1", "team-1")
    assert valid is True
    assert err is None


async def test_team_context_validator_with_invalid_context() -> None:
    result_mock = MagicMock()
    result_mock.fetchall.return_value = [("team-1",)]
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result_mock)

    validator = TeamContextValidator(session)
    valid, err = await validator.validate("user:1", "team-999")
    assert valid is False
    assert err == "team_not_in_memberships"


# ---------------------------------------------------------------------------
# resolve_principal_id
# ---------------------------------------------------------------------------


async def test_resolve_principal_id_found() -> None:
    result_mock = MagicMock()
    result_mock.first.return_value = ("principal-uuid-1",)
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result_mock)

    principal_id = await resolve_principal_id(session, "user:alice")
    assert principal_id == "principal-uuid-1"


async def test_resolve_principal_id_not_found() -> None:
    result_mock = MagicMock()
    result_mock.first.return_value = None
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result_mock)

    principal_id = await resolve_principal_id(session, "user:unknown")
    assert principal_id is None
