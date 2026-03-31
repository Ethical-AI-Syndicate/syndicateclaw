"""Unit tests for db/repository.py — methods not covered by integration tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from syndicateclaw.db.repository import (
    ApprovalRequestRepository,
    AuditEventRepository,
    DeadLetterRecordRepository,
    DecisionRecordRepository,
    InputSnapshotRepository,
    MemoryRecordRepository,
    NodeExecutionRepository,
    PolicyRuleRepository,
    ToolExecutionRepository,
    WorkflowRunRepository,
)


def _make_session(*, scalars_return=None, scalar_one_or_none=None, all_return=None):
    session = AsyncMock()
    session.merge = AsyncMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()

    result = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = scalars_return or []
    result.scalars.return_value = scalars_mock
    result.scalar_one_or_none.return_value = scalar_one_or_none
    result.all.return_value = all_return or []
    session.execute = AsyncMock(return_value=result)
    return session


# ---------------------------------------------------------------------------
# BaseRepository.delete
# ---------------------------------------------------------------------------


async def test_base_delete_executes_and_flushes() -> None:
    session = _make_session()
    repo = WorkflowRunRepository(session)
    await repo.delete("run-1")
    session.execute.assert_awaited_once()
    session.flush.assert_awaited_once()


# ---------------------------------------------------------------------------
# BaseRepository.list
# ---------------------------------------------------------------------------


async def test_base_list_no_filters() -> None:
    row = MagicMock()
    session = _make_session(scalars_return=[row])
    repo = WorkflowRunRepository(session)
    result = await repo.list()
    assert result == [row]


async def test_base_list_with_valid_filter() -> None:
    row = MagicMock()
    session = _make_session(scalars_return=[row])
    repo = WorkflowRunRepository(session)
    result = await repo.list(filters={"status": "running"})
    assert result == [row]


async def test_base_list_ignores_unknown_filter() -> None:
    session = _make_session(scalars_return=[])
    repo = WorkflowRunRepository(session)
    result = await repo.list(filters={"nonexistent_col": "val"})
    assert result == []


# ---------------------------------------------------------------------------
# WorkflowRunRepository
# ---------------------------------------------------------------------------


async def test_get_active_runs_returns_rows() -> None:
    row = MagicMock()
    session = _make_session(scalars_return=[row])
    repo = WorkflowRunRepository(session)
    result = await repo.get_active_runs()
    assert result == [row]


async def test_get_runs_by_status_returns_rows() -> None:
    row = MagicMock()
    session = _make_session(scalars_return=[row])
    repo = WorkflowRunRepository(session)
    result = await repo.get_runs_by_status("completed")
    assert result == [row]


async def test_update_status_running_sets_started_at() -> None:
    session = _make_session()
    repo = WorkflowRunRepository(session)
    await repo.update_status("run-1", "running")
    session.execute.assert_awaited_once()
    session.flush.assert_awaited_once()


async def test_update_status_completed_sets_completed_at() -> None:
    session = _make_session()
    repo = WorkflowRunRepository(session)
    await repo.update_status("run-1", "completed")
    session.execute.assert_awaited_once()


async def test_update_status_with_error() -> None:
    session = _make_session()
    repo = WorkflowRunRepository(session)
    await repo.update_status("run-1", "failed", error="something went wrong")
    session.execute.assert_awaited_once()


async def test_update_status_generic_transition() -> None:
    session = _make_session()
    repo = WorkflowRunRepository(session)
    await repo.update_status("run-1", "paused")
    session.execute.assert_awaited_once()


# ---------------------------------------------------------------------------
# NodeExecutionRepository
# ---------------------------------------------------------------------------


async def test_node_execution_get_by_run() -> None:
    row = MagicMock()
    session = _make_session(scalars_return=[row])
    repo = NodeExecutionRepository(session)
    result = await repo.get_by_run("run-1")
    assert result == [row]


async def test_node_execution_get_latest_for_node_found() -> None:
    row = MagicMock()
    session = _make_session(scalar_one_or_none=row)
    repo = NodeExecutionRepository(session)
    result = await repo.get_latest_for_node("run-1", "node-1")
    assert result is row


async def test_node_execution_get_latest_for_node_not_found() -> None:
    session = _make_session(scalar_one_or_none=None)
    repo = NodeExecutionRepository(session)
    result = await repo.get_latest_for_node("run-1", "missing-node")
    assert result is None


# ---------------------------------------------------------------------------
# ToolExecutionRepository
# ---------------------------------------------------------------------------


async def test_tool_execution_get_by_run() -> None:
    row = MagicMock()
    session = _make_session(scalars_return=[row])
    repo = ToolExecutionRepository(session)
    result = await repo.get_by_run("run-1")
    assert result == [row]


# ---------------------------------------------------------------------------
# MemoryRecordRepository
# ---------------------------------------------------------------------------


async def test_memory_record_mark_for_deletion() -> None:
    session = _make_session()
    repo = MemoryRecordRepository(session)
    await repo.mark_for_deletion("rec-1")
    session.execute.assert_awaited_once()
    session.flush.assert_awaited_once()


# ---------------------------------------------------------------------------
# ApprovalRequestRepository
# ---------------------------------------------------------------------------


async def test_approval_get_pending_returns_rows() -> None:
    row = MagicMock()
    session = _make_session(scalars_return=[row])
    repo = ApprovalRequestRepository(session)
    result = await repo.get_pending()
    assert result == [row]


async def test_approval_get_by_run_returns_rows() -> None:
    row = MagicMock()
    session = _make_session(scalars_return=[row])
    repo = ApprovalRequestRepository(session)
    result = await repo.get_by_run("run-1")
    assert result == [row]


# ---------------------------------------------------------------------------
# AuditEventRepository
# ---------------------------------------------------------------------------


async def test_audit_get_by_trace_returns_rows() -> None:
    row = MagicMock()
    session = _make_session(scalars_return=[row])
    repo = AuditEventRepository(session)
    result = await repo.get_by_trace("trace-1")
    assert result == [row]


async def test_audit_get_by_resource_returns_rows() -> None:
    row = MagicMock()
    session = _make_session(scalars_return=[row])
    repo = AuditEventRepository(session)
    result = await repo.get_by_resource("workflow", "wf-1")
    assert result == [row]


async def test_audit_query_with_filters() -> None:
    row = MagicMock()
    session = _make_session(scalars_return=[row])
    repo = AuditEventRepository(session)
    result = await repo.query(filters={"actor": "user:1"}, limit=10)
    assert result == [row]


async def test_audit_append() -> None:
    event_row = MagicMock()
    session = _make_session()
    session.add = MagicMock()
    repo = AuditEventRepository(session)
    result = await repo.append(event_row)
    session.add.assert_called_once_with(event_row)
    session.flush.assert_awaited_once()


# ---------------------------------------------------------------------------
# MemoryRecordRepository — additional paths
# ---------------------------------------------------------------------------


async def test_memory_get_by_namespace_include_expired() -> None:
    row = MagicMock()
    session = _make_session(scalars_return=[row])
    repo = MemoryRecordRepository(session)
    result = await repo.get_by_namespace("ns-1", include_expired=True)
    assert result == [row]


async def test_memory_get_by_key_found() -> None:
    row = MagicMock()
    session = _make_session(scalar_one_or_none=row)
    repo = MemoryRecordRepository(session)
    result = await repo.get_by_key("ns-1", "my-key")
    assert result is row


async def test_memory_get_by_key_not_found() -> None:
    session = _make_session(scalar_one_or_none=None)
    repo = MemoryRecordRepository(session)
    result = await repo.get_by_key("ns-1", "missing")
    assert result is None


async def test_memory_purge_expired() -> None:
    session = _make_session(all_return=[MagicMock()])
    repo = MemoryRecordRepository(session)
    count = await repo.purge_expired()
    assert count == 1


# ---------------------------------------------------------------------------
# PolicyRuleRepository
# ---------------------------------------------------------------------------


async def test_policy_rule_get_enabled_by_resource_type() -> None:
    row = MagicMock()
    session = _make_session(scalars_return=[row])
    repo = PolicyRuleRepository(session)
    result = await repo.get_enabled_by_resource_type("tool")
    assert result == [row]


# ---------------------------------------------------------------------------
# ApprovalRequestRepository — additional paths
# ---------------------------------------------------------------------------


async def test_approval_get_pending_by_assignee() -> None:
    row = MagicMock()
    session = _make_session(scalars_return=[row])
    repo = ApprovalRequestRepository(session)
    result = await repo.get_pending_by_assignee("admin:ops")
    assert result == [row]


async def test_approval_get_expired_pending() -> None:
    from datetime import UTC, datetime
    row = MagicMock()
    session = _make_session(scalars_return=[row])
    repo = ApprovalRequestRepository(session)
    result = await repo.get_expired_pending(datetime.now(UTC))
    assert result == [row]


# ---------------------------------------------------------------------------
# DecisionRecordRepository
# ---------------------------------------------------------------------------


async def test_decision_record_append() -> None:
    rec = MagicMock()
    session = _make_session()
    session.add = MagicMock()
    repo = DecisionRecordRepository(session)
    result = await repo.append(rec)
    session.add.assert_called_once_with(rec)


async def test_decision_record_get_by_run() -> None:
    row = MagicMock()
    session = _make_session(scalars_return=[row])
    repo = DecisionRecordRepository(session)
    result = await repo.get_by_run("run-1")
    assert result == [row]


async def test_decision_record_get_by_domain() -> None:
    row = MagicMock()
    session = _make_session(scalars_return=[row])
    repo = DecisionRecordRepository(session)
    result = await repo.get_by_domain("policy", offset=0, limit=10)
    assert result == [row]


async def test_decision_record_get_by_trace() -> None:
    row = MagicMock()
    session = _make_session(scalars_return=[row])
    repo = DecisionRecordRepository(session)
    result = await repo.get_by_trace("trace-abc")
    assert result == [row]


# ---------------------------------------------------------------------------
# InputSnapshotRepository
# ---------------------------------------------------------------------------


async def test_input_snapshot_get_by_run() -> None:
    row = MagicMock()
    session = _make_session(scalars_return=[row])
    repo = InputSnapshotRepository(session)
    result = await repo.get_by_run("run-1")
    assert result == [row]


async def test_input_snapshot_get_by_node() -> None:
    row = MagicMock()
    session = _make_session(scalars_return=[row])
    repo = InputSnapshotRepository(session)
    result = await repo.get_by_node("run-1", "ne-1")
    assert result == [row]


async def test_input_snapshot_get_for_replay_found() -> None:
    row = MagicMock()
    session = _make_session(scalar_one_or_none=row)
    repo = InputSnapshotRepository(session)
    result = await repo.get_for_replay("run-1", "input:data")
    assert result is row


async def test_input_snapshot_get_for_replay_not_found() -> None:
    session = _make_session(scalar_one_or_none=None)
    repo = InputSnapshotRepository(session)
    result = await repo.get_for_replay("run-1", "missing:source")
    assert result is None


# ---------------------------------------------------------------------------
# DeadLetterRecordRepository
# ---------------------------------------------------------------------------


async def test_dead_letter_record_get_pending() -> None:
    row = MagicMock()
    session = _make_session(scalars_return=[row])
    repo = DeadLetterRecordRepository(session)
    result = await repo.get_pending()
    assert result == [row]


async def test_dead_letter_record_get_by_category() -> None:
    row = MagicMock()
    session = _make_session(scalars_return=[row])
    repo = DeadLetterRecordRepository(session)
    result = await repo.get_by_category("transient")
    assert result == [row]


async def test_dead_letter_record_mark_resolved() -> None:
    session = _make_session()
    repo = DeadLetterRecordRepository(session)
    await repo.mark_resolved("dlq-1", "admin:ops")
    session.execute.assert_awaited_once()
    session.flush.assert_awaited_once()


async def test_dead_letter_record_mark_permanent_failure() -> None:
    session = _make_session()
    repo = DeadLetterRecordRepository(session)
    await repo.mark_permanent_failure("dlq-1")
    session.execute.assert_awaited_once()
    session.flush.assert_awaited_once()


async def test_dead_letter_record_increment_retry() -> None:
    session = _make_session()
    repo = DeadLetterRecordRepository(session)
    await repo.increment_retry("dlq-1")
    session.execute.assert_awaited_once()
    session.flush.assert_awaited_once()
