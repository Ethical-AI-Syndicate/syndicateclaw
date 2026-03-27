from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.responses import Response

from syndicateclaw.authz.evaluator import Decision
from syndicateclaw.middleware.rbac import RBACMiddleware


def _make_request(
    *,
    enforcement_enabled: bool = True,
    environment: str = "test",
    method: str = "GET",
    path: str = "/api/v1/workflows/",
) -> MagicMock:
    request = MagicMock()
    request.method = method
    request.url.path = path
    request.state.actor = "test-actor"
    request.headers = {}
    request.app = MagicMock()
    request.app.state.settings = SimpleNamespace(
        rbac_enforcement_enabled=enforcement_enabled,
        environment=environment,
    )
    session = AsyncMock()
    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = session
    request.app.state.session_factory = MagicMock(return_value=session_cm)
    return request


@pytest.mark.asyncio
async def test_rbac_enforces_valid_permission(monkeypatch: pytest.MonkeyPatch) -> None:
    middleware = RBACMiddleware(MagicMock())
    request = _make_request()
    call_next = AsyncMock(return_value=Response(status_code=200))

    monkeypatch.setattr(
        "syndicateclaw.middleware.rbac.get_current_actor", AsyncMock(return_value="actor")
    )
    monkeypatch.setattr(
        "syndicateclaw.middleware.rbac.get_required_permission", lambda *_: "workflow:read"
    )
    monkeypatch.setattr(
        RBACMiddleware, "_evaluate_permission", AsyncMock(return_value=Decision.ALLOW)
    )

    response = await middleware.dispatch(request, call_next)
    assert response.status_code == 200
    call_next.assert_awaited_once()


@pytest.mark.asyncio
async def test_rbac_denies_insufficient_permission(monkeypatch: pytest.MonkeyPatch) -> None:
    middleware = RBACMiddleware(MagicMock())
    request = _make_request()
    call_next = AsyncMock(return_value=Response(status_code=200))

    monkeypatch.setattr(
        "syndicateclaw.middleware.rbac.get_current_actor", AsyncMock(return_value="actor")
    )
    monkeypatch.setattr(
        "syndicateclaw.middleware.rbac.get_required_permission", lambda *_: "workflow:read"
    )
    monkeypatch.setattr(
        RBACMiddleware, "_evaluate_permission", AsyncMock(return_value=Decision.DENY)
    )

    response = await middleware.dispatch(request, call_next)
    assert response.status_code == 403
    call_next.assert_not_awaited()


@pytest.mark.asyncio
async def test_rbac_admin_wildcard(monkeypatch: pytest.MonkeyPatch) -> None:
    middleware = RBACMiddleware(MagicMock())
    request = _make_request(path="/api/v1/tools/")
    call_next = AsyncMock(return_value=Response(status_code=200))

    monkeypatch.setattr(
        "syndicateclaw.middleware.rbac.get_current_actor", AsyncMock(return_value="admin:ops")
    )
    monkeypatch.setattr(
        "syndicateclaw.middleware.rbac.get_required_permission", lambda *_: "tool:read"
    )
    monkeypatch.setattr(
        RBACMiddleware, "_evaluate_permission", AsyncMock(return_value=Decision.ALLOW)
    )

    response = await middleware.dispatch(request, call_next)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_rbac_deny_beats_role_grant(monkeypatch: pytest.MonkeyPatch) -> None:
    middleware = RBACMiddleware(MagicMock())
    request = _make_request(path="/api/v1/policies/")
    call_next = AsyncMock(return_value=Response(status_code=200))

    monkeypatch.setattr(
        "syndicateclaw.middleware.rbac.get_current_actor", AsyncMock(return_value="actor")
    )
    monkeypatch.setattr(
        "syndicateclaw.middleware.rbac.get_required_permission", lambda *_: "policy:manage"
    )
    monkeypatch.setattr(
        RBACMiddleware, "_evaluate_permission", AsyncMock(return_value=Decision.DENY)
    )

    response = await middleware.dispatch(request, call_next)
    assert response.status_code == 403
    call_next.assert_not_awaited()


@pytest.mark.asyncio
async def test_rbac_enforcement_off_requires_explicit_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    middleware = RBACMiddleware(MagicMock())
    request = _make_request(enforcement_enabled=False, environment="production")
    call_next = AsyncMock(return_value=Response(status_code=200))

    eval_mock = AsyncMock(return_value=Decision.DENY)
    monkeypatch.setattr(RBACMiddleware, "_evaluate_permission", eval_mock)

    response = await middleware.dispatch(request, call_next)
    assert response.status_code == 200
    eval_mock.assert_not_awaited()
    call_next.assert_awaited_once()


@pytest.mark.asyncio
async def test_rbac_warn_logged_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    middleware = RBACMiddleware(MagicMock())
    request = _make_request(enforcement_enabled=False)
    call_next = AsyncMock(return_value=Response(status_code=200))

    warning = MagicMock()
    monkeypatch.setattr("syndicateclaw.middleware.rbac.logger.warning", warning)

    await middleware.dispatch(request, call_next)
    warning.assert_called_once()


@pytest.mark.asyncio
async def test_rbac_unknown_route_defaults_deny(monkeypatch: pytest.MonkeyPatch) -> None:
    middleware = RBACMiddleware(MagicMock())
    request = _make_request(path="/api/v1/unknown/path")
    call_next = AsyncMock(return_value=Response(status_code=200))

    monkeypatch.setattr(
        "syndicateclaw.middleware.rbac.get_current_actor", AsyncMock(return_value="actor")
    )
    monkeypatch.setattr("syndicateclaw.middleware.rbac.get_required_permission", lambda *_: "DENY")

    response = await middleware.dispatch(request, call_next)
    assert response.status_code == 403
    call_next.assert_not_awaited()


@pytest.mark.asyncio
async def test_rbac_policy_engine_deny_wins_after_rbac_allow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    middleware = RBACMiddleware(MagicMock())
    request = _make_request(path="/api/v1/tools/http_request/execute", method="POST")
    call_next = AsyncMock(return_value=Response(status_code=403))

    monkeypatch.setattr(
        "syndicateclaw.middleware.rbac.get_current_actor", AsyncMock(return_value="actor")
    )
    monkeypatch.setattr(
        "syndicateclaw.middleware.rbac.get_required_permission", lambda *_: "tool:execute"
    )
    monkeypatch.setattr(
        RBACMiddleware, "_evaluate_permission", AsyncMock(return_value=Decision.ALLOW)
    )

    response = await middleware.dispatch(request, call_next)
    assert response.status_code == 403
    call_next.assert_awaited_once()


@pytest.mark.asyncio
async def test_rbac_policy_engine_not_consulted_after_rbac_deny(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    middleware = RBACMiddleware(MagicMock())
    request = _make_request(path="/api/v1/tools/http_request/execute", method="POST")
    call_next = AsyncMock(return_value=Response(status_code=200))

    monkeypatch.setattr(
        "syndicateclaw.middleware.rbac.get_current_actor", AsyncMock(return_value="actor")
    )
    monkeypatch.setattr(
        "syndicateclaw.middleware.rbac.get_required_permission", lambda *_: "tool:execute"
    )
    monkeypatch.setattr(
        RBACMiddleware, "_evaluate_permission", AsyncMock(return_value=Decision.DENY)
    )

    response = await middleware.dispatch(request, call_next)
    assert response.status_code == 403
    call_next.assert_not_awaited()
