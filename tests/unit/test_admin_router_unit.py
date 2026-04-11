from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from syndicateclaw.api.dependencies import get_current_actor
from syndicateclaw.api.routers.admin import router
from syndicateclaw.inference.types import InferenceCapability, ProviderStatus
from syndicateclaw.models import ApprovalStatus


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


class _RowsResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None

    def scalars(self):
        return SimpleNamespace(all=lambda: self._rows)


class _Session:
    def __init__(self, results):
        self._results = iter(results)

    async def execute(self, _stmt):
        return next(self._results)


class _SessionContext:
    def __init__(self, results):
        self._session = _Session(results)

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _session_factory(*results):
    def factory():
        return _SessionContext(results)

    return factory


def _make_app(**state_values) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_actor] = lambda: "admin:ops"
    for key, value in state_values.items():
        setattr(app.state, key, value)
    return app


@pytest.fixture(scope="session", autouse=True)
async def db_engine():
    """Override the global DB fixture so these unit tests stay DB-free."""
    yield None


def test_dashboard_returns_real_aggregates() -> None:
    approval_service = SimpleNamespace(get_pending=AsyncMock(return_value=[1, 2, 3]))
    connector_registry = SimpleNamespace(
        statuses=lambda: [
            SimpleNamespace(connected=True, errors=1),
            SimpleNamespace(connected=False, errors=2),
        ]
    )
    app = _make_app(
        approval_service=approval_service,
        connector_registry=connector_registry,
        session_factory=_session_factory(_ScalarResult(4), _ScalarResult(2)),
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/admin/dashboard")

    assert response.status_code == 200
    assert response.json() == {
        "connectors_total": 2,
        "connectors_connected": 1,
        "connectors_errors": 3,
        "pending_approvals": 3,
        "workflow_runs_active": 4,
        "memory_namespaces": 2,
    }


def test_approval_queue_returns_pending_items() -> None:
    approval_service = SimpleNamespace(
        get_pending=AsyncMock(
            return_value=[
                SimpleNamespace(
                    id="apr-1",
                    requested_by="alice",
                    action_description="deploy release",
                    tool_name="deploy",
                    context={"reason": "prod deploy"},
                    created_at=datetime.now(UTC),
                    status=ApprovalStatus.PENDING,
                )
            ]
        )
    )
    app = _make_app(approval_service=approval_service)

    with TestClient(app) as client:
        response = client.get("/api/v1/admin/approvals")

    assert response.status_code == 200
    assert response.json()[0]["id"] == "apr-1"
    approval_service.get_pending.assert_awaited_once_with("admin:ops")


def test_approval_decision_calls_service() -> None:
    decided_at = datetime.now(UTC)
    approval_service = SimpleNamespace(
        approve=AsyncMock(
            return_value=SimpleNamespace(
                id="apr-1",
                status=ApprovalStatus.APPROVED,
                decided_by="admin:ops",
                decided_at=decided_at,
            )
        )
    )
    app = _make_app(approval_service=approval_service)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/admin/approvals/apr-1/decide",
            json={"accepted": True, "reason": "looks good"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "APPROVED"
    approval_service.approve.assert_awaited_once_with("apr-1", "admin:ops", "looks good")


def test_workflow_runs_endpoints_return_real_rows() -> None:
    run = SimpleNamespace(
        id="run-1",
        status="RUNNING",
        initiated_by="alice",
        created_at=datetime.now(UTC),
    )
    app = _make_app(
        session_factory=_session_factory(
            _RowsResult([(run, "Primary Workflow")]),
            _RowsResult([(run, "Primary Workflow")]),
        )
    )

    with TestClient(app) as client:
        list_response = client.get("/api/v1/admin/workflows/runs")
        detail_response = client.get("/api/v1/admin/workflows/runs/run-1")

    assert list_response.status_code == 200
    assert list_response.json()[0]["run_id"] == "run-1"
    assert detail_response.status_code == 200
    assert detail_response.json()["workflow_name"] == "Primary Workflow"


def test_memory_namespace_endpoints_use_service() -> None:
    memory_service = SimpleNamespace(
        list_namespaces=AsyncMock(
            return_value=[
                {
                    "namespace": "agent:facts",
                    "prefix": "agent",
                    "records": 3,
                    "last_updated_at": datetime.now(UTC),
                }
            ]
        ),
        purge_namespace=AsyncMock(return_value=3),
    )
    app = _make_app(memory_service=memory_service)

    with TestClient(app) as client:
        list_response = client.get("/api/v1/admin/memory/namespaces", params={"prefix": "agent"})
        purge_response = client.delete("/api/v1/admin/memory/namespaces/agent:facts")

    assert list_response.status_code == 200
    assert list_response.json()[0]["namespace"] == "agent:facts"
    assert purge_response.status_code == 200
    assert purge_response.json()["purged_count"] == 3
    memory_service.list_namespaces.assert_awaited_once_with("agent")
    memory_service.purge_namespace.assert_awaited_once_with("agent:facts", "admin:ops")


def test_audit_endpoint_merges_audit_and_decision_rows() -> None:
    audit_row = SimpleNamespace(
        id="evt-1",
        actor="alice",
        resource_type="workflow",
        event_type="WORKFLOW_STARTED",
        action="start",
        created_at=datetime.now(UTC),
        details={"trace_id": "t-1"},
    )
    decision_row = SimpleNamespace(
        id="dec-1",
        actor="bob",
        domain="APPROVAL",
        effect="allow",
        decision_type="approval_review",
        created_at=datetime.now(UTC),
        justification="approved",
        confidence=1.0,
        inputs={"resource": "deploy"},
        rules_evaluated=[],
        matched_rule=None,
        side_effects=[],
        trace_id="t-2",
        run_id=None,
        node_execution_id=None,
    )
    app = _make_app(
        session_factory=_session_factory(
            _RowsResult([audit_row]),
            _RowsResult([decision_row]),
        )
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/admin/audit")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 2
    assert {entry["id"] for entry in payload} == {"evt-1", "dec-1"}


def test_provider_summary_endpoint_returns_registry_state() -> None:
    provider = SimpleNamespace(
        id="p1",
        name="Provider One",
        enabled=True,
        capabilities=[InferenceCapability.CHAT, InferenceCapability.EMBEDDING],
    )
    loader = SimpleNamespace(current=lambda: (SimpleNamespace(providers=[provider]), "v1"))
    registry = SimpleNamespace(
        is_runtime_disabled=lambda provider_id: False,
        health_status=lambda provider_id: ProviderStatus.ACTIVE,
    )
    catalog = SimpleNamespace(
        models_for_capability_and_provider=lambda capability, provider_id: (
            ("chat-1", "chat-2") if capability == InferenceCapability.CHAT else ("embed-1",)
        )
    )
    app = _make_app(
        provider_config_loader=loader,
        provider_registry=registry,
        inference_catalog=catalog,
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/admin/providers")

    assert response.status_code == 200
    assert response.json() == [
        {
            "provider_id": "p1",
            "name": "Provider One",
            "enabled": True,
            "model_count": 3,
            "status": "active",
        }
    ]


def test_api_key_endpoints_use_service() -> None:
    created_at = datetime.now(UTC)
    api_key_service = SimpleNamespace(
        list_keys=AsyncMock(
            return_value=[
                {
                    "id": "key-1",
                    "key_prefix": "sc-abc123",
                    "description": "build token",
                    "revoked": False,
                    "last_used_at": None,
                    "created_at": created_at.isoformat(),
                }
            ]
        ),
        create_api_key=AsyncMock(return_value=("key-2", "sc-secret")),
        revoke_key=AsyncMock(return_value=True),
    )
    app = _make_app(api_key_service=api_key_service)

    with TestClient(app) as client:
        list_response = client.get("/api/v1/admin/api-keys")
        create_response = client.post(
            "/api/v1/admin/api-keys",
            json={"name": "deploy key", "expires_at": created_at.isoformat()},
        )
        revoke_response = client.delete("/api/v1/admin/api-keys/key-2")

    assert list_response.status_code == 200
    assert list_response.json()[0]["name"] == "build token"
    assert create_response.status_code == 200
    assert create_response.json()["key_id"] == "key-2"
    assert create_response.json()["key"] == "sc-secret"
    assert revoke_response.status_code == 200
    assert revoke_response.json()["revoked"] is True
    api_key_service.create_api_key.assert_awaited_once()
    api_key_service.revoke_key.assert_awaited_once_with("key-2", "admin:ops")


def test_revoke_api_key_returns_404_when_missing() -> None:
    api_key_service = SimpleNamespace(revoke_key=AsyncMock(return_value=False))
    app = _make_app(api_key_service=api_key_service)

    with TestClient(app) as client:
        response = client.delete("/api/v1/admin/api-keys/missing")

    assert response.status_code == 404
    assert response.json()["detail"] == "api key not found"
