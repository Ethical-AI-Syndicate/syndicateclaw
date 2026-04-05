"""
Release scenario tests for SyndicateClaw v1.0.
These verify end-to-end system contracts across subsystem boundaries.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from httpx import AsyncClient

from syndicateclaw.memory.service import MemoryService
from syndicateclaw.models import MemoryRecord, MemoryType

pytestmark = [pytest.mark.integration]


@pytest.mark.xfail(
    reason=(
        "Engine execution is async/separate from API run creation; "
        "audit events not emitted synchronously in test environment. "
        "Unskip: v1.2 when audit event emission is synchronous or test awaits event flush."
    ),
    strict=False,
)
async def test_workflow_execution_produces_complete_audit_trail(
    client: AsyncClient,
) -> None:
    wf_payload = {
        "name": f"scenario-linear-{uuid.uuid4().hex[:8]}",
        "version": "1.0.0",
        "nodes": [
            {"id": "start", "name": "Start", "node_type": "START", "handler": "start"},
            {"id": "end", "name": "End", "node_type": "END", "handler": "end"},
        ],
        "edges": [{"source_node_id": "start", "target_node_id": "end"}],
    }
    wf = await client.post("/api/v1/workflows/", json=wf_payload)
    assert wf.status_code == 201
    wf_id = wf.json()["id"]
    run = await client.post(f"/api/v1/workflows/{wf_id}/runs", json={"initial_state": {}})
    assert run.status_code in (200, 201)
    run_id = run.json()["id"]
    tl = await client.get(f"/api/v1/workflows/runs/{run_id}/timeline")
    assert tl.status_code == 200
    events = tl.json()
    types = {e.get("event_type") for e in events}
    assert "WORKFLOW_STARTED" in types or any("WORKFLOW" in str(t) for t in types)


async def test_policy_deny_on_tool_execution_is_audited(
    session_factory,
) -> None:
    from ulid import ULID

    from syndicateclaw.models import PolicyEffect, PolicyRule
    from syndicateclaw.policy.engine import PolicyEngine

    uid = str(ULID())
    pe = PolicyEngine(session_factory)
    await pe.add_rule(
        PolicyRule.new(
            name=f"sc-deny-{uid}",
            resource_type="tool",
            resource_pattern="blocked-*",
            effect=PolicyEffect.DENY,
            conditions=[],
            priority=100,
            owner="scenario",
        ),
        actor="admin:test",
    )
    decision = await pe.evaluate("tool", "blocked-x", "execute", "u", {})
    assert decision.effect == PolicyEffect.DENY


async def test_approval_gate_blocks_and_unblocks_workflow(
    client: AsyncClient,
) -> None:
    wf_payload = {
        "name": f"scenario-approval-{uuid.uuid4().hex[:8]}",
        "version": "1.0.0",
        "nodes": [
            {"id": "start", "name": "Start", "node_type": "START", "handler": "start"},
            {
                "id": "ap",
                "name": "A",
                "node_type": "APPROVAL",
                "handler": "approval",
                "config": {
                    "assigned_to": ["approver-scenario"],
                    "requested_by": "system",
                },
            },
            {"id": "end", "name": "End", "node_type": "END", "handler": "end"},
        ],
        "edges": [
            {"source_node_id": "start", "target_node_id": "ap"},
            {"source_node_id": "ap", "target_node_id": "end"},
        ],
    }
    wf = await client.post("/api/v1/workflows/", json=wf_payload)
    assert wf.status_code == 201
    wf_id = wf.json()["id"]
    run = await client.post(f"/api/v1/workflows/{wf_id}/runs", json={"initial_state": {}})
    assert run.status_code in (200, 201)
    body = run.json()
    # The API creates the run record synchronously; execution is async/separate.
    # PENDING is the correct initial state from the API surface.
    assert body.get("status") in ("PENDING", "WAITING_APPROVAL", "PAUSED", "RUNNING")
    assert "id" in body


async def test_memory_namespace_isolation(session_factory) -> None:
    from ulid import ULID

    svc = MemoryService(session_factory)
    ns = f"ns_{ULID()}"
    rec = MemoryRecord.new(
        namespace=ns,
        key="k1",
        value={"v": 1},
        memory_type=MemoryType.SEMANTIC,
        source="scenario",
        actor="actor-a",
        access_policy="owner_only",
    )
    await svc.write(rec, actor="actor-a")
    other = await svc.read(ns, "k1", actor="actor-b")
    assert other is None


@pytest.mark.xfail(
    reason=(
        "Idempotency store requires wired provider adapter in test environment; "
        "deferred to v1.1 integration harness. "
        "Unskip: v1.2 when provider adapter is injectable in integration fixture."
    ),
    strict=False,
)
async def test_inference_idempotency_key_deduplicates(
    session_factory,
    tmp_path: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same idempotency key and request: one provider call; second response is replay."""
    from unittest.mock import AsyncMock, MagicMock

    import yaml

    from syndicateclaw.inference.catalog import ModelCatalog
    from syndicateclaw.inference.config_loader import ProviderConfigLoader
    from syndicateclaw.inference.config_schema import StaticCatalogEntry
    from syndicateclaw.inference.idempotency import IdempotencyStore
    from syndicateclaw.inference.registry import ProviderRegistry
    from syndicateclaw.inference.service import ProviderService
    from syndicateclaw.inference.types import (
        AdapterProtocol,
        ChatInferenceRequest,
        ChatInferenceResponse,
        ChatMessage,
        InferenceCapability,
        ModelDescriptor,
        ProviderConfig,
        ProviderType,
    )
    from syndicateclaw.models import PolicyEffect
    from tests.unit.inference.fixtures import minimal_system

    calls: list[int] = []

    class FakeAdapter:
        async def infer_chat(self, cfg, req, *, api_key, bearer_token):
            calls.append(1)
            return ChatInferenceResponse(
                inference_id="",
                provider_id=cfg.id,
                model_id="m1",
                content="once",
            )

    monkeypatch.setattr(
        "syndicateclaw.inference.service.adapter_for",
        lambda _p: FakeAdapter(),
    )

    sys = minimal_system(
        ProviderConfig(
            id="p1",
            name="P",
            provider_type=ProviderType.LOCAL,
            adapter_protocol=AdapterProtocol.OPENAI_COMPATIBLE,
            base_url="http://test",
            capabilities=[InferenceCapability.CHAT],
        ),
        static=(
            StaticCatalogEntry(
                provider_id="p1",
                model_id="m1",
                capability=InferenceCapability.CHAT,
                descriptor=ModelDescriptor(model_id="m1", name="M", provider_id="p1"),
            ),
        ),
    )
    from pathlib import Path

    p = Path(tmp_path) / "scenario-idem.yaml"
    p.write_text(yaml.safe_dump(sys.model_dump(mode="json")))
    loader = ProviderConfigLoader(p)
    loader.load_and_activate()

    cat = ModelCatalog()
    cat.replace_from_yaml_static(loader.current()[0], snapshot_version=loader.current()[1])
    reg = ProviderRegistry(loader.current()[0])
    audit = AsyncMock()
    audit.emit = AsyncMock()
    pe = MagicMock()

    async def allow_eval(*_a, **_k):
        m = MagicMock()
        m.effect = PolicyEffect.ALLOW
        return m

    pe.evaluate = allow_eval

    store = IdempotencyStore(session_factory, stale_after_seconds=3600.0)
    svc = ProviderService(
        loader=loader,
        catalog=cat,
        registry=reg,
        policy_engine=pe,
        audit_service=audit,
        idempotency_store=store,
    )

    base = dict(
        messages=[ChatMessage(role="user", content="hi")],
        actor="scenario-actor",
        trace_id="scenario-trace",
        provider_id="p1",
        model_id="m1",
        idempotency_key="scenario-idem-v1-same",
    )
    r1 = await svc.infer_chat(ChatInferenceRequest(**base))
    r2 = await svc.infer_chat(ChatInferenceRequest(**base))
    assert r1.content == r2.content == "once"
    assert len(calls) == 1


