"""Unit tests for api/routes/audit.py using FastAPI TestClient."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from syndicateclaw.api.dependencies import get_current_actor, get_db_session
from syndicateclaw.api.routes.audit import router


def _make_audit_event(**kwargs: Any) -> MagicMock:
    row = MagicMock()
    defaults = {
        "id": "evt-1",
        "event_type": "WORKFLOW_STARTED",
        "actor": "actor-1",
        "resource_type": "workflow",
        "resource_id": "wf-1",
        "action": "start",
        "details": {},
        "parent_event_id": None,
        "trace_id": "trace-1",
        "span_id": None,
        "created_at": datetime.now(UTC),
    }
    defaults.update(kwargs)
    for k, v in defaults.items():
        setattr(row, k, v)
    return row


def _make_app(*, scalars_return: list[Any] | None = None) -> tuple[FastAPI, MagicMock]:
    app = FastAPI()
    app.include_router(router)

    mock_db = AsyncMock()
    result = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = scalars_return or []
    result.scalars.return_value = scalars_mock
    mock_db.execute = AsyncMock(return_value=result)

    app.dependency_overrides[get_current_actor] = lambda: "test-actor"
    app.dependency_overrides[get_db_session] = lambda: mock_db
    return app, mock_db


def test_query_audit_events_returns_empty() -> None:
    app, _ = _make_app()
    with TestClient(app) as client:
        resp = client.get("/api/v1/audit/")
        assert resp.status_code == 200
    assert resp.json() == []


def test_query_audit_events_with_filters() -> None:
    evt = _make_audit_event()
    app, _ = _make_app(scalars_return=[evt])
    client = TestClient(app)
    resp = client.get(
        "/api/v1/audit/",
        params={
            "event_type": "WORKFLOW_STARTED",
            "actor": "actor-1",
            "resource_type": "workflow",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["actor"] == "actor-1"


def test_query_audit_events_with_time_range() -> None:
    evt = _make_audit_event()
    app, _ = _make_app(scalars_return=[evt])
    client = TestClient(app)
    resp = client.get(
        "/api/v1/audit/",
        params={
            "start_time": "2024-01-01T00:00:00Z",
            "end_time": "2025-01-01T00:00:00Z",
        },
    )
    assert resp.status_code == 200


def test_get_events_by_trace_found() -> None:
    evt = _make_audit_event(trace_id="trace-abc")
    app, _ = _make_app(scalars_return=[evt])
    with TestClient(app) as client:
        resp = client.get("/api/v1/audit/trace/trace-abc")
        assert resp.status_code == 200
    assert resp.json()[0]["trace_id"] == "trace-abc"


def test_get_events_by_trace_not_found_returns_404() -> None:
    app, _ = _make_app(scalars_return=[])
    with TestClient(app) as client:
        resp = client.get("/api/v1/audit/trace/missing-trace")
        assert resp.status_code == 404


def test_get_run_timeline_returns_events() -> None:
    evt = _make_audit_event(resource_id="run-123")
    app, _ = _make_app(scalars_return=[evt])
    with TestClient(app) as client:
        resp = client.get("/api/v1/audit/runs/run-123/timeline")
        assert resp.status_code == 200
    assert resp.json()[0]["resource_id"] == "run-123"


def test_get_run_timeline_empty() -> None:
    app, _ = _make_app(scalars_return=[])
    with TestClient(app) as client:
        resp = client.get("/api/v1/audit/runs/no-events/timeline")
        assert resp.status_code == 200
    assert resp.json() == []
