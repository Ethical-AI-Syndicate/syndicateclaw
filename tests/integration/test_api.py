from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.integration


class TestHealthCheck:
    async def test_health_check(self, client: AsyncClient):
        resp = await client.get("/healthz")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data


class TestWorkflowCRUD:
    async def test_create_workflow(self, client: AsyncClient):
        wf_name = f"integration-test-wf-{uuid.uuid4().hex[:8]}"
        payload = {
            "name": wf_name,
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
        assert data["name"] == wf_name
        assert "id" in data

    async def test_list_workflows(self, client: AsyncClient):
        resp = await client.get("/api/v1/workflows/")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestMemoryCRUD:
    async def test_memory_crud(self, client: AsyncClient):
        ns = f"test-ns-{uuid.uuid4().hex[:8]}"
        key = f"test-key-{uuid.uuid4().hex[:8]}"
        create_payload = {
            "namespace": ns,
            "key": key,
            "value": {"data": "integration-test"},
            "memory_type": "SEMANTIC",
            "source": "integration-test",
            "access_policy": "default",
        }
        resp = await client.post("/api/v1/memory/", json=create_payload)
        assert resp.status_code == 201
        record = resp.json()
        record_id = record["id"]
        assert record["namespace"] == ns

        resp = await client.get(f"/api/v1/memory/{ns}/{key}")
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
            "name": f"approval-test-wf-{uuid.uuid4().hex[:8]}",
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
