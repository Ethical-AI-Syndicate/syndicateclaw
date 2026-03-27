"""DB-backed audit module integration tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from ulid import ULID

from syndicateclaw.audit.dead_letter import DeadLetterQueue
from syndicateclaw.audit.events import EventBus
from syndicateclaw.audit.export import RunExporter
from syndicateclaw.audit.service import AuditService
from syndicateclaw.db.models import AuditEvent as DBAuditEvent
from syndicateclaw.db.models import WorkflowDefinition as DBWorkflowDefinition
from syndicateclaw.db.models import WorkflowRun as DBWorkflowRun
from syndicateclaw.db.repository import AuditEventRepository
from syndicateclaw.models import AuditEvent, AuditEventType

pytestmark = pytest.mark.integration


async def test_audit_append_creates_retrievable_event(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    audit = AuditService(session_factory)
    event = AuditService.create_event(
        event_type=AuditEventType.HTTP_REQUEST,
        actor="actor-integ",
        resource_type="test",
        resource_id="res-1",
        action="GET",
        details={"path": "/x"},
    )
    await audit.emit(event)
    rows = await audit.query(filters={"resource_id": "res-1"}, limit=10)
    assert len(rows) >= 1
    assert rows[0].actor == "actor-integ"


async def test_audit_dead_letter_fires_on_persistence_failure(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dlq = DeadLetterQueue(session_factory)
    audit = AuditService(session_factory, dead_letter_queue=dlq)

    async def boom(_self: AuditEventRepository, _row: object) -> object:
        raise RuntimeError("simulated persistence failure")

    monkeypatch.setattr(AuditEventRepository, "append", boom)

    event = AuditService.create_event(
        event_type=AuditEventType.HTTP_REQUEST,
        actor="actor-dlq",
        resource_type="test",
        resource_id="res-dlq",
        action="POST",
        details={},
    )
    out = await audit.emit(event)
    assert out.id == event.id
    pending = await dlq.size()
    assert pending >= 1


async def test_audit_no_update_path() -> None:
    assert not hasattr(AuditEventRepository, "update")
    assert not hasattr(AuditEventRepository, "delete")


async def test_audit_export_returns_ordered_events(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    wf_id = str(ULID())
    run_id = str(ULID())
    base = datetime.now(UTC)
    async with session_factory() as session, session.begin():
        session.add(
            DBWorkflowDefinition(
                id=wf_id,
                name=f"export-wf-{uuid.uuid4().hex[:8]}",
                version="1.0",
                description=None,
                nodes={},
                edges={},
                owner="test",
                metadata_={},
                namespace="default",
            )
        )
        session.add(
            DBWorkflowRun(
                id=run_id,
                workflow_id=wf_id,
                workflow_version="1.0",
                status="COMPLETED",
                state={},
                initiated_by="test",
                version_manifest={},
                namespace="default",
            )
        )
        for i in range(3):
            session.add(
                DBAuditEvent(
                    event_type="HTTP_REQUEST",
                    actor="a",
                    resource_type="workflow_run",
                    resource_id=run_id,
                    action=f"step-{i}",
                    details={"order": i},
                    created_at=base + timedelta(seconds=i),
                )
            )
        await session.flush()

    exporter = RunExporter(session_factory)
    bundle = await exporter.export_run(run_id)
    evs = bundle["audit_events"]
    orders = [e["details"].get("order") for e in evs if isinstance(e.get("details"), dict)]
    assert orders == [0, 1, 2]


async def test_audit_event_bus_fires_on_append(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    EventBus.reset()
    bus = EventBus()
    received: list[AuditEvent] = []

    async def on_ev(ev: AuditEvent) -> None:
        received.append(ev)

    bus.subscribe(AuditEventType.HTTP_REQUEST, on_ev)
    audit = AuditService(session_factory)
    event = AuditService.create_event(
        event_type=AuditEventType.HTTP_REQUEST,
        actor="bus-user",
        resource_type="test",
        resource_id="bus-1",
        action="GET",
        details={},
    )
    await bus.publish_and_persist(event, audit)
    assert len(received) == 1
    assert received[0].actor == "bus-user"
    EventBus.reset()


async def test_audit_integrity_hash_present(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    key = b"k" * 32
    audit = AuditService(session_factory, signing_key=key)
    event = AuditService.create_event(
        event_type=AuditEventType.HTTP_REQUEST,
        actor="signed",
        resource_type="test",
        resource_id="sig-1",
        action="GET",
        details={"x": 1},
    )
    await audit.emit(event)
    async with session_factory() as session:
        row = await session.get(DBAuditEvent, event.id)
        assert row is not None
        assert row.details.get("integrity_signature")

