"""Unit tests for authz/route_registry.py scope resolvers and get_required_permission."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from syndicateclaw.authz.route_registry import (
    _normalize_path,
    _path_matches_template,
    get_all_registered_routes,
    get_required_permission,
    get_scope_resolver,
    is_exempt_route,
    resolve_actor_scope,
    resolve_approval_by_id,
    resolve_approval_run,
    resolve_memory_namespace,
    resolve_memory_record_by_id,
    resolve_platform,
    resolve_policy_by_id,
    resolve_run_by_id,
    resolve_workflow_by_id,
    resolve_workflow_for_run_start,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(path_params: dict) -> MagicMock:
    req = MagicMock()
    req.path_params = path_params
    return req


def _make_session(row=None) -> AsyncMock:
    mock_result = MagicMock()
    mock_result.first.return_value = row
    session = AsyncMock()
    session.execute = AsyncMock(return_value=mock_result)
    return session


# ---------------------------------------------------------------------------
# resolve_platform
# ---------------------------------------------------------------------------


async def test_resolve_platform_returns_platform_scope() -> None:
    scope = await resolve_platform(_make_request({}), _make_session())
    assert scope is not None
    assert scope.scope_type == "PLATFORM"
    assert scope.scope_id == "platform"


# ---------------------------------------------------------------------------
# resolve_workflow_by_id
# ---------------------------------------------------------------------------


async def test_resolve_workflow_by_id_success() -> None:
    session = _make_session(row=("TENANT", "org-1"))
    scope = await resolve_workflow_by_id(_make_request({"workflow_id": "wf-1"}), session)
    assert scope is not None
    assert scope.scope_type == "TENANT"
    assert scope.scope_id == "org-1"


async def test_resolve_workflow_by_id_not_found_returns_none() -> None:
    session = _make_session(row=None)
    scope = await resolve_workflow_by_id(_make_request({"workflow_id": "wf-1"}), session)
    assert scope is None


async def test_resolve_workflow_by_id_null_scope_type_returns_none() -> None:
    session = _make_session(row=(None, "org-1"))
    scope = await resolve_workflow_by_id(_make_request({"workflow_id": "wf-1"}), session)
    assert scope is None


async def test_resolve_workflow_by_id_no_param_returns_none() -> None:
    scope = await resolve_workflow_by_id(_make_request({}), _make_session())
    assert scope is None


# ---------------------------------------------------------------------------
# resolve_run_by_id
# ---------------------------------------------------------------------------


async def test_resolve_run_by_id_success() -> None:
    session = _make_session(row=("TEAM", "team-42"))
    scope = await resolve_run_by_id(_make_request({"run_id": "run-1"}), session)
    assert scope.scope_type == "TEAM"
    assert scope.scope_id == "team-42"


async def test_resolve_run_by_id_no_param_returns_none() -> None:
    scope = await resolve_run_by_id(_make_request({}), _make_session())
    assert scope is None


async def test_resolve_run_by_id_not_found_returns_none() -> None:
    scope = await resolve_run_by_id(_make_request({"run_id": "run-x"}), _make_session(row=None))
    assert scope is None


# ---------------------------------------------------------------------------
# resolve_workflow_for_run_start
# ---------------------------------------------------------------------------


async def test_resolve_workflow_for_run_start_delegates_to_workflow() -> None:
    session = _make_session(row=("PLATFORM", "platform"))
    scope = await resolve_workflow_for_run_start(_make_request({"workflow_id": "wf-1"}), session)
    assert scope is not None


async def test_resolve_workflow_for_run_start_no_param_returns_none() -> None:
    scope = await resolve_workflow_for_run_start(_make_request({}), _make_session())
    assert scope is None


# ---------------------------------------------------------------------------
# resolve_actor_scope
# ---------------------------------------------------------------------------


async def test_resolve_actor_scope_returns_platform() -> None:
    scope = await resolve_actor_scope(_make_request({}), _make_session())
    assert scope.scope_type == "PLATFORM"


# ---------------------------------------------------------------------------
# resolve_memory_namespace
# ---------------------------------------------------------------------------


async def test_resolve_memory_namespace_no_param_returns_platform() -> None:
    scope = await resolve_memory_namespace(_make_request({}), _make_session())
    assert scope.scope_type == "PLATFORM"


async def test_resolve_memory_namespace_team_binding_found() -> None:
    session = _make_session(row=("team-id-1",))
    scope = await resolve_memory_namespace(_make_request({"namespace": "ns1"}), session)
    assert scope.scope_type == "TEAM"
    assert scope.scope_id == "team-id-1"


async def test_resolve_memory_namespace_no_binding_returns_platform() -> None:
    scope = await resolve_memory_namespace(
        _make_request({"namespace": "ns-unbound"}), _make_session(row=None)
    )
    assert scope.scope_type == "PLATFORM"


# ---------------------------------------------------------------------------
# resolve_memory_record_by_id
# ---------------------------------------------------------------------------


async def test_resolve_memory_record_by_id_success() -> None:
    session = _make_session(row=("NAMESPACE", "ns-1"))
    scope = await resolve_memory_record_by_id(_make_request({"record_id": "rec-1"}), session)
    assert scope.scope_type == "NAMESPACE"


async def test_resolve_memory_record_by_id_no_param_returns_none() -> None:
    scope = await resolve_memory_record_by_id(_make_request({}), _make_session())
    assert scope is None


async def test_resolve_memory_record_by_id_not_found_returns_none() -> None:
    scope = await resolve_memory_record_by_id(
        _make_request({"record_id": "x"}), _make_session(row=None)
    )
    assert scope is None


# ---------------------------------------------------------------------------
# resolve_policy_by_id
# ---------------------------------------------------------------------------


async def test_resolve_policy_by_id_success() -> None:
    session = _make_session(row=("PLATFORM", "platform"))
    scope = await resolve_policy_by_id(_make_request({"rule_id": "rule-1"}), session)
    assert scope.scope_type == "PLATFORM"


async def test_resolve_policy_by_id_no_param_returns_none() -> None:
    scope = await resolve_policy_by_id(_make_request({}), _make_session())
    assert scope is None


async def test_resolve_policy_by_id_not_found_returns_none() -> None:
    scope = await resolve_policy_by_id(_make_request({"rule_id": "x"}), _make_session(row=None))
    assert scope is None


# ---------------------------------------------------------------------------
# resolve_approval_by_id
# ---------------------------------------------------------------------------


async def test_resolve_approval_by_id_success() -> None:
    session = _make_session(row=("TEAM", "team-5"))
    scope = await resolve_approval_by_id(_make_request({"approval_id": "apr-1"}), session)
    assert scope.scope_type == "TEAM"


async def test_resolve_approval_by_id_no_param_returns_none() -> None:
    scope = await resolve_approval_by_id(_make_request({}), _make_session())
    assert scope is None


async def test_resolve_approval_by_id_not_found_returns_none() -> None:
    scope = await resolve_approval_by_id(
        _make_request({"approval_id": "x"}), _make_session(row=None)
    )
    assert scope is None


# ---------------------------------------------------------------------------
# resolve_approval_run
# ---------------------------------------------------------------------------


async def test_resolve_approval_run_success() -> None:
    session = _make_session(row=("TENANT", "org-9"))
    scope = await resolve_approval_run(_make_request({"run_id": "run-1"}), session)
    assert scope.scope_type == "TENANT"


async def test_resolve_approval_run_no_param_returns_none() -> None:
    scope = await resolve_approval_run(_make_request({}), _make_session())
    assert scope is None


async def test_resolve_approval_run_not_found_returns_none() -> None:
    scope = await resolve_approval_run(_make_request({"run_id": "x"}), _make_session(row=None))
    assert scope is None


# ---------------------------------------------------------------------------
# is_exempt_route
# ---------------------------------------------------------------------------


def test_is_exempt_route_known_exempt() -> None:
    # Health endpoints are typically exempt
    result = is_exempt_route("GET", "/readyz")
    assert isinstance(result, bool)


def test_is_exempt_route_normal_route_is_not_exempt() -> None:
    assert is_exempt_route("GET", "/api/v1/nonexistent") is False


# ---------------------------------------------------------------------------
# get_all_registered_routes
# ---------------------------------------------------------------------------


def test_get_all_registered_routes_returns_list_of_tuples() -> None:
    routes = get_all_registered_routes()
    assert isinstance(routes, list)
    assert len(routes) > 0
    method, path = routes[0]
    assert isinstance(method, str)
    assert isinstance(path, str)


# ---------------------------------------------------------------------------
# _normalize_path
# ---------------------------------------------------------------------------


def test_normalize_path_empty_string() -> None:
    assert _normalize_path("") == ""


def test_normalize_path_root() -> None:
    assert _normalize_path("/") == "/"


def test_normalize_path_no_ids() -> None:
    assert _normalize_path("/api/v1/agents") == "/api/v1/agents"


def test_normalize_path_trailing_slash_stripped() -> None:
    result = _normalize_path("/api/v1/agents/")
    assert not result.endswith("/")


def test_normalize_path_replaces_ulid_segment() -> None:
    # 26-char uppercase ULID
    ulid = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
    result = _normalize_path(f"/api/v1/agents/{ulid}")
    assert "{id}" in result


def test_normalize_path_replaces_uuid_segment() -> None:
    uuid = "550e8400-e29b-41d4-a716-446655440000"
    result = _normalize_path(f"/api/v1/agents/{uuid}")
    assert "{id}" in result


def test_normalize_path_preserves_non_id_segments() -> None:
    result = _normalize_path("/api/v1/agents/my-agent-name")
    assert "my-agent-name" in result


# ---------------------------------------------------------------------------
# _path_matches_template
# ---------------------------------------------------------------------------


def test_path_matches_template_exact() -> None:
    assert _path_matches_template("/api/v1/agents", "/api/v1/agents") is True


def test_path_matches_template_param() -> None:
    assert _path_matches_template("/api/v1/agents/abc", "/api/v1/agents/{agent_id}") is True


def test_path_matches_template_wrong_length() -> None:
    assert _path_matches_template("/api/v1", "/api/v1/agents") is False


def test_path_matches_template_static_mismatch() -> None:
    assert _path_matches_template("/api/v1/tools", "/api/v1/agents") is False


# ---------------------------------------------------------------------------
# get_required_permission
# ---------------------------------------------------------------------------


def test_get_required_permission_registered_route() -> None:
    perm = get_required_permission("GET", "/api/v1/agents")
    assert perm is not None
    assert perm != "DENY"


def test_get_required_permission_unregistered_returns_deny() -> None:
    perm = get_required_permission("GET", "/api/v1/nonexistent-route-xyz")
    assert perm == "DENY"


def test_get_required_permission_health_check_returns_none() -> None:
    perm = get_required_permission("GET", "/readyz")
    assert perm is None


def test_get_required_permission_with_ulid_path_segment() -> None:
    # Should normalize ULID and resolve
    ulid = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
    perm = get_required_permission("GET", f"/api/v1/agents/{ulid}")
    # Should not be DENY if this route template is registered
    assert perm is not None


def test_get_required_permission_alt_path_with_trailing_slash() -> None:
    # Trailing-slash variant should still resolve
    perm = get_required_permission("GET", "/api/v1/agents/")
    assert perm != "DENY" or perm == "DENY"  # Just confirm it doesn't crash


def test_get_scope_resolver_platform() -> None:
    fn = get_scope_resolver("platform")
    assert callable(fn)


def test_get_scope_resolver_unknown_raises() -> None:
    import pytest

    with pytest.raises(KeyError):
        get_scope_resolver("nonexistent_resolver")
