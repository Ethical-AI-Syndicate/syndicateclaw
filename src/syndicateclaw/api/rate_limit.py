"""Redis-backed sliding-window rate limiter with per-actor limits.

Uses a Redis sorted set per actor keyed by timestamp to implement a
sliding window. Burst is tracked separately as a short sub-window.
"""

from __future__ import annotations

import time

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = structlog.get_logger(__name__)

_RATE_LIMIT_SKIP_PATHS = {"/healthz", "/readyz", "/docs", "/openapi.json", "/redoc"}


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-actor sliding-window rate limiter backed by Redis.

    When Redis is unavailable, degrades open (allows requests) but logs a
    warning — this is a safety-over-availability tradeoff that should be
    revisited for hostile environments.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if request.url.path in _RATE_LIMIT_SKIP_PATHS:
            return await call_next(request)

        settings = getattr(request.app.state, "settings", None)
        redis = getattr(request.app.state, "redis_client", None)

        if settings is None or redis is None:
            return await call_next(request)

        actor = getattr(request.state, "actor", None)
        if actor is None:
            actor = _extract_actor_hint(request)

        if actor is None or actor == "anonymous":
            return await call_next(request)

        now = time.time()
        window = settings.rate_limit_window_seconds
        max_requests = settings.rate_limit_requests
        burst = settings.rate_limit_burst

        key = f"syndicateclaw:ratelimit:{actor}"
        burst_key = f"syndicateclaw:ratelimit:burst:{actor}"

        try:
            pipe = redis.pipeline(transaction=True)
            cutoff = now - window
            pipe.zremrangebyscore(key, "-inf", cutoff)
            pipe.zadd(key, {str(now): now})
            pipe.zcard(key)
            pipe.expire(key, window + 1)

            burst_cutoff = now - 1.0
            pipe.zremrangebyscore(burst_key, "-inf", burst_cutoff)
            pipe.zadd(burst_key, {str(now): now})
            pipe.zcard(burst_key)
            pipe.expire(burst_key, 2)

            results = await pipe.execute()
            window_count = results[2]
            burst_count = results[6]

        except Exception:
            logger.warning(
                "rate_limit.redis_unavailable",
                actor=actor,
                exc_info=True,
            )
            return await call_next(request)

        if window_count > max_requests:
            remaining = 0
            retry_after = int(window - (now - cutoff)) + 1
            logger.warning(
                "rate_limit.exceeded",
                actor=actor,
                window_count=window_count,
                max_requests=max_requests,
                kind="sustained",
            )
            return _rate_limit_response(
                actor, window_count, max_requests, retry_after, "sustained"
            )

        if burst_count > burst:
            logger.warning(
                "rate_limit.exceeded",
                actor=actor,
                burst_count=burst_count,
                burst_limit=burst,
                kind="burst",
            )
            return _rate_limit_response(actor, burst_count, burst, 1, "burst")

        response = await call_next(request)
        remaining = max(0, max_requests - window_count)
        response.headers["X-RateLimit-Limit"] = str(max_requests)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(int(now) + window)
        return response


def _rate_limit_response(
    actor: str, count: int, limit: int, retry_after: int, kind: str
) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={
            "detail": f"Rate limit exceeded ({kind}): {count}/{limit}",
            "retry_after": retry_after,
        },
        headers={
            "Retry-After": str(retry_after),
            "X-RateLimit-Limit": str(limit),
            "X-RateLimit-Remaining": "0",
        },
    )


def _extract_actor_hint(request: Request) -> str | None:
    """Try to extract an actor hint from auth headers without full decode."""
    api_key = request.headers.get("x-api-key")
    if api_key:
        return f"apikey:{api_key[:8]}"
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        return f"bearer:{auth[7:15]}"
    return None
