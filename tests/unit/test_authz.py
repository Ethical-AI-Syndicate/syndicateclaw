"""Unit tests for the RBAC evaluator and route registry.

Tests the pure evaluator logic with mocked database sessions — no real
database required. Tests the route registry for completeness and correctness.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syndicateclaw.authz.evaluator import (
    AuthzResult,
    Decision,
    DenyReason,
    MatchedAssignment,
    MatchedDeny,
    RBACEvaluator,
    TeamContextValidator,
    _scope_contains,
    resolve_principal_id,
)
from syndicateclaw.authz.route_registry import (
    PUBLIC_ROUTES,
    ROUTE_PERMISSION_MAP,
    SCOPE_RESOLVERS,
    Scope,
    RouteAuthzSpec,
    get_all_registered_routes,
    get_route_spec,
    get_scope_resolver,
    is_public_route,
)


# ---------------------------------------------------------------------------
# Scope containment tests
# ---------------------------------------------------------------------------

class TestScopeContainment:
    def test_platform_contains_everything(self):
        platform = Scope(scope_type="PLATFORM", scope_id="platform")
        assert _scope_contains(platform, Scope(scope_type="TENANT", scope_id="acme"))
        assert _scope_contains(platform, Scope(scope_type="TEAM", scope_id="alpha"))
        assert _scope_contains(platform, Scope(scope_type="NAMESPACE", scope_id="ns:x"))
        assert _scope_contains(platform, platform)

    def test_same_scope_same_id(self):
        team_a = Scope(scope_type="TEAM", scope_id="alpha")
        assert _scope_contains(team_a, team_a)

    def test_same_scope_different_id(self):
        team_a = Scope(scope_type="TEAM", scope_id="alpha")
        team_b = Scope(scope_type="TEAM", scope_id="beta")
        assert not _scope_contains(team_a, team_b)

    def test_narrower_does_not_contain_broader(self):
        team = Scope(scope_type="TEAM", scope_id="alpha")
        tenant = Scope(scope_type="TENANT", scope_id="acme")
        assert not _scope_contains(team, tenant)

    def test_broader_contains_narrower(self):
        tenant = Scope(scope_type="TENANT", scope_id="acme")
        team = Scope(scope_type="TEAM", scope_id="alpha")
        assert _scope_contains(tenant, team)


# ---------------------------------------------------------------------------
# Route registry tests
# ---------------------------------------------------------------------------

class TestRouteRegistry:
    def test_all_routes_have_permissions(self):
        for (method, path), spec in ROUTE_PERMISSION_MAP.items():
            assert spec.permission, f"Route {method} {path} has no permission"
            assert ":" in spec.permission, f"Permission '{spec.permission}' must be resource:action format"

    def test_all_routes_have_scope_resolvers(self):
        for (method, path), spec in ROUTE_PERMISSION_MAP.items():
            assert spec.scope_resolver in SCOPE_RESOLVERS, (
                f"Route {method} {path} references unknown resolver '{spec.scope_resolver}'"
            )

    def test_public_routes_not_in_permission_map(self):
        for method, path in PUBLIC_ROUTES:
            assert (method, path) not in ROUTE_PERMISSION_MAP

    def test_get_route_spec_found(self):
        spec = get_route_spec("POST", "/api/v1/workflows/")
        assert spec is not None
        assert spec.permission == "workflow:create"

    def test_get_route_spec_not_found(self):
        spec = get_route_spec("GET", "/nonexistent")
        assert spec is None

    def test_is_public_route(self):
        assert is_public_route("GET", "/healthz")
        assert is_public_route("GET", "/readyz")
        assert not is_public_route("POST", "/api/v1/workflows/")

    def test_get_scope_resolver(self):
        resolver = get_scope_resolver("platform")
        assert callable(resolver)

    def test_get_scope_resolver_unknown(self):
        with pytest.raises(KeyError):
            get_scope_resolver("nonexistent")

    def test_workflow_routes_covered(self):
        expected = [
            ("POST", "/api/v1/workflows/"),
            ("GET", "/api/v1/workflows/"),
            ("GET", "/api/v1/workflows/{workflow_id}"),
            ("POST", "/api/v1/workflows/{workflow_id}/runs"),
        ]
        for route in expected:
            assert route in ROUTE_PERMISSION_MAP, f"Missing route: {route}"

    def test_run_routes_covered(self):
        expected_actions = ["pause", "resume", "cancel", "replay"]
        for action in expected_actions:
            key = ("POST", f"/api/v1/workflows/runs/{{run_id}}/{action}")
            assert key in ROUTE_PERMISSION_MAP, f"Missing route: {key}"

    def test_memory_routes_covered(self):
        expected = [
            ("POST", "/api/v1/memory/"),
            ("GET", "/api/v1/memory/{namespace}/{key}"),
            ("GET", "/api/v1/memory/{namespace}"),
            ("PUT", "/api/v1/memory/{record_id}"),
            ("DELETE", "/api/v1/memory/{record_id}"),
            ("GET", "/api/v1/memory/{record_id}/lineage"),
        ]
        for route in expected:
            assert route in ROUTE_PERMISSION_MAP, f"Missing route: {route}"

    def test_policy_routes_covered(self):
        expected = [
            ("POST", "/api/v1/policies/"),
            ("GET", "/api/v1/policies/"),
            ("GET", "/api/v1/policies/{rule_id}"),
            ("PUT", "/api/v1/policies/{rule_id}"),
            ("DELETE", "/api/v1/policies/{rule_id}"),
            ("POST", "/api/v1/policies/evaluate"),
        ]
        for route in expected:
            assert route in ROUTE_PERMISSION_MAP, f"Missing route: {route}"

    def test_policy_manage_routes_require_admin(self):
        admin_routes = [
            ("POST", "/api/v1/policies/"),
            ("PUT", "/api/v1/policies/{rule_id}"),
            ("DELETE", "/api/v1/policies/{rule_id}"),
        ]
        for route in admin_routes:
            spec = ROUTE_PERMISSION_MAP[route]
            assert spec.permission == "policy:manage"
            assert spec.legacy_check == "prefix_admin"

    def test_route_count_minimum(self):
        assert len(ROUTE_PERMISSION_MAP) >= 30, (
            f"Expected at least 30 routes, got {len(ROUTE_PERMISSION_MAP)}"
        )


# ---------------------------------------------------------------------------
# RBAC evaluator tests
# ---------------------------------------------------------------------------

def _mock_session(
    assignments=None,
    denies=None,
    role_permissions=None,
):
    """Create a mock AsyncSession that returns controlled query results."""
    session = AsyncMock()

    call_count = {"n": 0}

    async def mock_execute(query, params=None):
        call_count["n"] += 1
        result = MagicMock()

        query_str = str(query)

        if "deny_assignments" in query_str:
            rows = denies or []
            result.fetchall.return_value = rows
            return result

        if "role_assignments" in query_str or "team_memberships" in query_str:
            rows = assignments or []
            result.fetchall.return_value = rows
            return result

        if "role_chain" in query_str:
            perms = role_permissions or set()
            result.fetchall.return_value = [(p,) for p in perms]
            return result

        if "principals" in query_str:
            result.first.return_value = ("principal-123",)
            return result

        result.fetchall.return_value = []
        result.first.return_value = None
        return result

    session.execute = mock_execute
    return session


class TestRBACEvaluator:
    @pytest.mark.asyncio
    async def test_deny_when_no_principal(self):
        session = _mock_session()
        evaluator = RBACEvaluator(session)
        result = await evaluator.evaluate(None, "workflow:read", Scope.platform())

        assert result.decision == Decision.DENY
        assert result.deny_reason == DenyReason.NO_PRINCIPAL

    @pytest.mark.asyncio
    async def test_allow_with_matching_grant(self):
        assignments = [
            ("asgn-1", "role-1", "operator", '["workflow:read"]', "viewer",
             "PLATFORM", "platform", "direct", None),
        ]
        session = _mock_session(
            assignments=assignments,
            role_permissions={"workflow:read", "workflow:create", "run:read"},
        )
        evaluator = RBACEvaluator(session)
        result = await evaluator.evaluate("principal-1", "workflow:read", Scope.platform())

        assert result.decision == Decision.ALLOW
        assert result.permission_source is not None
        assert len(result.matched_assignments) == 1
        assert result.matched_assignments[0].role_name == "operator"

    @pytest.mark.asyncio
    async def test_deny_no_matching_grant(self):
        assignments = [
            ("asgn-1", "role-1", "viewer", '["workflow:read"]', None,
             "PLATFORM", "platform", "direct", None),
        ]
        session = _mock_session(
            assignments=assignments,
            role_permissions={"workflow:read"},
        )
        evaluator = RBACEvaluator(session)
        result = await evaluator.evaluate("principal-1", "policy:manage", Scope.platform())

        assert result.decision == Decision.DENY
        assert result.deny_reason == DenyReason.NO_MATCHING_GRANT

    @pytest.mark.asyncio
    async def test_explicit_deny_wins_over_grant(self):
        assignments = [
            ("asgn-1", "role-1", "admin", '["policy:manage"]', "operator",
             "PLATFORM", "platform", "direct", None),
        ]
        denies = [
            ("deny-1", "policy:manage", "PLATFORM", "platform", "under investigation", None),
        ]
        session = _mock_session(assignments=assignments, denies=denies)
        evaluator = RBACEvaluator(session)
        result = await evaluator.evaluate("principal-1", "policy:manage", Scope.platform())

        assert result.decision == Decision.DENY
        assert result.deny_reason == DenyReason.EXPLICIT_DENY
        assert len(result.matched_denies) == 1

    @pytest.mark.asyncio
    async def test_expired_deny_ignored(self):
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        assignments = [
            ("asgn-1", "role-1", "admin", '["policy:manage"]', "operator",
             "PLATFORM", "platform", "direct", None),
        ]
        denies = [
            ("deny-1", "policy:manage", "PLATFORM", "platform", "expired", past),
        ]
        session = _mock_session(
            assignments=assignments,
            denies=denies,
            role_permissions={"policy:manage"},
        )
        evaluator = RBACEvaluator(session)
        result = await evaluator.evaluate("principal-1", "policy:manage", Scope.platform())

        assert result.decision == Decision.ALLOW

    @pytest.mark.asyncio
    async def test_scope_not_contained(self):
        assignments = [
            ("asgn-1", "role-1", "operator", '["workflow:read"]', "viewer",
             "TEAM", "team-alpha", "direct", None),
        ]
        session = _mock_session(
            assignments=assignments,
            role_permissions={"workflow:read"},
        )
        evaluator = RBACEvaluator(session)
        result = await evaluator.evaluate(
            "principal-1",
            "workflow:read",
            Scope(scope_type="TEAM", scope_id="team-beta"),
        )

        assert result.decision == Decision.DENY
        assert result.deny_reason == DenyReason.NO_MATCHING_GRANT

    @pytest.mark.asyncio
    async def test_expired_assignment(self):
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        assignments = [
            ("asgn-1", "role-1", "operator", '["workflow:read"]', "viewer",
             "PLATFORM", "platform", "direct", past),
        ]
        session = _mock_session(
            assignments=assignments,
            role_permissions={"workflow:read"},
        )
        evaluator = RBACEvaluator(session)
        result = await evaluator.evaluate("principal-1", "workflow:read", Scope.platform())

        assert result.decision == Decision.DENY
        assert result.deny_reason == DenyReason.EXPIRED_ASSIGNMENTS_ONLY

    @pytest.mark.asyncio
    async def test_team_inherited_assignment(self):
        assignments = [
            ("asgn-1", "role-1", "operator", '["workflow:read"]', "viewer",
             "PLATFORM", "platform", "team:team-alpha", None),
        ]
        session = _mock_session(
            assignments=assignments,
            role_permissions={"workflow:read"},
        )
        evaluator = RBACEvaluator(session)
        result = await evaluator.evaluate("principal-1", "workflow:read", Scope.platform())

        assert result.decision == Decision.ALLOW
        assert result.matched_assignments[0].source == "team:team-alpha"


class TestResolvesPrincipalId:
    @pytest.mark.asyncio
    async def test_resolves_existing(self):
        session = AsyncMock()
        result = MagicMock()
        result.first.return_value = ("pid-abc",)
        session.execute = AsyncMock(return_value=result)

        pid = await resolve_principal_id(session, "user:alice")
        assert pid == "pid-abc"

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown(self):
        session = AsyncMock()
        result = MagicMock()
        result.first.return_value = None
        session.execute = AsyncMock(return_value=result)

        pid = await resolve_principal_id(session, "unknown:actor")
        assert pid is None


class TestTeamContextValidator:
    @pytest.mark.asyncio
    async def test_no_context_single_team(self):
        session = AsyncMock()
        result = MagicMock()
        result.fetchall.return_value = [("team-alpha",)]
        session.execute = AsyncMock(return_value=result)

        v = TeamContextValidator(session)
        valid, error = await v.validate("pid-1", None)
        assert valid is True
        assert error is None

    @pytest.mark.asyncio
    async def test_no_context_multiple_teams(self):
        session = AsyncMock()
        result = MagicMock()
        result.fetchall.return_value = [("team-alpha",), ("team-beta",)]
        session.execute = AsyncMock(return_value=result)

        v = TeamContextValidator(session)
        valid, error = await v.validate("pid-1", None)
        assert valid is False
        assert error == "principal_has_multiple_teams"

    @pytest.mark.asyncio
    async def test_valid_context(self):
        session = AsyncMock()
        result = MagicMock()
        result.fetchall.return_value = [("team-alpha",), ("team-beta",)]
        session.execute = AsyncMock(return_value=result)

        v = TeamContextValidator(session)
        valid, error = await v.validate("pid-1", "team-alpha")
        assert valid is True

    @pytest.mark.asyncio
    async def test_invalid_context(self):
        session = AsyncMock()
        result = MagicMock()
        result.fetchall.return_value = [("team-alpha",)]
        session.execute = AsyncMock(return_value=result)

        v = TeamContextValidator(session)
        valid, error = await v.validate("pid-1", "team-gamma")
        assert valid is False
        assert error == "team_not_in_memberships"
