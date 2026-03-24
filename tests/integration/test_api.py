from __future__ import annotations

import os
import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _integration_env(monkeypatch):
    """Ensure required env vars are set for Settings() construction."""
    monkeypatch.setenv(
        "SYNDICATECLAW_DATABASE_URL",
        os.environ.get(
            "SYNDICATECLAW_DATABASE_URL",
            "postgresql+asyncpg://syndicateclaw:syndicateclaw@localhost:5432/syndicateclaw_test",
        ),
    )
    monkeypatch.setenv(
        "SYNDICATECLAW_SECRET_KEY",
        os.environ.get("SYNDICATECLAW_SECRET_KEY", "test-secret-key-not-for-production"),
    )
    monkeypatch.setenv("SYNDICATECLAW_ENVIRONMENT", "test")


@pytest.fixture()
async def client(_integration_env):
    """Create a test client with full app lifespan.

    Uses LifespanManager to properly trigger the app's startup/shutdown,
    which populates app.state with Settings, services, and DB connections.
    Skips gracefully if external dependencies (PostgreSQL, Redis) are not
    reachable.
    """
    import importlib
    import syndicateclaw.api.main as main_mod
    importlib.reload(main_mod)

    app = main_mod.create_app()
    try:
        async with LifespanManager(app) as manager:
            async with AsyncClient(
                transport=ASGITransport(app=manager.app), base_url="http://test"
            ) as ac:
                resp = await ac.get("/readyz")
                if resp.status_code != 200:
                    pytest.skip(
                        f"Integration dependencies not ready: {resp.json()}"
                    )
                yield ac
    except OSError as exc:
        pytest.skip(f"Integration test infrastructure unavailable: {exc}")
    except Exception as exc:
        if "Connect call failed" in str(exc) or "Connection refused" in str(exc):
            pytest.skip(f"Integration test infrastructure unavailable: {exc}")
        raise


class TestHealthCheck:
    async def test_health_check(self, client: AsyncClient):
        resp = await client.get("/healthz")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data


class TestWorkflowCRUD:
    async def test_create_workflow(self, client: AsyncClient):
        payload = {
            "name": "integration-test-wf",
            "version": "1.0.0",
            "description": "Created by integration test",
            "nodes": [
                {"id": "start", "name": "Start", "node_type": "START", "handler": "start"},
                {"id": "end", "name": "End", "node_type": "END", "handler": "end"},
            ],
            "edges": [{"source_node_id": "start", "target_node_id": "end"}],
        }
        resp = await client.post("/api/v1/workflows/", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "integration-test-wf"
        assert "id" in data

    async def test_list_workflows(self, client: AsyncClient):
        resp = await client.get("/api/v1/workflows/")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestMemoryCRUD:
    async def test_memory_crud(self, client: AsyncClient):
        create_payload = {
            "namespace": "test-ns",
            "key": "test-key",
            "value": {"data": "integration-test"},
            "memory_type": "SEMANTIC",
            "source": "integration-test",
        }
        resp = await client.post("/api/v1/memory/", json=create_payload)
        assert resp.status_code == 201
        record = resp.json()
        record_id = record["id"]
        assert record["namespace"] == "test-ns"

        resp = await client.get(f"/api/v1/memory/test-ns/test-key")
        assert resp.status_code == 200
        assert resp.json()["id"] == record_id

        update_payload = {"value": {"data": "updated"}, "confidence": 0.8}
        resp = await client.put(f"/api/v1/memory/{record_id}", json=update_payload)
        assert resp.status_code == 200

        resp = await client.delete(f"/api/v1/memory/{record_id}")
        assert resp.status_code == 204


class TestApprovalLifecycle:
    async def test_approval_lifecycle(self, client: AsyncClient):
        wf_payload = {
            "name": "approval-test-wf",
            "version": "1.0.0",
            "nodes": [
                {"id": "start", "name": "Start", "node_type": "START", "handler": "start"},
                {"id": "end", "name": "End", "node_type": "END", "handler": "end"},
            ],
            "edges": [{"source_node_id": "start", "target_node_id": "end"}],
        }
        wf_resp = await client.post("/api/v1/workflows/", json=wf_payload)
        if wf_resp.status_code != 201:
            pytest.skip("Could not create workflow for approval test")

        resp = await client.get("/api/v1/approvals/")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
