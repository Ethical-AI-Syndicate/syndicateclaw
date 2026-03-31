"""Unit tests for authz/shadow_middleware.py — covering uncovered paths."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from starlette.responses import JSONResponse, Response
from starlette.routing import Match

from syndicateclaw.authz.evaluator import AuthzResult, Decision
from syndicateclaw.authz.route_registry import RouteAuthzSpec
from syndicateclaw.authz.shadow_middleware import (
    DisagreementType,
    ShadowRBACMiddleware,
    _elapsed_us,
    _serialize_assignments,
    _serialize_denies,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_middleware() -> ShadowRBACMiddleware:
    app = MagicMock()
    return ShadowRBACMiddleware(app)


def _make_request(
    *,
    actor: str = "user:1",
    method: str = "GET",
    path: str = "/api/v1/workflows/",
    headers: dict | None = None,
    rbac_enforcement_enabled: bool = False,
    session_factory=None,
    redis_client=None,
    request_id: str | None = None,
) -> MagicMock:
    request = MagicMock()
    request.method = method
    request.url.path = path
    request.state.actor = actor
    request.state.request_id = request_id
    request.headers = headers or {}
    request.scope = {"type": "http", "path": path, "method": method}

    settings = SimpleNamespace(rbac_enforcement_enabled=rbac_enforcement_enabled)
    request.app.state.settings = settings
    request.app.state.session_factory = session_factory
    request.app.state.redis_client = redis_client
    request.app.routes = []
    return request


def _make_session_factory():
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_begin = AsyncMock()
    mock_begin.__aenter__ = AsyncMock(return_value=None)
    mock_begin.__aexit__ = AsyncMock(return_value=False)
    mock_session.begin = MagicMock(return_value=mock_begin)
    mock_session.execute = AsyncMock()

    return MagicMock(return_value=mock_session)


def _make_spec(
    *,
    permission: str = "workflow:read",
    scope_resolver: str = "platform",
    legacy_check: str = "authenticated_only",
    owner_field: str | None = None,
) -> RouteAuthzSpec:
    return RouteAuthzSpec(
        permission=permission,
        scope_resolver=scope_resolver,
        legacy_check=legacy_check,
        owner_field=owner_field,
    )


def _make_authz_result(decision: Decision = Decision.ALLOW) -> AuthzResult:
    result = MagicMock(spec=AuthzResult)
    result.decision = decision
    result.cache_hit = False
    result.deny_reason = None
    result.matched_assignments = []
    result.matched_denies = []
    result.permission_source = None
    result.evaluation_latency_us = 100
    return result


# ---------------------------------------------------------------------------
# Pure / sync helpers
# ---------------------------------------------------------------------------


def test_elapsed_us_returns_positive_int() -> None:
    import time
    t0 = time.monotonic()
    result = _elapsed_us(t0)
    assert isinstance(result, int)
    assert result >= 0


def test_serialize_assignments_none() -> None:
    assert _serialize_assignments(None) == "[]"


def test_serialize_denies_none() -> None:
    assert _serialize_denies(None) == "[]"


def test_serialize_assignments_with_result() -> None:
    result = _make_authz_result()
    assignment = MagicMock()
    assignment.to_dict.return_value = {"role": "reader"}
    result.matched_assignments = [assignment]
    out = _serialize_assignments(result)
    data = json.loads(out)
    assert data == [{"role": "reader"}]


def test_serialize_denies_with_result() -> None:
    result = _make_authz_result()
    deny = MagicMock()
    deny.to_dict.return_value = {"deny_type": "explicit"}
    result.matched_denies = [deny]
    out = _serialize_denies(result)
    data = json.loads(out)
    assert data == [{"deny_type": "explicit"}]


# ---------------------------------------------------------------------------
# _evaluate_legacy
# ---------------------------------------------------------------------------


def test_evaluate_legacy_403_returns_deny() -> None:
    mw = _make_middleware()
    spec = _make_spec()
    response = MagicMock()
    response.status_code = 403
    assert mw._evaluate_legacy(spec, "user:1", response) == Decision.DENY


def test_evaluate_legacy_200_returns_allow() -> None:
    mw = _make_middleware()
    spec = _make_spec()
    response = MagicMock()
    response.status_code = 200
    assert mw._evaluate_legacy(spec, "user:1", response) == Decision.ALLOW


def test_evaluate_legacy_prefix_admin_with_admin_actor() -> None:
    mw = _make_middleware()
    spec = _make_spec(legacy_check="prefix_admin")
    response = MagicMock()
    response.status_code = 200
    assert mw._evaluate_legacy(spec, "admin:ops", response) == Decision.ALLOW


def test_evaluate_legacy_prefix_admin_without_admin_actor() -> None:
    mw = _make_middleware()
    spec = _make_spec(legacy_check="prefix_admin")
    response = MagicMock()
    response.status_code = 200
    assert mw._evaluate_legacy(spec, "user:1", response) == Decision.DENY


def test_evaluate_legacy_prefix_admin_policy_prefix() -> None:
    mw = _make_middleware()
    spec = _make_spec(legacy_check="prefix_admin")
    response = MagicMock()
    response.status_code = 200
    assert mw._evaluate_legacy(spec, "policy:admin", response) == Decision.ALLOW


def test_evaluate_legacy_404_with_owner_field_returns_deny() -> None:
    mw = _make_middleware()
    spec = _make_spec(owner_field="created_by")
    response = MagicMock()
    response.status_code = 404
    assert mw._evaluate_legacy(spec, "user:1", response) == Decision.DENY


def test_evaluate_legacy_404_without_owner_field_returns_allow() -> None:
    mw = _make_middleware()
    spec = _make_spec(owner_field=None)
    response = MagicMock()
    response.status_code = 404
    assert mw._evaluate_legacy(spec, "user:1", response) == Decision.ALLOW


# ---------------------------------------------------------------------------
# _legacy_deny_reason
# ---------------------------------------------------------------------------


def test_legacy_deny_reason_403() -> None:
    mw = _make_middleware()
    spec = _make_spec()
    response = MagicMock()
    response.status_code = 403
    assert mw._legacy_deny_reason(spec, "user:1", response) == "handler returned 403"


def test_legacy_deny_reason_prefix_admin() -> None:
    mw = _make_middleware()
    spec = _make_spec(legacy_check="prefix_admin")
    response = MagicMock()
    response.status_code = 200
    reason = mw._legacy_deny_reason(spec, "user:1", response)
    assert "lacks admin prefix" in reason


def test_legacy_deny_reason_ownership() -> None:
    mw = _make_middleware()
    spec = _make_spec(owner_field="owner_id")
    response = MagicMock()
    response.status_code = 404
    reason = mw._legacy_deny_reason(spec, "user:1", response)
    assert "ownership" in reason


def test_legacy_deny_reason_fallback() -> None:
    mw = _make_middleware()
    spec = _make_spec()
    response = MagicMock()
    response.status_code = 422
    reason = mw._legacy_deny_reason(spec, "user:1", response)
    assert "422" in reason


# ---------------------------------------------------------------------------
# _resolve_route_template
# ---------------------------------------------------------------------------


def test_resolve_route_template_returns_path_when_no_routes() -> None:
    mw = _make_middleware()
    request = _make_request(path="/api/v1/test")
    request.app.routes = []
    result = mw._resolve_route_template(request)
    assert result == "/api/v1/test"


def test_resolve_route_template_prefers_static_over_parameterized() -> None:
    mw = _make_middleware()
    request = _make_request(path="/api/v1/workflows/")
    request.scope = {"type": "http", "path": "/api/v1/workflows/", "method": "GET"}

    static_route = MagicMock()
    static_route.path = "/api/v1/workflows/"
    static_route.matches.return_value = (Match.FULL, {})

    parameterized_route = MagicMock()
    parameterized_route.path = "/api/v1/{resource}/"
    parameterized_route.matches.return_value = (Match.FULL, {})

    request.app.routes = [parameterized_route, static_route]
    result = mw._resolve_route_template(request)
    assert result == "/api/v1/workflows/"  # static preferred (fewer {})


def test_resolve_route_template_full_match_wins() -> None:
    mw = _make_middleware()
    request = _make_request(path="/api/v1/workflows/wf-1")
    request.scope = {"type": "http", "path": "/api/v1/workflows/wf-1", "method": "GET"}

    route = MagicMock()
    route.path = "/api/v1/workflows/{workflow_id}"
    route.matches.return_value = (Match.FULL, {})

    partial_route = MagicMock()
    partial_route.path = "/api/v1/workflows"
    partial_route.matches.return_value = (Match.PARTIAL, {})

    request.app.routes = [route, partial_route]
    result = mw._resolve_route_template(request)
    assert result == "/api/v1/workflows/{workflow_id}"


# ---------------------------------------------------------------------------
# _enforce_rbac_if_enabled — returns None when enforcement disabled
# ---------------------------------------------------------------------------


async def test_enforce_rbac_returns_none_when_disabled() -> None:
    mw = _make_middleware()
    request = _make_request(rbac_enforcement_enabled=False)
    result = await mw._enforce_rbac_if_enabled(request)
    assert result is None


async def test_enforce_rbac_returns_none_when_no_settings() -> None:
    mw = _make_middleware()
    request = _make_request()
    request.app.state.settings = None
    result = await mw._enforce_rbac_if_enabled(request)
    assert result is None


async def test_enforce_rbac_returns_none_when_anonymous() -> None:
    mw = _make_middleware()
    request = _make_request(rbac_enforcement_enabled=True, actor="anonymous")
    result = await mw._enforce_rbac_if_enabled(request)
    assert result is None


async def test_enforce_rbac_returns_none_when_no_actor() -> None:
    mw = _make_middleware()
    request = _make_request(rbac_enforcement_enabled=True)
    request.state.actor = None
    result = await mw._enforce_rbac_if_enabled(request)
    assert result is None


async def test_enforce_rbac_returns_none_for_public_route() -> None:
    mw = _make_middleware()
    request = _make_request(rbac_enforcement_enabled=True, path="/api/v1/health")
    with patch("syndicateclaw.authz.shadow_middleware.is_public_route", return_value=True):
        with patch("syndicateclaw.authz.shadow_middleware.ShadowRBACMiddleware._resolve_route_template", return_value="/api/v1/health"):
            result = await mw._enforce_rbac_if_enabled(request)
    assert result is None


async def test_enforce_rbac_returns_none_for_exempt_route() -> None:
    mw = _make_middleware()
    request = _make_request(rbac_enforcement_enabled=True)
    with patch("syndicateclaw.authz.shadow_middleware.is_public_route", return_value=False):
        with patch("syndicateclaw.authz.shadow_middleware.is_exempt_route", return_value=True):
            with patch.object(mw, "_resolve_route_template", return_value="/api/v1/metrics"):
                result = await mw._enforce_rbac_if_enabled(request)
    assert result is None


async def test_enforce_rbac_returns_none_when_no_spec() -> None:
    mw = _make_middleware()
    request = _make_request(rbac_enforcement_enabled=True)
    with patch("syndicateclaw.authz.shadow_middleware.is_public_route", return_value=False):
        with patch("syndicateclaw.authz.shadow_middleware.is_exempt_route", return_value=False):
            with patch("syndicateclaw.authz.shadow_middleware.get_route_spec", return_value=None):
                with patch.object(mw, "_resolve_route_template", return_value="/unknown"):
                    result = await mw._enforce_rbac_if_enabled(request)
    assert result is None


async def test_enforce_rbac_returns_none_when_no_session_factory() -> None:
    mw = _make_middleware()
    spec = _make_spec()
    request = _make_request(rbac_enforcement_enabled=True, session_factory=None)
    with patch("syndicateclaw.authz.shadow_middleware.is_public_route", return_value=False):
        with patch("syndicateclaw.authz.shadow_middleware.is_exempt_route", return_value=False):
            with patch("syndicateclaw.authz.shadow_middleware.get_route_spec", return_value=spec):
                with patch.object(mw, "_resolve_route_template", return_value="/api/v1/workflows/"):
                    result = await mw._enforce_rbac_if_enabled(request)
    assert result is None


async def test_enforce_rbac_403_when_principal_not_found() -> None:
    mw = _make_middleware()
    spec = _make_spec()
    session_factory = _make_session_factory()
    request = _make_request(rbac_enforcement_enabled=True, session_factory=session_factory)

    with patch("syndicateclaw.authz.shadow_middleware.is_public_route", return_value=False):
        with patch("syndicateclaw.authz.shadow_middleware.is_exempt_route", return_value=False):
            with patch("syndicateclaw.authz.shadow_middleware.get_route_spec", return_value=spec):
                with patch.object(mw, "_resolve_route_template", return_value="/api/v1/workflows/"):
                    with patch("syndicateclaw.authz.shadow_middleware.resolve_principal_id", return_value=None):
                        result = await mw._enforce_rbac_if_enabled(request)

    assert isinstance(result, JSONResponse)
    assert result.status_code == 403


async def test_enforce_rbac_403_on_scope_resolution_failure() -> None:
    mw = _make_middleware()
    spec = _make_spec(scope_resolver="resolve_workflow_by_id")
    session_factory = _make_session_factory()
    request = _make_request(rbac_enforcement_enabled=True, session_factory=session_factory)

    mock_validator = AsyncMock()
    mock_validator.validate = AsyncMock(return_value=(True, None))

    with patch("syndicateclaw.authz.shadow_middleware.is_public_route", return_value=False):
        with patch("syndicateclaw.authz.shadow_middleware.is_exempt_route", return_value=False):
            with patch("syndicateclaw.authz.shadow_middleware.get_route_spec", return_value=spec):
                with patch.object(mw, "_resolve_route_template", return_value="/api/v1/workflows/wf-1"):
                    with patch("syndicateclaw.authz.shadow_middleware.resolve_principal_id", return_value="pid-1"):
                        with patch("syndicateclaw.authz.shadow_middleware.TeamContextValidator", return_value=mock_validator):
                            with patch("syndicateclaw.authz.shadow_middleware.SCOPE_RESOLVERS", {"resolve_workflow_by_id": AsyncMock(side_effect=RuntimeError("db down"))}):
                                result = await mw._enforce_rbac_if_enabled(request)

    assert isinstance(result, JSONResponse)
    assert result.status_code == 403


async def test_enforce_rbac_403_on_rbac_deny() -> None:
    mw = _make_middleware()
    spec = _make_spec()
    session_factory = _make_session_factory()
    request = _make_request(rbac_enforcement_enabled=True, session_factory=session_factory)

    mock_validator = AsyncMock()
    mock_validator.validate = AsyncMock(return_value=(True, None))
    mock_evaluator = AsyncMock()
    mock_evaluator.evaluate = AsyncMock(return_value=_make_authz_result(Decision.DENY))

    with patch("syndicateclaw.authz.shadow_middleware.is_public_route", return_value=False):
        with patch("syndicateclaw.authz.shadow_middleware.is_exempt_route", return_value=False):
            with patch("syndicateclaw.authz.shadow_middleware.get_route_spec", return_value=spec):
                with patch.object(mw, "_resolve_route_template", return_value="/api/v1/workflows/"):
                    with patch("syndicateclaw.authz.shadow_middleware.resolve_principal_id", return_value="pid-1"):
                        with patch("syndicateclaw.authz.shadow_middleware.TeamContextValidator", return_value=mock_validator):
                            with patch("syndicateclaw.authz.shadow_middleware.SCOPE_RESOLVERS", {}):
                                with patch("syndicateclaw.authz.shadow_middleware.RBACEvaluator", return_value=mock_evaluator):
                                    result = await mw._enforce_rbac_if_enabled(request)

    assert isinstance(result, JSONResponse)
    assert result.status_code == 403


async def test_enforce_rbac_allows_when_rbac_allow() -> None:
    mw = _make_middleware()
    spec = _make_spec()
    session_factory = _make_session_factory()
    request = _make_request(rbac_enforcement_enabled=True, session_factory=session_factory)

    mock_validator = AsyncMock()
    mock_validator.validate = AsyncMock(return_value=(True, None))
    mock_evaluator = AsyncMock()
    mock_evaluator.evaluate = AsyncMock(return_value=_make_authz_result(Decision.ALLOW))

    with patch("syndicateclaw.authz.shadow_middleware.is_public_route", return_value=False):
        with patch("syndicateclaw.authz.shadow_middleware.is_exempt_route", return_value=False):
            with patch("syndicateclaw.authz.shadow_middleware.get_route_spec", return_value=spec):
                with patch.object(mw, "_resolve_route_template", return_value="/api/v1/workflows/"):
                    with patch("syndicateclaw.authz.shadow_middleware.resolve_principal_id", return_value="pid-1"):
                        with patch("syndicateclaw.authz.shadow_middleware.TeamContextValidator", return_value=mock_validator):
                            with patch("syndicateclaw.authz.shadow_middleware.SCOPE_RESOLVERS", {}):
                                with patch("syndicateclaw.authz.shadow_middleware.RBACEvaluator", return_value=mock_evaluator):
                                    result = await mw._enforce_rbac_if_enabled(request)

    assert result is None


async def test_enforce_rbac_403_team_context_multiple_teams() -> None:
    mw = _make_middleware()
    spec = _make_spec()
    session_factory = _make_session_factory()
    request = _make_request(rbac_enforcement_enabled=True, session_factory=session_factory)

    mock_validator = AsyncMock()
    mock_validator.validate = AsyncMock(return_value=(False, "principal_has_multiple_teams"))

    with patch("syndicateclaw.authz.shadow_middleware.is_public_route", return_value=False):
        with patch("syndicateclaw.authz.shadow_middleware.is_exempt_route", return_value=False):
            with patch("syndicateclaw.authz.shadow_middleware.get_route_spec", return_value=spec):
                with patch.object(mw, "_resolve_route_template", return_value="/api/v1/workflows/"):
                    with patch("syndicateclaw.authz.shadow_middleware.resolve_principal_id", return_value="pid-1"):
                        with patch("syndicateclaw.authz.shadow_middleware.TeamContextValidator", return_value=mock_validator):
                            with patch("syndicateclaw.authz.shadow_middleware.SCOPE_RESOLVERS", {}):
                                result = await mw._enforce_rbac_if_enabled(request)

    assert isinstance(result, JSONResponse)
    assert result.status_code == 403


async def test_enforce_rbac_403_team_not_in_memberships() -> None:
    mw = _make_middleware()
    spec = _make_spec()
    session_factory = _make_session_factory()
    request = _make_request(rbac_enforcement_enabled=True, session_factory=session_factory)

    mock_validator = AsyncMock()
    mock_validator.validate = AsyncMock(return_value=(False, "team_not_in_memberships"))

    with patch("syndicateclaw.authz.shadow_middleware.is_public_route", return_value=False):
        with patch("syndicateclaw.authz.shadow_middleware.is_exempt_route", return_value=False):
            with patch("syndicateclaw.authz.shadow_middleware.get_route_spec", return_value=spec):
                with patch.object(mw, "_resolve_route_template", return_value="/api/v1/workflows/"):
                    with patch("syndicateclaw.authz.shadow_middleware.resolve_principal_id", return_value="pid-1"):
                        with patch("syndicateclaw.authz.shadow_middleware.TeamContextValidator", return_value=mock_validator):
                            with patch("syndicateclaw.authz.shadow_middleware.SCOPE_RESOLVERS", {}):
                                result = await mw._enforce_rbac_if_enabled(request)

    assert isinstance(result, JSONResponse)
    assert result.status_code == 403


# ---------------------------------------------------------------------------
# _try_shadow — anonymous / public skip paths
# ---------------------------------------------------------------------------


async def test_try_shadow_skips_anonymous() -> None:
    mw = _make_middleware()
    request = _make_request(actor="anonymous")
    response = Response(status_code=200)
    # Should return without doing anything (no exception)
    await mw._try_shadow(request, response)


async def test_try_shadow_skips_none_actor() -> None:
    mw = _make_middleware()
    request = _make_request()
    request.state.actor = None
    response = Response(status_code=200)
    await mw._try_shadow(request, response)


async def test_try_shadow_skips_public_route() -> None:
    mw = _make_middleware()
    request = _make_request()
    response = Response(status_code=200)
    with patch.object(mw, "_resolve_route_template", return_value="/health"):
        with patch("syndicateclaw.authz.shadow_middleware.is_public_route", return_value=True):
            await mw._try_shadow(request, response)


async def test_try_shadow_skips_exempt_route() -> None:
    mw = _make_middleware()
    request = _make_request()
    response = Response(status_code=200)
    with patch.object(mw, "_resolve_route_template", return_value="/metrics"):
        with patch("syndicateclaw.authz.shadow_middleware.is_public_route", return_value=False):
            with patch("syndicateclaw.authz.shadow_middleware.is_exempt_route", return_value=True):
                await mw._try_shadow(request, response)


async def test_try_shadow_swallows_evaluation_errors() -> None:
    mw = _make_middleware()
    request = _make_request()
    response = Response(status_code=200)
    with patch.object(mw, "_resolve_route_template", return_value="/api/v1/workflows/"):
        with patch("syndicateclaw.authz.shadow_middleware.is_public_route", return_value=False):
            with patch("syndicateclaw.authz.shadow_middleware.is_exempt_route", return_value=False):
                with patch.object(mw, "_shadow_evaluate", side_effect=RuntimeError("boom")):
                    with patch.object(mw, "_incr_metric", new=AsyncMock()):
                        # Should not raise
                        await mw._try_shadow(request, response)


# ---------------------------------------------------------------------------
# _shadow_evaluate — unregistered route path
# ---------------------------------------------------------------------------


async def test_shadow_evaluate_unregistered_route_records_disagreement() -> None:
    mw = _make_middleware()
    session_factory = _make_session_factory()
    request = _make_request(session_factory=session_factory)
    response = Response(status_code=200)

    with patch("syndicateclaw.authz.shadow_middleware.get_route_spec", return_value=None):
        with patch.object(mw, "_record_evaluation", new=AsyncMock()) as mock_record:
            await mw._shadow_evaluate(request, response, "GET", "/unknown", "user:1")

    mock_record.assert_awaited_once()
    kwargs = mock_record.call_args[1]
    assert kwargs["disagreement_type"] == DisagreementType.ROUTE_UNREGISTERED


async def test_shadow_evaluate_returns_when_no_session_factory() -> None:
    mw = _make_middleware()
    spec = _make_spec()
    request = _make_request(session_factory=None)
    response = Response(status_code=200)

    with patch("syndicateclaw.authz.shadow_middleware.get_route_spec", return_value=spec):
        with patch.object(mw, "_record_evaluation", new=AsyncMock()) as mock_record:
            await mw._shadow_evaluate(request, response, "GET", "/api/v1/workflows/", "user:1")

    mock_record.assert_not_awaited()


async def test_shadow_evaluate_principal_not_found() -> None:
    mw = _make_middleware()
    spec = _make_spec()
    session_factory = _make_session_factory()
    request = _make_request(session_factory=session_factory)
    response = Response(status_code=200)

    with patch("syndicateclaw.authz.shadow_middleware.get_route_spec", return_value=spec):
        with patch("syndicateclaw.authz.shadow_middleware.resolve_principal_id", return_value=None):
            with patch.object(mw, "_record_evaluation", new=AsyncMock()) as mock_record:
                await mw._shadow_evaluate(request, response, "GET", "/api/v1/workflows/", "user:1")

    mock_record.assert_awaited_once()
    kwargs = mock_record.call_args[1]
    assert kwargs["disagreement_type"] == DisagreementType.PRINCIPAL_NOT_FOUND


async def test_shadow_evaluate_agree_path() -> None:
    mw = _make_middleware()
    spec = _make_spec()
    session_factory = _make_session_factory()
    request = _make_request(session_factory=session_factory)
    response = Response(status_code=200)

    mock_validator = AsyncMock()
    mock_validator.validate = AsyncMock(return_value=(True, None))
    mock_evaluator = AsyncMock()
    mock_evaluator.evaluate = AsyncMock(return_value=_make_authz_result(Decision.ALLOW))

    with patch("syndicateclaw.authz.shadow_middleware.get_route_spec", return_value=spec):
        with patch("syndicateclaw.authz.shadow_middleware.resolve_principal_id", return_value="pid-1"):
            with patch("syndicateclaw.authz.shadow_middleware.TeamContextValidator", return_value=mock_validator):
                with patch("syndicateclaw.authz.shadow_middleware.SCOPE_RESOLVERS", {}):
                    with patch("syndicateclaw.authz.shadow_middleware.RBACEvaluator", return_value=mock_evaluator):
                        with patch.object(mw, "_record_evaluation", new=AsyncMock()) as mock_record:
                            await mw._shadow_evaluate(request, response, "GET", "/api/v1/workflows/", "user:1")

    mock_record.assert_awaited_once()
    kwargs = mock_record.call_args[1]
    assert kwargs["disagreement_type"] is None  # agreement


async def test_shadow_evaluate_disagree_legacy_allow_rbac_deny() -> None:
    mw = _make_middleware()
    spec = _make_spec()
    session_factory = _make_session_factory()
    request = _make_request(session_factory=session_factory)
    response = Response(status_code=200)  # legacy = ALLOW

    mock_validator = AsyncMock()
    mock_validator.validate = AsyncMock(return_value=(True, None))
    mock_evaluator = AsyncMock()
    mock_evaluator.evaluate = AsyncMock(return_value=_make_authz_result(Decision.DENY))

    with patch("syndicateclaw.authz.shadow_middleware.get_route_spec", return_value=spec):
        with patch("syndicateclaw.authz.shadow_middleware.resolve_principal_id", return_value="pid-1"):
            with patch("syndicateclaw.authz.shadow_middleware.TeamContextValidator", return_value=mock_validator):
                with patch("syndicateclaw.authz.shadow_middleware.SCOPE_RESOLVERS", {}):
                    with patch("syndicateclaw.authz.shadow_middleware.RBACEvaluator", return_value=mock_evaluator):
                        with patch.object(mw, "_record_evaluation", new=AsyncMock()) as mock_record:
                            await mw._shadow_evaluate(request, response, "GET", "/api/v1/workflows/", "user:1")

    kwargs = mock_record.call_args[1]
    assert kwargs["disagreement_type"] == DisagreementType.LEGACY_ALLOW_RBAC_DENY


async def test_shadow_evaluate_scope_failure_type() -> None:
    mw = _make_middleware()
    spec = _make_spec(scope_resolver="resolve_workflow_by_id")
    session_factory = _make_session_factory()
    request = _make_request(session_factory=session_factory)
    response = Response(status_code=200)

    mock_validator = AsyncMock()
    mock_validator.validate = AsyncMock(return_value=(True, None))
    mock_evaluator = AsyncMock()
    mock_evaluator.evaluate = AsyncMock(return_value=_make_authz_result(Decision.ALLOW))

    with patch("syndicateclaw.authz.shadow_middleware.get_route_spec", return_value=spec):
        with patch("syndicateclaw.authz.shadow_middleware.resolve_principal_id", return_value="pid-1"):
            with patch("syndicateclaw.authz.shadow_middleware.TeamContextValidator", return_value=mock_validator):
                with patch("syndicateclaw.authz.shadow_middleware.SCOPE_RESOLVERS", {"resolve_workflow_by_id": AsyncMock(side_effect=RuntimeError("db down"))}):
                    with patch("syndicateclaw.authz.shadow_middleware.RBACEvaluator", return_value=mock_evaluator):
                        with patch.object(mw, "_record_evaluation", new=AsyncMock()) as mock_record:
                            await mw._shadow_evaluate(request, response, "GET", "/api/v1/workflows/wf-1", "user:1")

    kwargs = mock_record.call_args[1]
    assert kwargs["disagreement_type"] == DisagreementType.SCOPE_RESOLUTION_FAILED


async def test_shadow_evaluate_team_context_missing_type() -> None:
    mw = _make_middleware()
    spec = _make_spec()
    session_factory = _make_session_factory()
    request = _make_request(session_factory=session_factory)
    response = Response(status_code=200)

    mock_validator = AsyncMock()
    mock_validator.validate = AsyncMock(return_value=(False, "principal_has_multiple_teams"))
    mock_evaluator = AsyncMock()
    mock_evaluator.evaluate = AsyncMock(return_value=_make_authz_result(Decision.ALLOW))

    with patch("syndicateclaw.authz.shadow_middleware.get_route_spec", return_value=spec):
        with patch("syndicateclaw.authz.shadow_middleware.resolve_principal_id", return_value="pid-1"):
            with patch("syndicateclaw.authz.shadow_middleware.TeamContextValidator", return_value=mock_validator):
                with patch("syndicateclaw.authz.shadow_middleware.SCOPE_RESOLVERS", {}):
                    with patch("syndicateclaw.authz.shadow_middleware.RBACEvaluator", return_value=mock_evaluator):
                        with patch.object(mw, "_record_evaluation", new=AsyncMock()) as mock_record:
                            await mw._shadow_evaluate(request, response, "GET", "/api/v1/workflows/", "user:1")

    kwargs = mock_record.call_args[1]
    assert kwargs["disagreement_type"] == DisagreementType.TEAM_CONTEXT_MISSING


# ---------------------------------------------------------------------------
# _record_evaluation — DB write and metrics
# ---------------------------------------------------------------------------


async def test_record_evaluation_skips_when_no_session_factory() -> None:
    mw = _make_middleware()
    request = _make_request(session_factory=None)
    rbac_result = _make_authz_result(Decision.ALLOW)

    # Should not raise
    await mw._record_evaluation(
        request=request,
        request_id="req-1",
        route_name="/api/v1/workflows/",
        method="GET",
        path="/api/v1/workflows/",
        actor="user:1",
        principal_id="pid-1",
        team_context=None,
        team_context_valid=True,
        required_permission="workflow:read",
        resolved_scope_type=None,
        resolved_scope_id=None,
        rbac_result=rbac_result,
        legacy_decision=Decision.ALLOW,
        legacy_deny_reason=None,
        disagreement_type=None,
        evaluation_latency_us=100,
    )


async def test_record_evaluation_handles_db_write_failure() -> None:
    mw = _make_middleware()
    session_factory = _make_session_factory()
    # Make execute raise
    session_factory.return_value.execute = AsyncMock(side_effect=RuntimeError("insert failed"))
    request = _make_request(session_factory=session_factory)
    rbac_result = _make_authz_result(Decision.ALLOW)

    with patch.object(mw, "_incr_metric", new=AsyncMock()):
        with patch.object(mw, "_emit_metrics", new=AsyncMock()):
            # Should not raise
            await mw._record_evaluation(
                request=request,
                request_id=None,
                route_name="/api/v1/workflows/",
                method="GET",
                path="/api/v1/workflows/",
                actor="user:1",
                principal_id="pid-1",
                team_context=None,
                team_context_valid=True,
                required_permission="workflow:read",
                resolved_scope_type=None,
                resolved_scope_id=None,
                rbac_result=rbac_result,
                legacy_decision=Decision.ALLOW,
                legacy_deny_reason=None,
                disagreement_type=None,
                evaluation_latency_us=100,
            )


# ---------------------------------------------------------------------------
# _emit_metrics
# ---------------------------------------------------------------------------


async def test_emit_metrics_skips_when_no_redis() -> None:
    mw = _make_middleware()
    request = _make_request(redis_client=None)
    # Should not raise
    await mw._emit_metrics(request, True, None, None)


async def test_emit_metrics_agreement() -> None:
    mw = _make_middleware()
    mock_redis = AsyncMock()
    pipe = MagicMock()
    pipe.incr = MagicMock()
    pipe.execute = AsyncMock()
    mock_redis.pipeline = MagicMock(return_value=pipe)
    request = _make_request(redis_client=mock_redis)

    await mw._emit_metrics(request, True, None, None)
    pipe.incr.assert_any_call("rbac.shadow.agree")


async def test_emit_metrics_disagreement_legacy_allow_rbac_deny() -> None:
    mw = _make_middleware()
    mock_redis = AsyncMock()
    pipe = MagicMock()
    pipe.incr = MagicMock()
    pipe.execute = AsyncMock()
    mock_redis.pipeline = MagicMock(return_value=pipe)
    request = _make_request(redis_client=mock_redis)

    await mw._emit_metrics(request, False, DisagreementType.LEGACY_ALLOW_RBAC_DENY, None)
    pipe.incr.assert_any_call("rbac.shadow.rbac_stricter")


async def test_emit_metrics_disagreement_legacy_deny_rbac_allow() -> None:
    mw = _make_middleware()
    mock_redis = AsyncMock()
    pipe = MagicMock()
    pipe.incr = MagicMock()
    pipe.execute = AsyncMock()
    mock_redis.pipeline = MagicMock(return_value=pipe)
    request = _make_request(redis_client=mock_redis)

    await mw._emit_metrics(request, False, DisagreementType.LEGACY_DENY_RBAC_ALLOW, None)
    pipe.incr.assert_any_call("rbac.shadow.legacy_stricter")


async def test_emit_metrics_with_cache_hit() -> None:
    mw = _make_middleware()
    mock_redis = AsyncMock()
    pipe = MagicMock()
    pipe.incr = MagicMock()
    pipe.execute = AsyncMock()
    mock_redis.pipeline = MagicMock(return_value=pipe)
    request = _make_request(redis_client=mock_redis)
    rbac_result = _make_authz_result(Decision.ALLOW)
    rbac_result.cache_hit = True

    await mw._emit_metrics(request, True, None, rbac_result)
    pipe.incr.assert_any_call("rbac.shadow.cache_hit")


async def test_emit_metrics_handles_redis_error() -> None:
    mw = _make_middleware()
    mock_redis = AsyncMock()
    mock_redis.pipeline = MagicMock(side_effect=RuntimeError("redis down"))
    request = _make_request(redis_client=mock_redis)
    # Should not raise
    await mw._emit_metrics(request, True, None, None)


# ---------------------------------------------------------------------------
# _incr_metric
# ---------------------------------------------------------------------------


async def test_incr_metric_skips_when_no_redis() -> None:
    mw = _make_middleware()
    request = _make_request(redis_client=None)
    await mw._incr_metric(request, "rbac.shadow.total")


async def test_incr_metric_calls_redis_incr() -> None:
    mw = _make_middleware()
    mock_redis = AsyncMock()
    mock_redis.incr = AsyncMock()
    request = _make_request(redis_client=mock_redis)
    await mw._incr_metric(request, "rbac.shadow.total")
    mock_redis.incr.assert_awaited_once_with("rbac.shadow.total")


async def test_incr_metric_suppresses_redis_error() -> None:
    mw = _make_middleware()
    mock_redis = AsyncMock()
    mock_redis.incr = AsyncMock(side_effect=RuntimeError("redis down"))
    request = _make_request(redis_client=mock_redis)
    # Should not raise
    await mw._incr_metric(request, "rbac.shadow.total")
