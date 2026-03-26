"""Unit tests for models.dev catalog sync runner (fetch + merge + audit)."""

from __future__ import annotations

import httpx
import pytest

from syndicateclaw.inference.catalog import ModelCatalog
from syndicateclaw.inference.catalog_sync.runner import run_models_dev_catalog_sync
from syndicateclaw.models import AuditEventType
from tests.unit.inference.fixtures import minimal_system, provider, static_chat_row


class _RecordingAudit:
    def __init__(self) -> None:
        self.events: list = []

    async def emit(self, ev) -> None:
        self.events.append(ev)


@pytest.mark.asyncio
async def test_runner_applies_models_dev_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_resolve(_host: str) -> list[str]:
        return ["8.8.8.8"]

    monkeypatch.setattr(
        "syndicateclaw.inference.catalog_sync.ssrf.resolve_hostname_ips",
        fake_resolve,
    )

    payload = (
        b'[{"provider_id":"allowed","model_id":"md1","capability":"chat","name":"MD"}]'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload)

    transport = httpx.MockTransport(handler)
    sys = minimal_system(provider("allowed"), static=(static_chat_row("allowed", "m1"),))
    cat = ModelCatalog()
    cat.replace_from_yaml_static(sys, snapshot_version="v0")
    audit = _RecordingAudit()

    res = await run_models_dev_catalog_sync(
        feed_url="https://e.models.dev/data.json",
        allowed_host_suffixes=("models.dev",),
        max_bytes=1024,
        timeout_seconds=5.0,
        max_redirects=8,
        catalog=cat,
        base_system_config=sys,
        audit_service=audit,
        actor="tester",
        transport=transport,
    )

    assert res.applied is True
    assert res.records_accepted == 1
    assert cat.get("allowed", "md1") is not None

    types = [e.event_type for e in audit.events]
    assert AuditEventType.CATALOG_SYNC_STARTED in types
    assert AuditEventType.CATALOG_SYNC_COMPLETED in types


@pytest.mark.asyncio
async def test_runner_anomaly_aborts_emits_event(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_resolve(_host: str) -> list[str]:
        return ["8.8.8.8"]

    monkeypatch.setattr(
        "syndicateclaw.inference.catalog_sync.ssrf.resolve_hostname_ips",
        fake_resolve,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"[]")

    transport = httpx.MockTransport(handler)
    rows = (static_chat_row("p", "a"), static_chat_row("p", "b"))
    sys = minimal_system(provider("p"), static=rows)
    cat = ModelCatalog()
    cat.replace_from_yaml_static(sys, snapshot_version="v0")
    audit = _RecordingAudit()

    res = await run_models_dev_catalog_sync(
        feed_url="https://f.models.dev/data.json",
        allowed_host_suffixes=("models.dev",),
        max_bytes=1024,
        timeout_seconds=5.0,
        max_redirects=8,
        catalog=cat,
        base_system_config=sys,
        audit_service=audit,
        actor="tester",
        transport=transport,
    )

    assert res.applied is False
    assert res.aborted_reason == "systemic_anomaly_drop"
    types = [e.event_type for e in audit.events]
    assert AuditEventType.CATALOG_SYNC_ANOMALY_ABORTED in types


@pytest.mark.asyncio
async def test_runner_fetch_failed_emits_failed_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_resolve(_host: str) -> list[str]:
        return ["8.8.8.8"]

    monkeypatch.setattr(
        "syndicateclaw.inference.catalog_sync.ssrf.resolve_hostname_ips",
        fake_resolve,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b"err")

    transport = httpx.MockTransport(handler)
    sys = minimal_system(provider("allowed"), static=(static_chat_row("allowed", "m1"),))
    cat = ModelCatalog()
    cat.replace_from_yaml_static(sys, snapshot_version="v0")
    snap_before = cat.snapshot_version
    audit = _RecordingAudit()

    res = await run_models_dev_catalog_sync(
        feed_url="https://g.models.dev/data.json",
        allowed_host_suffixes=("models.dev",),
        max_bytes=1024,
        timeout_seconds=5.0,
        max_redirects=8,
        catalog=cat,
        base_system_config=sys,
        audit_service=audit,
        actor="tester",
        transport=transport,
    )

    assert res.applied is False
    assert res.aborted_reason == "fetch_failed"
    assert cat.snapshot_version == snap_before
    types = [e.event_type for e in audit.events]
    assert AuditEventType.CATALOG_SYNC_FAILED in types
