from __future__ import annotations

import time
from typing import Any

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from ulid import ULID

from syndicateclaw.observability.metrics import (
    http_request_duration_seconds,
    http_requests_total,
)

logger = structlog.get_logger(__name__)


class PrometheusMetricsMiddleware(BaseHTTPMiddleware):
    """Record HTTP request counts and latency (low-cardinality path label)."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        t0 = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - t0
        route = request.url.path
        http_request_duration_seconds.labels(method=request.method, route=route).observe(elapsed)
        http_requests_total.labels(
            method=request.method,
            route=route,
            status_code=str(response.status_code),
        ).inc()
        return response


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attach a unique X-Request-ID (ULID) to every request and response."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(ULID())
        request.state.request_id = request_id

        structlog.contextvars.bind_contextvars(request_id=request_id)

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id

        structlog.contextvars.unbind_contextvars("request_id")
        return response


class AuditMiddleware(BaseHTTPMiddleware):
    """Log every API request to the audit log with method, path, actor, status, and duration."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        t0 = time.monotonic()
        response: Response | None = None
        error: str | None = None

        try:
            response = await call_next(request)
        except Exception as exc:
            error = str(exc)
            raise
        finally:
            duration_ms = round((time.monotonic() - t0) * 1000, 2)
            actor = getattr(request.state, "actor", "anonymous")
            status_code = response.status_code if response else 500

            log_data: dict[str, Any] = {
                "method": request.method,
                "path": request.url.path,
                "status": status_code,
                "duration_ms": duration_ms,
                "actor": actor,
            }
            if error:
                log_data["error"] = error

            request_id = getattr(request.state, "request_id", None)
            if request_id:
                log_data["request_id"] = request_id

            logger.info("http.request", **log_data)

            audit_service = getattr(request.app.state, "audit_service", None)
            if audit_service is not None and hasattr(audit_service, "emit"):
                from syndicateclaw.models import AuditEvent, AuditEventType

                event = AuditEvent(
                    event_type=AuditEventType.HTTP_REQUEST,
                    actor=actor,
                    resource_type="http",
                    resource_id=request.url.path,
                    action=request.method,
                    details=log_data,
                )
                try:
                    await audit_service.emit(event)
                except Exception:
                    logger.warning("audit.middleware_emit_failed", exc_info=True)

        return response
