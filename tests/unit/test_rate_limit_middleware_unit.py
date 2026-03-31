"""Unit tests for api/rate_limit.py — RateLimitMiddleware dispatch paths."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from starlette.responses import Response

from syndicateclaw.api.rate_limit import (
    RateLimitMiddleware,
    _extract_actor_hint,
    _rate_limit_response,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_middleware() -> RateLimitMiddleware:
    return RateLimitMiddleware(MagicMock())


def _make_request(
    *,
    path: str = "/api/v1/workflows/",
    actor: str | None = "user:1",
    redis_client=None,
    settings=None,
    headers: dict | None = None,
) -> MagicMock:
    request = MagicMock()
    request.url.path = path
    request.state.actor = actor
    request.headers = headers or {}

    request.app.state.redis_client = redis_client
    request.app.state.settings = settings
    return request


def _make_settings(
    window: int = 60,
    max_requests: int = 100,
    burst: int = 20,
) -> SimpleNamespace:
    return SimpleNamespace(
        rate_limit_window_seconds=window,
        rate_limit_requests=max_requests,
        rate_limit_burst=burst,
    )


def _make_redis(window_count: int = 1, burst_count: int = 1) -> AsyncMock:
    """Redis pipeline mock returning (window_count, burst_count)."""
    mock_redis = AsyncMock()
    pipe = AsyncMock()
    # results[2] = window_count, results[6] = burst_count
    results = [None, None, window_count, None, None, None, burst_count, None]
    pipe.execute = AsyncMock(return_value=results)
    pipe.zremrangebyscore = MagicMock()
    pipe.zadd = MagicMock()
    pipe.zcard = MagicMock()
    pipe.expire = MagicMock()
    mock_redis.pipeline = MagicMock(return_value=pipe)
    return mock_redis


# ---------------------------------------------------------------------------
# Skip paths
# ---------------------------------------------------------------------------


async def test_dispatch_skips_healthz() -> None:
    mw = _make_middleware()
    request = _make_request(path="/healthz")
    call_next = AsyncMock(return_value=Response(status_code=200))
    response = await mw.dispatch(request, call_next)
    assert response.status_code == 200
    call_next.assert_awaited_once()


async def test_dispatch_skips_readyz() -> None:
    mw = _make_middleware()
    request = _make_request(path="/readyz")
    call_next = AsyncMock(return_value=Response(status_code=200))
    response = await mw.dispatch(request, call_next)
    call_next.assert_awaited_once()


async def test_dispatch_skips_docs() -> None:
    mw = _make_middleware()
    request = _make_request(path="/docs")
    call_next = AsyncMock(return_value=Response(status_code=200))
    response = await mw.dispatch(request, call_next)
    call_next.assert_awaited_once()


async def test_dispatch_passes_when_no_settings() -> None:
    mw = _make_middleware()
    request = _make_request(settings=None, redis_client=None)
    call_next = AsyncMock(return_value=Response(status_code=200))
    response = await mw.dispatch(request, call_next)
    call_next.assert_awaited_once()


async def test_dispatch_passes_when_no_redis() -> None:
    mw = _make_middleware()
    settings = _make_settings()
    request = _make_request(settings=settings, redis_client=None)
    call_next = AsyncMock(return_value=Response(status_code=200))
    response = await mw.dispatch(request, call_next)
    call_next.assert_awaited_once()


async def test_dispatch_passes_when_anonymous_actor() -> None:
    mw = _make_middleware()
    settings = _make_settings()
    redis = _make_redis()
    request = _make_request(settings=settings, redis_client=redis, actor="anonymous")
    call_next = AsyncMock(return_value=Response(status_code=200))
    response = await mw.dispatch(request, call_next)
    call_next.assert_awaited_once()


async def test_dispatch_passes_when_no_actor_no_hint() -> None:
    mw = _make_middleware()
    settings = _make_settings()
    redis = _make_redis()
    request = _make_request(settings=settings, redis_client=redis, actor=None, headers={})
    call_next = AsyncMock(return_value=Response(status_code=200))
    response = await mw.dispatch(request, call_next)
    call_next.assert_awaited_once()


# ---------------------------------------------------------------------------
# Redis error fallback
# ---------------------------------------------------------------------------


async def test_dispatch_allows_on_redis_error() -> None:
    mw = _make_middleware()
    settings = _make_settings()
    mock_redis = AsyncMock()
    pipe = AsyncMock()
    pipe.execute = AsyncMock(side_effect=RuntimeError("redis down"))
    pipe.zremrangebyscore = MagicMock()
    pipe.zadd = MagicMock()
    pipe.zcard = MagicMock()
    pipe.expire = MagicMock()
    mock_redis.pipeline = MagicMock(return_value=pipe)

    request = _make_request(settings=settings, redis_client=mock_redis)
    call_next = AsyncMock(return_value=Response(status_code=200))
    response = await mw.dispatch(request, call_next)
    assert response.status_code == 200
    call_next.assert_awaited_once()


# ---------------------------------------------------------------------------
# Rate limited — window exceeded
# ---------------------------------------------------------------------------


async def test_dispatch_429_when_window_exceeded() -> None:
    mw = _make_middleware()
    settings = _make_settings(max_requests=5)
    redis = _make_redis(window_count=6, burst_count=1)
    request = _make_request(settings=settings, redis_client=redis)
    call_next = AsyncMock(return_value=Response(status_code=200))
    response = await mw.dispatch(request, call_next)
    assert response.status_code == 429
    call_next.assert_not_awaited()


# ---------------------------------------------------------------------------
# Rate limited — burst exceeded
# ---------------------------------------------------------------------------


async def test_dispatch_429_when_burst_exceeded() -> None:
    mw = _make_middleware()
    settings = _make_settings(max_requests=100, burst=3)
    redis = _make_redis(window_count=2, burst_count=4)
    request = _make_request(settings=settings, redis_client=redis)
    call_next = AsyncMock(return_value=Response(status_code=200))
    response = await mw.dispatch(request, call_next)
    assert response.status_code == 429
    call_next.assert_not_awaited()


# ---------------------------------------------------------------------------
# Allowed — rate limit headers added
# ---------------------------------------------------------------------------


async def test_dispatch_adds_rate_limit_headers_on_success() -> None:
    mw = _make_middleware()
    settings = _make_settings(max_requests=100, burst=20)
    redis = _make_redis(window_count=5, burst_count=2)
    request = _make_request(settings=settings, redis_client=redis)
    call_next = AsyncMock(return_value=Response(status_code=200))
    response = await mw.dispatch(request, call_next)
    assert response.status_code == 200
    assert "X-RateLimit-Limit" in response.headers
    assert "X-RateLimit-Remaining" in response.headers
    assert "X-RateLimit-Reset" in response.headers


# ---------------------------------------------------------------------------
# Actor hint extraction from headers (no actor on request.state)
# ---------------------------------------------------------------------------


async def test_dispatch_uses_api_key_hint_when_no_actor() -> None:
    mw = _make_middleware()
    settings = _make_settings()
    redis = _make_redis()
    request = _make_request(
        settings=settings,
        redis_client=redis,
        actor=None,
        headers={"x-api-key": "sk-test12345"},
    )
    call_next = AsyncMock(return_value=Response(status_code=200))
    response = await mw.dispatch(request, call_next)
    call_next.assert_awaited_once()


async def test_dispatch_uses_bearer_hint_when_no_actor() -> None:
    mw = _make_middleware()
    settings = _make_settings()
    redis = _make_redis()
    request = _make_request(
        settings=settings,
        redis_client=redis,
        actor=None,
        headers={"authorization": "Bearer eyJtoken123"},
    )
    call_next = AsyncMock(return_value=Response(status_code=200))
    await mw.dispatch(request, call_next)
    call_next.assert_awaited_once()


# ---------------------------------------------------------------------------
# _extract_actor_hint
# ---------------------------------------------------------------------------


def test_extract_actor_hint_from_api_key() -> None:
    request = MagicMock()
    request.headers = {"x-api-key": "sk-abcdefgh12345"}
    assert _extract_actor_hint(request) == "apikey:sk-abcde"


def test_extract_actor_hint_from_bearer() -> None:
    request = MagicMock()
    request.headers = {"authorization": "Bearer eyJtoken12345"}
    assert _extract_actor_hint(request) == "bearer:eyJtoken"


def test_extract_actor_hint_from_bearer_no_api_key() -> None:
    request = MagicMock()
    request.headers = {"authorization": "Basic xyz"}
    result = _extract_actor_hint(request)
    assert result is None


def test_extract_actor_hint_no_headers() -> None:
    request = MagicMock()
    request.headers = {}
    assert _extract_actor_hint(request) is None


# ---------------------------------------------------------------------------
# _rate_limit_response
# ---------------------------------------------------------------------------


def test_rate_limit_response_sustained() -> None:
    r = _rate_limit_response("user:1", 101, 100, 60, "sustained")
    assert r.status_code == 429
    assert "sustained" in r.body.decode()


def test_rate_limit_response_burst() -> None:
    r = _rate_limit_response("user:1", 21, 20, 1, "burst")
    assert r.status_code == 429
    assert "burst" in r.body.decode()
    assert r.headers["Retry-After"] == "1"
