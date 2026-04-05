"""Unit tests for api/routes/agents.py using FastAPI TestClient."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from syndicateclaw.api.dependencies import (
    get_actor_org,
    get_agent_service,
    get_current_actor,
    get_db_session,
)
from syndicateclaw.api.routes.agents import router
from syndicateclaw.services.agent_service import (
    AgentConflictError,
    AgentNotFoundError,
    AgentOwnershipError,
)


def _make_agent(**kwargs: Any) -> MagicMock:
    row = MagicMock()
    defaults = {
        "id": "agent-1",
        "name": "test-agent",
        "description": "A test agent",
        "namespace": "default",
        "capabilities": ["chat"],
        "metadata_": {},
        "status": "ACTIVE",
        "registered_by": "actor-1",
        "heartbeat_at": None,
        "deregistered_at": None,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    defaults.update(kwargs)
    for k, v in defaults.items():
        setattr(row, k, v)
    return row


def _make_app(agent_svc: Any = None) -> FastAPI:
    app = FastAPI()
    app.include_router(router)

    mock_db = AsyncMock()
    result = MagicMock()
    scalar = MagicMock()
    scalar.return_value = 0
    result.scalar.return_value = 0
    mock_db.execute = AsyncMock(return_value=result)

    if agent_svc is None:
        agent_svc = AsyncMock()

    app.dependency_overrides[get_current_actor] = lambda: "test-actor"
    app.dependency_overrides[get_agent_service] = lambda: agent_svc
    app.dependency_overrides[get_db_session] = lambda: mock_db
    app.dependency_overrides[get_actor_org] = lambda: None  # no org
    return app


# ---------------------------------------------------------------------------
# register_agent
# ---------------------------------------------------------------------------


def test_register_agent_success() -> None:
    agent = _make_agent()
    svc = AsyncMock()
    svc.register = AsyncMock(return_value=agent)
    with TestClient(_make_app(svc)) as client:
        resp = client.post(
            "/api/v1/agents",
            json={
                "name": "bot",
                "namespace": "default",
                "capabilities": ["chat"],
                "metadata": {},
            },
        )
    assert resp.status_code == 201


def test_register_agent_conflict_returns_409() -> None:
    svc = AsyncMock()
    svc.register = AsyncMock(side_effect=AgentConflictError("duplicate"))
    with TestClient(_make_app(svc)) as client:
        resp = client.post("/api/v1/agents", json={"name": "bot", "namespace": "default"})
        assert resp.status_code == 409


def test_register_agent_value_error_returns_422() -> None:
    svc = AsyncMock()
    svc.register = AsyncMock(side_effect=ValueError("bad name"))
    with TestClient(_make_app(svc)) as client:
        resp = client.post("/api/v1/agents", json={"name": "bot", "namespace": "default"})
        assert resp.status_code == 422


def test_register_agent_cross_namespace_forbidden() -> None:
    app = FastAPI()
    app.include_router(router)
    mock_db = AsyncMock()
    result = MagicMock()
    result.scalar.return_value = 0
    mock_db.execute = AsyncMock(return_value=result)
    actor_org = MagicMock()
    actor_org.namespace = "org-ns"
    actor_org.quotas = {}  # no quota limits
    app.dependency_overrides[get_current_actor] = lambda: "actor-1"
    app.dependency_overrides[get_agent_service] = lambda: AsyncMock()
    app.dependency_overrides[get_db_session] = lambda: mock_db
    app.dependency_overrides[get_actor_org] = lambda: actor_org

    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/agents",
            json={"name": "bot", "namespace": "different-ns"},
        )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# list_agents
# ---------------------------------------------------------------------------


def test_list_agents_returns_rows() -> None:
    agent = _make_agent()
    svc = AsyncMock()
    svc.discover = AsyncMock(return_value=[agent])
    with TestClient(_make_app(svc)) as client:
        resp = client.get("/api/v1/agents")
        assert resp.status_code == 200
        assert len(resp.json()) == 1


# ---------------------------------------------------------------------------
# get_agent
# ---------------------------------------------------------------------------


def test_get_agent_found() -> None:
    agent = _make_agent()
    svc = AsyncMock()
    svc.get = AsyncMock(return_value=agent)
    with TestClient(_make_app(svc)) as client:
        resp = client.get("/api/v1/agents/agent-1")
        assert resp.status_code == 200


def test_get_agent_not_found_returns_404() -> None:
    svc = AsyncMock()
    svc.get = AsyncMock(side_effect=AgentNotFoundError("not found"))
    with TestClient(_make_app(svc)) as client:
        resp = client.get("/api/v1/agents/missing")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# update_agent
# ---------------------------------------------------------------------------


def test_update_agent_success() -> None:
    agent = _make_agent()
    svc = AsyncMock()
    svc.update = AsyncMock(return_value=agent)
    with TestClient(_make_app(svc)) as client:
        resp = client.put("/api/v1/agents/agent-1", json={"name": "new-name"})
        assert resp.status_code == 200


def test_update_agent_not_found_returns_404() -> None:
    svc = AsyncMock()
    svc.update = AsyncMock(side_effect=AgentNotFoundError("not found"))
    with TestClient(_make_app(svc)) as client:
        resp = client.put("/api/v1/agents/missing", json={})
        assert resp.status_code == 404


def test_update_agent_ownership_error_returns_403() -> None:
    svc = AsyncMock()
    svc.update = AsyncMock(side_effect=AgentOwnershipError("not owner"))
    with TestClient(_make_app(svc)) as client:
        resp = client.put("/api/v1/agents/agent-1", json={})
        assert resp.status_code == 403


def test_update_agent_conflict_returns_409() -> None:
    svc = AsyncMock()
    svc.update = AsyncMock(side_effect=AgentConflictError("dup name"))
    with TestClient(_make_app(svc)) as client:
        resp = client.put("/api/v1/agents/agent-1", json={"name": "taken"})
        assert resp.status_code == 409


def test_update_agent_value_error_returns_422() -> None:
    svc = AsyncMock()
    svc.update = AsyncMock(side_effect=ValueError("invalid"))
    with TestClient(_make_app(svc)) as client:
        resp = client.put("/api/v1/agents/agent-1", json={"name": "x"})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# deregister_agent
# ---------------------------------------------------------------------------


def test_deregister_agent_success() -> None:
    agent = _make_agent()
    svc = AsyncMock()
    svc.deregister = AsyncMock(return_value=agent)
    with TestClient(_make_app(svc)) as client:
        resp = client.delete("/api/v1/agents/agent-1")
        assert resp.status_code == 200


def test_deregister_agent_not_found_returns_404() -> None:
    svc = AsyncMock()
    svc.deregister = AsyncMock(side_effect=AgentNotFoundError("not found"))
    with TestClient(_make_app(svc)) as client:
        resp = client.delete("/api/v1/agents/missing")
        assert resp.status_code == 404


def test_deregister_agent_ownership_error_returns_403() -> None:
    svc = AsyncMock()
    svc.deregister = AsyncMock(side_effect=AgentOwnershipError("not owner"))
    with TestClient(_make_app(svc)) as client:
        resp = client.delete("/api/v1/agents/agent-1")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# heartbeat_agent
# ---------------------------------------------------------------------------


def test_heartbeat_agent_success() -> None:
    agent = _make_agent()
    svc = AsyncMock()
    svc.heartbeat = AsyncMock(return_value=agent)
    with TestClient(_make_app(svc)) as client:
        resp = client.post("/api/v1/agents/agent-1/heartbeat")
        assert resp.status_code == 200


def test_heartbeat_agent_not_found_returns_404() -> None:
    svc = AsyncMock()
    svc.heartbeat = AsyncMock(side_effect=AgentNotFoundError("not found"))
    with TestClient(_make_app(svc)) as client:
        resp = client.post("/api/v1/agents/missing/heartbeat")
        assert resp.status_code == 404


def test_heartbeat_agent_ownership_error_returns_403() -> None:
    svc = AsyncMock()
    svc.heartbeat = AsyncMock(side_effect=AgentOwnershipError("not owner"))
    with TestClient(_make_app(svc)) as client:
        resp = client.post("/api/v1/agents/agent-1/heartbeat")
        assert resp.status_code == 403
