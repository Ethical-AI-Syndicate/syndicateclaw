"""Targeted coverage gap tests for audit/dead_letter.py, audit/events.py,
audit/export.py, and services/subscription_service.py."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from syndicateclaw.audit.dead_letter import DeadLetterQueue
from syndicateclaw.audit.events import EventBus
from syndicateclaw.models import AuditEvent, AuditEventType, DeadLetterStatus

# ---------------------------------------------------------------------------
# Helpers shared
# ---------------------------------------------------------------------------


def _make_factory(*, get_return=None, scalars_return=None):
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_begin = AsyncMock()
    mock_begin.__aenter__ = AsyncMock(return_value=None)
    mock_begin.__aexit__ = AsyncMock(return_value=False)
    mock_session.begin = MagicMock(return_value=mock_begin)
    mock_session.get = AsyncMock(return_value=get_return)
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()

    result = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = scalars_return or []
    result.scalars.return_value = scalars_mock
    mock_session.execute = AsyncMock(return_value=result)

    return MagicMock(return_value=mock_session)


def _make_event(**kwargs) -> AuditEvent:
    defaults = dict(
        event_type=AuditEventType.HTTP_REQUEST,
        actor="user:1",
        resource_type="workflow",
        resource_id="wf-1",
        action="GET",
        details={},
    )
    defaults.update(kwargs)
    return AuditEvent.new(**defaults)


# ---------------------------------------------------------------------------
# DeadLetterQueue.size
# ---------------------------------------------------------------------------


async def test_dead_letter_size_returns_count() -> None:
    row1, row2 = MagicMock(), MagicMock()
    factory = _make_factory(scalars_return=[row1, row2])
    dlq = DeadLetterQueue(factory)
    count = await dlq.size()
    assert count == 2


async def test_dead_letter_size_empty() -> None:
    factory = _make_factory(scalars_return=[])
    dlq = DeadLetterQueue(factory)
    count = await dlq.size()
    assert count == 0


# ---------------------------------------------------------------------------
# DeadLetterQueue.retry_pending — retry paths
# ---------------------------------------------------------------------------


async def _make_dlq_rec(retry_count: int = 0, max_retries: int = 3) -> MagicMock:
    rec = MagicMock()
    rec.id = "dlq-1"
    rec.retry_count = retry_count
    rec.max_retries = max_retries
    rec.event_payload = {
        "id": "ev-1",
        "event_type": "HTTP_REQUEST",
        "actor": "user:1",
        "resource_type": "workflow",
        "resource_id": "wf-1",
        "action": "GET",
        "details": {},
        "timestamp": "2024-01-01T00:00:00+00:00",
        "scope_type": None,
        "scope_id": None,
        "principal_id": None,
        "outcome": None,
    }
    return rec


async def test_dead_letter_retry_marks_permanent_when_max_retries_reached() -> None:
    rec = await _make_dlq_rec(retry_count=3, max_retries=3)
    row = MagicMock()
    row.status = DeadLetterStatus.PENDING.value
    row.error_message = "orig"
    factory = _make_factory(scalars_return=[rec], get_return=row)
    dlq = DeadLetterQueue(factory)
    audit_service = AsyncMock()
    retried = await dlq.retry_all(audit_service)
    assert retried == 0
    assert DeadLetterStatus.FAILED_PERMANENT.value == row.status


async def test_dead_letter_retry_success_path() -> None:
    rec = await _make_dlq_rec(retry_count=0, max_retries=3)
    row = MagicMock()
    row.status = DeadLetterStatus.PENDING.value
    factory = _make_factory(scalars_return=[rec], get_return=row)
    dlq = DeadLetterQueue(factory)
    audit_service = AsyncMock()
    audit_service.emit = AsyncMock(return_value=_make_event())
    retried = await dlq.retry_all(audit_service)
    assert retried == 1
    assert row.status == DeadLetterStatus.RESOLVED.value


async def test_dead_letter_retry_emit_failure_increments_retry() -> None:
    rec = await _make_dlq_rec(retry_count=0, max_retries=3)
    row = MagicMock()
    row.retry_count = 0
    row.error_message = "old error"
    factory = _make_factory(scalars_return=[rec], get_return=row)
    dlq = DeadLetterQueue(factory)
    audit_service = AsyncMock()
    audit_service.emit = AsyncMock(side_effect=RuntimeError("db crash"))
    retried = await dlq.retry_all(audit_service)
    assert retried == 0
    assert row.retry_count == 1


# ---------------------------------------------------------------------------
# EventBus — publish with subscribers, error handlers, async handlers
# ---------------------------------------------------------------------------


async def test_event_bus_publish_notifies_sync_handler() -> None:
    EventBus.reset()
    bus = EventBus()
    received = []

    def handler(event: AuditEvent) -> None:
        received.append(event)

    bus.subscribe(AuditEventType.HTTP_REQUEST, handler)
    event = _make_event()
    await bus.publish(event)
    assert len(received) == 1
    EventBus.reset()


async def test_event_bus_publish_notifies_async_handler() -> None:
    EventBus.reset()
    bus = EventBus()
    received = []

    async def handler(event: AuditEvent) -> None:
        received.append(event)

    bus.subscribe(AuditEventType.HTTP_REQUEST, handler)
    event = _make_event()
    await bus.publish(event)
    assert len(received) == 1
    EventBus.reset()


async def test_event_bus_publish_logs_handler_error() -> None:
    EventBus.reset()
    bus = EventBus()

    def bad_handler(event: AuditEvent) -> None:
        raise RuntimeError("boom")

    bus.subscribe(AuditEventType.HTTP_REQUEST, bad_handler)
    event = _make_event()
    # Should not raise — error is logged
    await bus.publish(event)
    EventBus.reset()


async def test_event_bus_publish_skips_when_no_subscribers() -> None:
    EventBus.reset()
    bus = EventBus()
    event = _make_event()
    # No subscribers — should return without doing anything
    await bus.publish(event)
    EventBus.reset()


async def test_event_bus_publish_and_persist() -> None:
    EventBus.reset()
    bus = EventBus()
    event = _make_event()
    audit_service = AsyncMock()
    audit_service.emit = AsyncMock(return_value=event)

    result = await bus.publish_and_persist(event, audit_service)
    assert result is event
    audit_service.emit.assert_awaited_once_with(event)
    EventBus.reset()


async def test_event_bus_unsubscribe_removes_handler() -> None:
    EventBus.reset()
    bus = EventBus()
    received = []

    def handler(event: AuditEvent) -> None:
        received.append(event)

    bus.subscribe(AuditEventType.HTTP_REQUEST, handler)
    bus.unsubscribe(AuditEventType.HTTP_REQUEST, handler)
    event = _make_event()
    await bus.publish(event)
    assert received == []
    EventBus.reset()


def test_event_bus_unsubscribe_missing_handler_logs_warning() -> None:
    EventBus.reset()
    bus = EventBus()

    def handler(event: AuditEvent) -> None:
        pass

    # Unsubscribing a never-subscribed handler should not raise
    bus.unsubscribe("HTTP_REQUEST", handler)
    EventBus.reset()


# ---------------------------------------------------------------------------
# audit/export.py — missing lines 102-107 (export batch exceeds limit)
# ---------------------------------------------------------------------------


async def test_audit_run_exporter_run_not_found_raises() -> None:
    """Hit the RunExporter.export_run path when run doesn't exist."""
    from syndicateclaw.audit.export import RunExporter

    factory = _make_factory(get_return=None)
    exporter = RunExporter(factory)
    with pytest.raises(ValueError, match="not found"):
        await exporter.export_run("nonexistent-run")
