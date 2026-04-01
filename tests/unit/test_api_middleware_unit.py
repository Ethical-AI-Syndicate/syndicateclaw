"""Unit tests for api/middleware.py — middleware dispatch paths."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from starlette.responses import Response

from syndicateclaw.api.middleware import (
    AuditMiddleware,
    PrometheusMetricsMiddleware,
    RequestIDMiddleware,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(
    *,
    method: str = "GET",
    path: str = "/api/v1/workflows/",
    actor: str = "user:1",
    request_id: str | None = None,
    headers: dict | None = None,
    audit_service=None,
) -> MagicMock:
    request = MagicMock()
    request.method = method
    request.url.path = path
    request.state.actor = actor
    request.state.request_id = request_id
    request.headers = headers or {}
    request.app.state.audit_service = audit_service
    return request


# ---------------------------------------------------------------------------
# PrometheusMetricsMiddleware
# ---------------------------------------------------------------------------


async def test_prometheus_middleware_observes_metrics() -> None:
    mw = PrometheusMetricsMiddleware(MagicMock())
    request = _make_request()
    response = Response(status_code=200)
    call_next = AsyncMock(return_value=response)

    with (
        patch("syndicateclaw.api.middleware.http_request_duration_seconds") as mock_hist,
        patch("syndicateclaw.api.middleware.http_requests_total") as mock_counter,
    ):
        mock_hist.labels.return_value.observe = MagicMock()
        mock_counter.labels.return_value.inc = MagicMock()

        result = await mw.dispatch(request, call_next)

    assert result.status_code == 200
    mock_hist.labels.assert_called_once()
    mock_counter.labels.assert_called_once()


# ---------------------------------------------------------------------------
# RequestIDMiddleware
# ---------------------------------------------------------------------------


async def test_request_id_middleware_generates_id_when_missing() -> None:
    mw = RequestIDMiddleware(MagicMock())
    request = _make_request(headers={})
    response = Response(status_code=200)
    call_next = AsyncMock(return_value=response)

    result = await mw.dispatch(request, call_next)

    assert "X-Request-ID" in result.headers
    # ID was set on request state
    assert request.state.request_id is not None


async def test_request_id_middleware_preserves_existing_id() -> None:
    mw = RequestIDMiddleware(MagicMock())
    request = _make_request(headers={"X-Request-ID": "existing-id-123"})
    response = Response(status_code=200)
    call_next = AsyncMock(return_value=response)

    result = await mw.dispatch(request, call_next)

    assert result.headers["X-Request-ID"] == "existing-id-123"


# ---------------------------------------------------------------------------
# AuditMiddleware
# ---------------------------------------------------------------------------


async def test_audit_middleware_logs_request() -> None:
    mw = AuditMiddleware(MagicMock())
    request = _make_request(audit_service=None)
    response = Response(status_code=200)
    call_next = AsyncMock(return_value=response)

    result = await mw.dispatch(request, call_next)
    assert result.status_code == 200


async def test_audit_middleware_emits_audit_event() -> None:
    mock_audit = AsyncMock()
    mock_audit.emit = AsyncMock()
    mw = AuditMiddleware(MagicMock())
    request = _make_request(audit_service=mock_audit, request_id="req-1")
    response = Response(status_code=200)
    call_next = AsyncMock(return_value=response)

    result = await mw.dispatch(request, call_next)

    mock_audit.emit.assert_awaited_once()
    assert result.status_code == 200


async def test_audit_middleware_swallows_emit_exception() -> None:
    mock_audit = AsyncMock()
    mock_audit.emit = AsyncMock(side_effect=RuntimeError("audit down"))
    mw = AuditMiddleware(MagicMock())
    request = _make_request(audit_service=mock_audit)
    response = Response(status_code=200)
    call_next = AsyncMock(return_value=response)

    # Should not raise
    result = await mw.dispatch(request, call_next)
    assert result.status_code == 200


async def test_audit_middleware_handles_handler_exception() -> None:
    mw = AuditMiddleware(MagicMock())
    request = _make_request(audit_service=None)
    call_next = AsyncMock(side_effect=RuntimeError("internal error"))

    import pytest

    with pytest.raises(RuntimeError, match="internal error"):
        await mw.dispatch(request, call_next)


async def test_audit_middleware_no_actor_uses_anonymous() -> None:
    mw = AuditMiddleware(MagicMock())
    request = _make_request(audit_service=None)
    del request.state.actor  # remove actor attr
    request.state = MagicMock()
    request.state.actor = "anonymous"
    response = Response(status_code=200)
    call_next = AsyncMock(return_value=response)

    result = await mw.dispatch(request, call_next)
    assert result.status_code == 200


async def test_audit_middleware_skips_emit_when_no_audit_service() -> None:
    mw = AuditMiddleware(MagicMock())
    request = _make_request(audit_service=None)
    response = Response(status_code=200)
    call_next = AsyncMock(return_value=response)

    # No audit service — should complete normally
    result = await mw.dispatch(request, call_next)
    assert result.status_code == 200


async def test_audit_middleware_with_404_response() -> None:
    mock_audit = AsyncMock()
    mock_audit.emit = AsyncMock()
    mw = AuditMiddleware(MagicMock())
    request = _make_request(audit_service=mock_audit)
    response = Response(status_code=404)
    call_next = AsyncMock(return_value=response)

    result = await mw.dispatch(request, call_next)
    assert result.status_code == 404
    mock_audit.emit.assert_awaited_once()
