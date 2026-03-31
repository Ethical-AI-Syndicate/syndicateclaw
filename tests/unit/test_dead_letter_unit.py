"""Unit tests for audit/dead_letter.py — paths not covered by integration tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syndicateclaw.audit.dead_letter import DeadLetterQueue
from syndicateclaw.models import AuditEvent, AuditEventType, DeadLetterStatus


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

    return MagicMock(return_value=mock_session), mock_session


def _make_event() -> AuditEvent:
    return AuditEvent(
        event_type=AuditEventType.WORKFLOW_STARTED,
        actor="test-actor",
        resource_id="wf-1",
        resource_type="workflow",
        action="start",
    )


# ---------------------------------------------------------------------------
# enqueue
# ---------------------------------------------------------------------------


async def test_enqueue_returns_record_id() -> None:
    factory, session = _make_factory()
    dlq = DeadLetterQueue(factory)

    # Simulate flush setting row.id
    added_row = None

    def capture_add(row):
        nonlocal added_row
        added_row = row
        row.id = "dlq-record-1"

    session.add = MagicMock(side_effect=capture_add)

    record_id = await dlq.enqueue(_make_event(), "connection refused")
    assert record_id == "dlq-record-1"
    session.add.assert_called_once()
    session.flush.assert_awaited()


# ---------------------------------------------------------------------------
# retry_all — max retries exhausted branch
# ---------------------------------------------------------------------------


async def test_retry_all_marks_permanent_when_max_retries_exhausted() -> None:
    # First factory call: query returns records with retry_count >= max_retries
    rec = MagicMock()
    rec.id = "dlq-1"
    rec.retry_count = 3
    rec.max_retries = 3

    # Second factory call: session.get returns the row to update
    row = MagicMock()
    row.error_message = "original"

    factory, _ = _make_factory(scalars_return=[rec])
    # Override get on each new session created
    call_count = 0

    def make_session():
        nonlocal call_count
        call_count += 1
        s = AsyncMock()
        s.__aenter__ = AsyncMock(return_value=s)
        s.__aexit__ = AsyncMock(return_value=False)
        begin = AsyncMock()
        begin.__aenter__ = AsyncMock(return_value=None)
        begin.__aexit__ = AsyncMock(return_value=False)
        s.begin = MagicMock(return_value=begin)
        result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [rec] if call_count == 1 else []
        result.scalars.return_value = scalars_mock
        s.execute = AsyncMock(return_value=result)
        s.get = AsyncMock(return_value=row)
        return s

    dlq = DeadLetterQueue(MagicMock(side_effect=make_session))
    audit_svc = AsyncMock()
    retried = await dlq.retry_all(audit_svc)
    assert retried == 0
    assert row.status == DeadLetterStatus.FAILED_PERMANENT.value


# ---------------------------------------------------------------------------
# retry_all — exception during retry
# ---------------------------------------------------------------------------


async def test_retry_all_increments_retry_count_on_failure() -> None:
    rec = MagicMock()
    rec.id = "dlq-2"
    rec.retry_count = 0
    rec.max_retries = 3

    row = MagicMock()
    row.error_message = "original"
    row.retry_count = 0

    call_count = 0

    def make_session():
        nonlocal call_count
        call_count += 1
        s = AsyncMock()
        s.__aenter__ = AsyncMock(return_value=s)
        s.__aexit__ = AsyncMock(return_value=False)
        begin = AsyncMock()
        begin.__aenter__ = AsyncMock(return_value=None)
        begin.__aexit__ = AsyncMock(return_value=False)
        s.begin = MagicMock(return_value=begin)
        result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [rec] if call_count == 1 else []
        result.scalars.return_value = scalars_mock
        s.execute = AsyncMock(return_value=result)
        s.get = AsyncMock(return_value=row)
        return s

    audit_svc = AsyncMock()
    audit_svc.emit = AsyncMock(side_effect=RuntimeError("network down"))

    with patch(
        "syndicateclaw.audit.dead_letter.AuditEvent.model_validate",
        return_value=MagicMock(),
    ):
        dlq = DeadLetterQueue(MagicMock(side_effect=make_session))
        retried = await dlq.retry_all(audit_svc)

    assert retried == 0
    assert row.retry_count == 1  # incremented


# ---------------------------------------------------------------------------
# resolve
# ---------------------------------------------------------------------------


async def test_resolve_marks_resolved() -> None:
    row = MagicMock()
    row.status = DeadLetterStatus.PENDING.value
    row.resolved_at = None
    row.resolved_by = None
    row.error_message = "original"

    factory, session = _make_factory(get_return=row)
    dlq = DeadLetterQueue(factory)
    await dlq.resolve("dlq-1", "admin", reason="manually resolved")
    assert row.status == DeadLetterStatus.RESOLVED.value
    assert row.resolved_by == "admin"


async def test_resolve_raises_when_not_found() -> None:
    factory, _ = _make_factory(get_return=None)
    dlq = DeadLetterQueue(factory)
    with pytest.raises(ValueError, match="not found"):
        await dlq.resolve("missing", "admin")


async def test_resolve_no_reason_skips_message_update() -> None:
    row = MagicMock()
    row.error_message = "original"
    row.status = DeadLetterStatus.PENDING.value

    factory, _ = _make_factory(get_return=row)
    dlq = DeadLetterQueue(factory)
    await dlq.resolve("dlq-1", "admin")
    # No reason → error_message should not be modified
    assert row.error_message == "original"
