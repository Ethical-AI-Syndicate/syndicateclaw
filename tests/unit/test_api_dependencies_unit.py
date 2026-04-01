"""Unit tests for api/dependencies.py — paths not covered by integration tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException


def _make_request(
    *,
    auth_header: str | None = None,
    api_key: str | None = None,
    settings_env: str = "production",
    app_state: dict | None = None,
) -> Any:
    """Build a mock FastAPI Request."""
    req = MagicMock()
    headers = {}
    if auth_header:
        headers["Authorization"] = auth_header
    if api_key:
        headers["X-API-Key"] = api_key
    req.headers = headers
    req.state = MagicMock()

    state = app_state or {}
    settings = MagicMock()
    settings.secret_key = "test-secret"
    settings.environment = settings_env
    settings.jwt_secondary_secret_key = None
    settings.jwt_audience = None
    state.setdefault("settings", settings)

    for k, v in state.items():
        setattr(req.app.state, k, v)

    req.app.state.settings = state.get("settings", settings)
    req.app.state.asymmetric_keypair = None
    req.app.state.redis_client = None
    req.app.state.api_key_service = None
    return req


# ---------------------------------------------------------------------------
# _get_service — missing service raises 503
# ---------------------------------------------------------------------------


def test_get_service_raises_503_when_missing() -> None:
    from syndicateclaw.api.dependencies import _get_service

    req = _make_request()
    req.app.state.some_service = None
    with pytest.raises(HTTPException) as exc_info:
        _get_service(req, "some_service")
    assert exc_info.value.status_code == 503


def test_get_service_returns_service_when_present() -> None:
    from syndicateclaw.api.dependencies import _get_service

    req = _make_request()
    svc = MagicMock()
    req.app.state.my_svc = svc
    assert _get_service(req, "my_svc") is svc


# ---------------------------------------------------------------------------
# Individual service getters — verify they delegate to _get_service
# ---------------------------------------------------------------------------


def test_get_memory_service_delegates() -> None:
    from syndicateclaw.api.dependencies import get_memory_service

    req = _make_request()
    svc = MagicMock()
    req.app.state.memory_service = svc
    assert get_memory_service(req) is svc


def test_get_policy_engine_delegates() -> None:
    from syndicateclaw.api.dependencies import get_policy_engine

    req = _make_request()
    svc = MagicMock()
    req.app.state.policy_engine = svc
    assert get_policy_engine(req) is svc


def test_get_approval_service_delegates() -> None:
    from syndicateclaw.api.dependencies import get_approval_service

    req = _make_request()
    svc = MagicMock()
    req.app.state.approval_service = svc
    assert get_approval_service(req) is svc


def test_get_workflow_engine_delegates() -> None:
    from syndicateclaw.api.dependencies import get_workflow_engine

    req = _make_request()
    svc = MagicMock()
    req.app.state.workflow_engine = svc
    assert get_workflow_engine(req) is svc


def test_get_tool_executor_delegates() -> None:
    from syndicateclaw.api.dependencies import get_tool_executor

    req = _make_request()
    svc = MagicMock()
    req.app.state.tool_executor = svc
    assert get_tool_executor(req) is svc


def test_get_provider_service_delegates() -> None:
    from syndicateclaw.api.dependencies import get_provider_service

    req = _make_request()
    svc = MagicMock()
    req.app.state.provider_service = svc
    assert get_provider_service(req) is svc


def test_get_agent_service_delegates() -> None:
    from syndicateclaw.api.dependencies import get_agent_service

    req = _make_request()
    svc = MagicMock()
    req.app.state.agent_service = svc
    assert get_agent_service(req) is svc


def test_get_schedule_service_delegates() -> None:
    from syndicateclaw.api.dependencies import get_schedule_service

    req = _make_request()
    svc = MagicMock()
    req.app.state.schedule_service = svc
    assert get_schedule_service(req) is svc


def test_get_message_service_delegates() -> None:
    from syndicateclaw.api.dependencies import get_message_service

    req = _make_request()
    svc = MagicMock()
    req.app.state.message_service = svc
    assert get_message_service(req) is svc


def test_get_subscription_service_delegates() -> None:
    from syndicateclaw.api.dependencies import get_subscription_service

    req = _make_request()
    svc = MagicMock()
    req.app.state.subscription_service = svc
    assert get_subscription_service(req) is svc


def test_get_versioning_service_delegates() -> None:
    from syndicateclaw.api.dependencies import get_versioning_service

    req = _make_request()
    svc = MagicMock()
    req.app.state.versioning_service = svc
    assert get_versioning_service(req) is svc


def test_get_streaming_token_service_delegates() -> None:
    from syndicateclaw.api.dependencies import get_streaming_token_service

    req = _make_request()
    svc = MagicMock()
    req.app.state.streaming_token_service = svc
    assert get_streaming_token_service(req) is svc


def test_get_builder_token_service_delegates() -> None:
    from syndicateclaw.api.dependencies import get_builder_token_service

    req = _make_request()
    svc = MagicMock()
    req.app.state.builder_token_service = svc
    assert get_builder_token_service(req) is svc


def test_get_provider_loader_delegates() -> None:
    from syndicateclaw.api.dependencies import get_provider_loader

    req = _make_request()
    svc = MagicMock()
    req.app.state.provider_config_loader = svc
    assert get_provider_loader(req) is svc


def test_get_inference_catalog_delegates() -> None:
    from syndicateclaw.api.dependencies import get_inference_catalog

    req = _make_request()
    svc = MagicMock()
    req.app.state.inference_catalog = svc
    assert get_inference_catalog(req) is svc


# ---------------------------------------------------------------------------
# get_current_actor — JWT path (revocation check, missing sub)
# ---------------------------------------------------------------------------


async def test_get_current_actor_revoked_token_raises_401() -> None:
    from syndicateclaw.api.dependencies import get_current_actor

    req = _make_request(auth_header="Bearer mytoken")
    req.app.state.redis_client = AsyncMock()

    with (
        patch(
            "syndicateclaw.api.dependencies.decode_access_token",
            return_value={"sub": "actor-1", "jti": "jti-123"},
        ),
        patch("syndicateclaw.api.dependencies.is_token_revoked", return_value=True),
        pytest.raises(HTTPException) as exc_info,
    ):
        await get_current_actor(req)
    assert exc_info.value.status_code == 401
    assert "revoked" in exc_info.value.detail


async def test_get_current_actor_missing_sub_raises_401() -> None:
    from syndicateclaw.api.dependencies import get_current_actor

    req = _make_request(auth_header="Bearer mytoken")

    with (
        patch(
            "syndicateclaw.api.dependencies.decode_access_token",
            return_value={"jti": None},  # no sub
        ),
        patch("syndicateclaw.api.dependencies.is_token_revoked", return_value=False),
        pytest.raises(HTTPException) as exc_info,
    ):
        await get_current_actor(req)
    assert exc_info.value.status_code == 401
    assert "sub" in exc_info.value.detail


async def test_get_current_actor_valid_jwt_returns_actor() -> None:
    from syndicateclaw.api.dependencies import get_current_actor

    req = _make_request(auth_header="Bearer mytoken")

    with (
        patch(
            "syndicateclaw.api.dependencies.decode_access_token",
            return_value={"sub": "actor-1", "jti": None},
        ),
        patch("syndicateclaw.api.dependencies.is_token_revoked", return_value=False),
    ):
        actor = await get_current_actor(req)
    assert actor == "actor-1"


# ---------------------------------------------------------------------------
# get_current_actor — API key path (UnscopedApiKeyNotPermittedError)
# ---------------------------------------------------------------------------


async def test_get_current_actor_unscoped_key_raises_401() -> None:
    from syndicateclaw.api.dependencies import get_current_actor
    from syndicateclaw.security.api_keys import UnscopedApiKeyNotPermittedError

    req = _make_request(api_key="raw-key")
    api_key_svc = AsyncMock()
    api_key_svc.verify_key_details = AsyncMock(
        side_effect=UnscopedApiKeyNotPermittedError("unscoped")
    )
    req.app.state.api_key_service = api_key_svc

    with pytest.raises(HTTPException) as exc_info:
        await get_current_actor(req)
    assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# get_current_actor — anonymous fallback
# ---------------------------------------------------------------------------


async def test_get_current_actor_anonymous_in_dev() -> None:
    from syndicateclaw.api.dependencies import get_current_actor

    req = _make_request(settings_env="development")
    actor = await get_current_actor(req)
    assert actor == "anonymous"


async def test_get_current_actor_anonymous_blocked_in_production() -> None:
    from syndicateclaw.api.dependencies import get_current_actor

    req = _make_request(settings_env="production")
    with pytest.raises(HTTPException) as exc_info:
        await get_current_actor(req)
    assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# get_db_session — rollback on exception
# ---------------------------------------------------------------------------


async def test_get_db_session_rolls_back_on_exception() -> None:
    from syndicateclaw.api.dependencies import get_db_session

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()

    mock_factory = MagicMock(return_value=mock_session)

    req = _make_request()
    req.app.state.session_factory = mock_factory

    gen = get_db_session(req)
    await gen.__anext__()
    with pytest.raises(RuntimeError):
        await gen.athrow(RuntimeError("db error"))

    mock_session.rollback.assert_awaited_once()
