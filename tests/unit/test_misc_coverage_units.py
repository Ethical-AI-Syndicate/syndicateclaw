"""Unit tests for small utility modules previously at < 60% coverage.

Covers:
- memory/retention.py
- tools/inference_tools.py
- security/revocation.py
- cache/state_cache.py
- middleware/csrf.py
- tasks/message_delivery.py
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.responses import Response

from syndicateclaw.cache.state_cache import StateCache
from syndicateclaw.memory.retention import RetentionEnforcer, RetentionReport
from syndicateclaw.middleware.csrf import BuilderCSRFMiddleware
from syndicateclaw.security.revocation import is_token_revoked
from syndicateclaw.tools.inference_tools import build_inference_tools

# ---------------------------------------------------------------------------
# memory/retention.py
# ---------------------------------------------------------------------------


def test_retention_report_total_purged() -> None:
    r = RetentionReport(expired_count=3, deleted_count=7)
    assert r.total_purged == 10


async def test_retention_enforcer_run_success() -> None:
    svc = AsyncMock()
    svc.enforce_retention = AsyncMock(return_value=5)
    enforcer = RetentionEnforcer(svc)
    report = await enforcer.run()
    assert report.expired_count == 5
    assert report.errors == []


async def test_retention_enforcer_run_exception_captured() -> None:
    svc = AsyncMock()
    svc.enforce_retention = AsyncMock(side_effect=RuntimeError("db down"))
    enforcer = RetentionEnforcer(svc)
    report = await enforcer.run()
    assert report.expired_count == 0
    assert len(report.errors) == 1
    assert "db down" in report.errors[0]


# ---------------------------------------------------------------------------
# tools/inference_tools.py
# ---------------------------------------------------------------------------


async def test_llm_handler_calls_infer_chat() -> None:
    mock_response = MagicMock()
    mock_response.model_dump.return_value = {"inference_id": "x", "content": "hello"}

    provider_service = AsyncMock()
    provider_service.infer_chat = AsyncMock(return_value=mock_response)

    tools = build_inference_tools(provider_service)
    _, llm_handler = tools[0]

    input_data = {
        "messages": [{"role": "user", "content": "hi"}],
        "actor": "test-actor",
        "trace_id": "trace-1",
    }
    result = await llm_handler(input_data)
    assert result["content"] == "hello"
    provider_service.infer_chat.assert_awaited_once()


async def test_embed_handler_calls_infer_embedding() -> None:
    mock_response = MagicMock()
    mock_response.model_dump.return_value = {"inference_id": "y", "dimensions": 3}

    provider_service = AsyncMock()
    provider_service.infer_embedding = AsyncMock(return_value=mock_response)

    tools = build_inference_tools(provider_service)
    _, embed_handler = tools[1]

    input_data = {
        "inputs": ["hello world"],
        "actor": "test-actor",
        "trace_id": "trace-2",
    }
    result = await embed_handler(input_data)
    assert result["dimensions"] == 3
    provider_service.infer_embedding.assert_awaited_once()


async def test_llm_handler_optional_fields_default() -> None:
    mock_response = MagicMock()
    mock_response.model_dump.return_value = {}
    provider_service = AsyncMock()
    provider_service.infer_chat = AsyncMock(return_value=mock_response)
    tools = build_inference_tools(provider_service)
    _, llm_handler = tools[0]
    # No trace_id / provider_id / model_id
    await llm_handler({"messages": [{"role": "user", "content": "x"}], "actor": "a"})
    req = provider_service.infer_chat.call_args[0][0]
    assert req.trace_id == ""  # defaults to empty string


# ---------------------------------------------------------------------------
# security/revocation.py
# ---------------------------------------------------------------------------


async def test_revocation_redis_none_returns_false() -> None:
    assert await is_token_revoked(None, "some-jti") is False


async def test_revocation_empty_jti_returns_false() -> None:
    assert await is_token_revoked(AsyncMock(), "") is False


async def test_revocation_key_present_returns_true() -> None:
    redis = AsyncMock()
    redis.get = AsyncMock(return_value="1")
    assert await is_token_revoked(redis, "jti-abc") is True


async def test_revocation_key_absent_returns_false() -> None:
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    assert await is_token_revoked(redis, "jti-abc") is False


async def test_revocation_redis_error_returns_false() -> None:
    redis = AsyncMock()
    redis.get = AsyncMock(side_effect=ConnectionError("redis down"))
    assert await is_token_revoked(redis, "jti-abc") is False


# ---------------------------------------------------------------------------
# cache/state_cache.py
# ---------------------------------------------------------------------------


def test_state_cache_key_format() -> None:
    cache = StateCache(None)
    assert cache._key("run-99") == "syndicateclaw:run_state:run-99"


async def test_state_cache_set_with_no_redis_is_noop() -> None:
    cache = StateCache(None)
    await cache.set("run-1", {"k": "v"}, "RUNNING")  # should not raise


async def test_state_cache_set_uses_status_ttl() -> None:
    redis = AsyncMock()
    cache = StateCache(redis)
    await cache.set("run-1", {"k": "v"}, "COMPLETED")
    redis.set.assert_awaited_once()
    _, kwargs = redis.set.call_args
    assert kwargs["ex"] == 60  # COMPLETED TTL


async def test_state_cache_set_unknown_status_uses_default_ttl() -> None:
    redis = AsyncMock()
    cache = StateCache(redis)
    await cache.set("run-1", {}, "UNKNOWN_STATUS")
    _, kwargs = redis.set.call_args
    assert kwargs["ex"] == 3600


async def test_state_cache_get_no_redis_returns_none() -> None:
    cache = StateCache(None)
    assert await cache.get("run-1") is None


async def test_state_cache_get_missing_key_returns_none() -> None:
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    cache = StateCache(redis)
    assert await cache.get("run-1") is None


async def test_state_cache_get_returns_deserialized_dict() -> None:
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=json.dumps({"x": 1}).encode())
    cache = StateCache(redis)
    result = await cache.get("run-1")
    assert result == {"x": 1}


async def test_state_cache_invalidate_no_redis_is_noop() -> None:
    cache = StateCache(None)
    await cache.invalidate("run-1")  # should not raise


async def test_state_cache_invalidate_calls_delete() -> None:
    redis = AsyncMock()
    cache = StateCache(redis)
    await cache.invalidate("run-1")
    redis.delete.assert_awaited_once_with("syndicateclaw:run_state:run-1")


# ---------------------------------------------------------------------------
# middleware/csrf.py
# ---------------------------------------------------------------------------


def _make_csrf_request(
    *,
    method: str = "PUT",
    path: str = "/api/v1/workflows/wf-abc",
    builder_enabled: bool = True,
    builder_token: str | None = "valid-token",
    builder_token_svc: object = None,
    settings: object | None = None,
) -> MagicMock:
    request = MagicMock()
    request.method = method.upper()
    request.url.path = path
    request.headers = {}
    if builder_token is not None:
        request.headers = {"X-Builder-Token": builder_token}
    if settings is None:
        settings = SimpleNamespace(builder_enabled=builder_enabled)
    request.app = MagicMock()
    request.app.state.settings = settings
    request.app.state.builder_token_service = builder_token_svc
    return request


async def test_csrf_pass_through_when_builder_disabled() -> None:
    mw = BuilderCSRFMiddleware(MagicMock())
    request = _make_csrf_request(builder_enabled=False)
    call_next = AsyncMock(return_value=Response(status_code=200))
    resp = await mw.dispatch(request, call_next)
    assert resp.status_code == 200
    call_next.assert_awaited_once()


async def test_csrf_pass_through_non_put() -> None:
    mw = BuilderCSRFMiddleware(MagicMock())
    request = _make_csrf_request(method="GET")
    call_next = AsyncMock(return_value=Response(status_code=200))
    resp = await mw.dispatch(request, call_next)
    assert resp.status_code == 200


async def test_csrf_pass_through_non_workflow_path() -> None:
    mw = BuilderCSRFMiddleware(MagicMock())
    request = _make_csrf_request(path="/api/v1/agents/agent-1")
    call_next = AsyncMock(return_value=Response(status_code=200))
    resp = await mw.dispatch(request, call_next)
    assert resp.status_code == 200


async def test_csrf_pass_through_workflow_subpath() -> None:
    # PUT /api/v1/workflows/{id}/runs has a slash in rest — should pass through
    mw = BuilderCSRFMiddleware(MagicMock())
    request = _make_csrf_request(path="/api/v1/workflows/wf-abc/runs")
    call_next = AsyncMock(return_value=Response(status_code=200))
    resp = await mw.dispatch(request, call_next)
    assert resp.status_code == 200


async def test_csrf_missing_token_returns_403() -> None:
    mw = BuilderCSRFMiddleware(MagicMock())
    request = _make_csrf_request(builder_token=None)
    request.headers = {}
    call_next = AsyncMock(return_value=Response(status_code=200))
    resp = await mw.dispatch(request, call_next)
    assert resp.status_code == 403


async def test_csrf_missing_service_returns_500() -> None:
    mw = BuilderCSRFMiddleware(MagicMock())
    request = _make_csrf_request(builder_token_svc=None)
    request.app.state.builder_token_service = None
    call_next = AsyncMock(return_value=Response(status_code=200))
    resp = await mw.dispatch(request, call_next)
    assert resp.status_code == 500


async def test_csrf_valid_token_passes_through() -> None:
    svc = AsyncMock()
    svc.validate = AsyncMock(return_value=None)
    mw = BuilderCSRFMiddleware(MagicMock())
    request = _make_csrf_request(builder_token_svc=svc)
    call_next = AsyncMock(return_value=Response(status_code=200))
    resp = await mw.dispatch(request, call_next)
    assert resp.status_code == 200


async def test_csrf_invalid_token_returns_403() -> None:
    from syndicateclaw.services.streaming_token_service import InvalidTokenError

    svc = AsyncMock()
    svc.validate = AsyncMock(side_effect=InvalidTokenError("token expired"))
    mw = BuilderCSRFMiddleware(MagicMock())
    request = _make_csrf_request(builder_token_svc=svc)
    call_next = AsyncMock(return_value=Response(status_code=200))
    resp = await mw.dispatch(request, call_next)
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# tasks/message_delivery.py
# ---------------------------------------------------------------------------


async def test_message_delivery_loop_delivers_message() -> None:
    """Run one pass of the delivery loop; break after first sleep."""
    from syndicateclaw.tasks.message_delivery import run_message_delivery_loop

    msg = MagicMock()
    msg.id = "msg-001"

    call_count = 0

    async def fake_sleep(_: float) -> None:
        nonlocal call_count
        call_count += 1
        if call_count >= 1:
            raise asyncio.CancelledError

    svc = AsyncMock()
    svc.pending_messages = AsyncMock(return_value=[msg])
    svc.mark_delivered = AsyncMock(return_value=None)

    mock_factory = MagicMock()

    with (
        patch("syndicateclaw.tasks.message_delivery.asyncio.sleep", side_effect=fake_sleep),
        pytest.raises(asyncio.CancelledError),
    ):
        await run_message_delivery_loop(svc, mock_factory, poll_interval_seconds=1)

    svc.mark_delivered.assert_awaited_once_with("msg-001")


async def test_message_delivery_loop_dead_letters_on_failure() -> None:
    """If all retries fail, write a DeadLetterRecord."""
    from syndicateclaw.tasks.message_delivery import run_message_delivery_loop

    msg = MagicMock()
    msg.id = "msg-fail"

    sleep_call = 0

    async def fake_sleep(_: float) -> None:
        nonlocal sleep_call
        sleep_call += 1
        if sleep_call > 5:  # allow retry sleeps + one poll sleep
            raise asyncio.CancelledError

    svc = AsyncMock()
    svc.pending_messages = AsyncMock(return_value=[msg])
    svc.mark_delivered = AsyncMock(side_effect=RuntimeError("delivery error"))
    svc.mark_delivery_failed = AsyncMock()

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_begin = AsyncMock()
    mock_begin.__aenter__ = AsyncMock(return_value=None)
    mock_begin.__aexit__ = AsyncMock(return_value=False)
    mock_session.begin = MagicMock(return_value=mock_begin)
    mock_session.add = MagicMock()
    mock_factory = MagicMock(return_value=mock_session)

    with (
        patch("syndicateclaw.tasks.message_delivery.asyncio.sleep", side_effect=fake_sleep),
        pytest.raises(asyncio.CancelledError),
    ):
        await run_message_delivery_loop(svc, mock_factory, poll_interval_seconds=1)

    svc.mark_delivery_failed.assert_awaited_once_with("msg-fail")
    mock_session.add.assert_called_once()
