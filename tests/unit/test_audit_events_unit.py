"""Unit tests for audit — EventBus (lines 48, 59) and RunExporter error path (line 67)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from syndicateclaw.audit.events import EventBus
from syndicateclaw.audit.export import RunExporter
from syndicateclaw.models import AuditEvent, AuditEventType


def _make_event() -> AuditEvent:
    return AuditEvent.new(
        event_type=AuditEventType.HTTP_REQUEST,
        actor="unit-test",
        resource_type="test",
        resource_id="r1",
        action="GET",
        details={},
    )


def test_event_bus_unsubscribe_registered_handler() -> None:
    """Unsubscribing a registered handler covers the logger.debug success path (line 48)."""
    EventBus.reset()
    bus = EventBus()

    def handler(ev: AuditEvent) -> None:  # pragma: no cover
        pass

    bus.subscribe(AuditEventType.HTTP_REQUEST, handler)
    # Should not raise; covers line 48 (logger.debug after handlers.remove)
    bus.unsubscribe(AuditEventType.HTTP_REQUEST, handler)
    EventBus.reset()


async def test_event_bus_publish_no_subscribers_returns_early() -> None:
    """Publishing to an event type with no subscribers covers the early return (line 59)."""
    EventBus.reset()
    bus = EventBus()
    # No subscriber registered — publish should return immediately without error
    await bus.publish(_make_event())
    EventBus.reset()


async def test_run_exporter_raises_when_run_not_found() -> None:
    """export_run raises ValueError when session.get returns None (covers line 67)."""
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.get = AsyncMock(return_value=None)
    mock_factory = MagicMock(return_value=mock_session)

    exporter = RunExporter(mock_factory)
    with pytest.raises(ValueError, match="not found"):
        await exporter.export_run("nonexistent-run-id")


def test_event_bus_unsubscribe_unregistered_handler_does_not_raise() -> None:
    """Unsubscribing a handler that was never subscribed logs a warning but does not raise."""
    EventBus.reset()
    bus = EventBus()

    def handler(ev: AuditEvent) -> None:  # pragma: no cover
        pass

    bus.unsubscribe(AuditEventType.HTTP_REQUEST, handler)  # Miss path — already covered
    EventBus.reset()
