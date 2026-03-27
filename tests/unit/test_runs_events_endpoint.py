from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from syndicateclaw.api.dependencies import get_current_actor, get_db_session
from syndicateclaw.api.routes.runs import router as runs_router


@pytest.mark.asyncio
async def test_get_run_events_returns_count_and_events() -> None:
    app = FastAPI()
    app.include_router(runs_router)

    row = SimpleNamespace(
        id="evt-1",
        event_type="WORKFLOW_STARTED",
        actor="alice",
        resource_type="workflow_run",
        resource_id="run-1",
        action="started",
        details={"k": "v"},
        created_at=datetime.now(UTC),
    )

    result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [row]))
    db = SimpleNamespace(execute=AsyncMock(return_value=result))

    app.dependency_overrides[get_current_actor] = lambda: "alice"
    app.dependency_overrides[get_db_session] = lambda: db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/runs/run-1/events")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["events"][0]["id"] == "evt-1"