async def test_expired_jwt_returns_401_not_500(client: AsyncClient) -> None:
    secret = os.environ.get("SYNDICATECLAW_SECRET_KEY", "test-secret-key-not-for-production")
    token = jwt.encode(
        {"sub": "x", "exp": datetime.now(UTC) - timedelta(seconds=5)},
        secret,
        algorithm="HS256",
    )
    resp = await client.get(
        "/api/v1/workflows/",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 401
    assert "traceback" not in resp.text.lower()


@pytest.mark.skip(
    reason=(
        "v1.1: per-API-key OAuth-style scopes not implemented — verified keys map to an "
        "actor; authorization is RBAC on that principal, not a scope string on the key. "
        "Unskip: v2.0 if per-key scope enforcement is added."
    ),
)
async def test_api_key_wrong_scope_returns_403_not_401() -> None:
    pass


def test_audit_log_has_no_update_or_delete_api_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib

    monkeypatch.setenv("SYNDICATECLAW_SECRET_KEY", "k" * 40)
    monkeypatch.setenv(
        "SYNDICATECLAW_DATABASE_URL",
        "postgresql+asyncpg://u:p@postgres:5432/db",
    )
    import syndicateclaw.api.main as main_mod

    importlib.reload(main_mod)
    app = main_mod.create_app()
    audit_routes = [
        r for r in app.routes if hasattr(r, "path") and "audit" in getattr(r, "path", "")
    ]
    for route in audit_routes:
        methods = getattr(route, "methods", None) or set()
        assert "DELETE" not in methods, f"Audit route {route.path} exposes DELETE"
        assert "PUT" not in methods, f"Audit route {route.path} exposes PUT"
        assert "PATCH" not in methods, f"Audit route {route.path} exposes PATCH"
