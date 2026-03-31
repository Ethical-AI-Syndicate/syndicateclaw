"""Unit tests for audit/service.py and audit/ledger.py — missing coverage paths."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from syndicateclaw.audit.ledger import DecisionLedger, _hash_inputs
from syndicateclaw.audit.service import AuditService, _resolve_resource_scope
from syndicateclaw.models import AuditEvent, AuditEventType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session_factory(get_return=None, scalars_all=None, execute_first=None):
    mock_result = MagicMock()
    if scalars_all is not None:
        mock_result.scalars.return_value.all.return_value = list(scalars_all)
    if execute_first is not None:
        mock_result.first.return_value = execute_first

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.get = AsyncMock(return_value=get_return)

    mock_begin = AsyncMock()
    mock_begin.__aenter__ = AsyncMock(return_value=None)
    mock_begin.__aexit__ = AsyncMock(return_value=False)
    mock_session.begin = MagicMock(return_value=mock_begin)

    return MagicMock(return_value=mock_session)


def _make_audit_event(**overrides) -> AuditEvent:
    defaults = dict(
        event_type=AuditEventType.HTTP_REQUEST,
        actor="user:1",
        resource_type="workflow",
        resource_id="wf-1",
        action="GET",
        details={},
    )
    defaults.update(overrides)
    return AuditEvent.new(**defaults)


# ---------------------------------------------------------------------------
# _hash_inputs
# ---------------------------------------------------------------------------


def test_hash_inputs_deterministic() -> None:
    data = {"b": 2, "a": 1}
    h1 = _hash_inputs(data)
    h2 = _hash_inputs(data)
    assert h1 == h2
    # Same content different key order → same hash (sort_keys=True)
    h3 = _hash_inputs({"a": 1, "b": 2})
    assert h1 == h3


# ---------------------------------------------------------------------------
# _resolve_resource_scope (module-level function in audit/service.py)
# ---------------------------------------------------------------------------


async def test_resolve_resource_scope_known_table_returns_scope() -> None:
    mock_result = MagicMock()
    mock_result.first.return_value = ("TENANT", "org-1")
    session = AsyncMock()
    session.execute = AsyncMock(return_value=mock_result)

    scope_type, scope_id = await _resolve_resource_scope(session, "workflow", "wf-1")
    assert scope_type == "TENANT"
    assert scope_id == "org-1"


async def test_resolve_resource_scope_unknown_type_returns_nones() -> None:
    session = AsyncMock()
    scope_type, scope_id = await _resolve_resource_scope(session, "unknown_type", "id-1")
    assert scope_type is None
    assert scope_id is None


async def test_resolve_resource_scope_row_not_found_returns_nones() -> None:
    mock_result = MagicMock()
    mock_result.first.return_value = None
    session = AsyncMock()
    session.execute = AsyncMock(return_value=mock_result)

    scope_type, scope_id = await _resolve_resource_scope(session, "workflow_run", "run-1")
    assert scope_type is None
    assert scope_id is None


async def test_resolve_resource_scope_memory_type() -> None:
    mock_result = MagicMock()
    mock_result.first.return_value = ("NAMESPACE", "ns-1")
    session = AsyncMock()
    session.execute = AsyncMock(return_value=mock_result)

    scope_type, scope_id = await _resolve_resource_scope(session, "memory", "rec-1")
    assert scope_type == "NAMESPACE"


async def test_resolve_resource_scope_policy_type() -> None:
    mock_result = MagicMock()
    mock_result.first.return_value = ("PLATFORM", "platform")
    session = AsyncMock()
    session.execute = AsyncMock(return_value=mock_result)

    scope_type, scope_id = await _resolve_resource_scope(session, "policy_rule", "rule-1")
    assert scope_type == "PLATFORM"


async def test_resolve_resource_scope_exception_returns_nones() -> None:
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=RuntimeError("db error"))
    scope_type, scope_id = await _resolve_resource_scope(session, "workflow", "wf-1")
    assert scope_type is None
    assert scope_id is None


# ---------------------------------------------------------------------------
# AuditService.emit — signing key path
# ---------------------------------------------------------------------------


async def test_audit_service_emit_with_signing_key() -> None:
    factory = _make_session_factory()
    signing_key = b"test-signing-key-32-bytes-long!!"

    with patch("syndicateclaw.audit.service.AuditEventRepository") as MockRepo:
        mock_repo = AsyncMock()
        mock_repo.append = AsyncMock()
        MockRepo.return_value = mock_repo

        with patch("syndicateclaw.audit.service._resolve_principal_id", new=AsyncMock(return_value="pid-1")):
            with patch("syndicateclaw.audit.service._resolve_resource_scope", new=AsyncMock(return_value=(None, None))):
                with patch("syndicateclaw.security.signing.sign_record", return_value={"signed": True}) as mock_sign:
                    svc = AuditService(factory, signing_key=signing_key)
                    event = _make_audit_event()
                    await svc.emit(event)

    mock_sign.assert_called_once()


async def test_audit_service_emit_dead_letter_on_failure() -> None:
    """When emit fails and dead_letter_queue is set, event is enqueued instead of raising."""
    factory = _make_session_factory()

    with patch("syndicateclaw.audit.service.AuditEventRepository") as MockRepo:
        mock_repo = AsyncMock()
        mock_repo.append = AsyncMock(side_effect=RuntimeError("db write failed"))
        MockRepo.return_value = mock_repo

        with patch("syndicateclaw.audit.service._resolve_principal_id", new=AsyncMock(return_value=None)):
            with patch("syndicateclaw.audit.service._resolve_resource_scope", new=AsyncMock(return_value=(None, None))):
                dlq = AsyncMock()
                dlq.enqueue = AsyncMock()

                svc = AuditService(factory, dead_letter_queue=dlq)
                event = _make_audit_event()
                result = await svc.emit(event)

    dlq.enqueue.assert_awaited_once()
    assert result is event


async def test_audit_service_emit_no_dlq_reraises() -> None:
    """When emit fails and no DLQ, exception propagates."""
    factory = _make_session_factory()

    with patch("syndicateclaw.audit.service.AuditEventRepository") as MockRepo:
        mock_repo = AsyncMock()
        mock_repo.append = AsyncMock(side_effect=RuntimeError("db write failed"))
        MockRepo.return_value = mock_repo

        with patch("syndicateclaw.audit.service._resolve_principal_id", new=AsyncMock(return_value=None)):
            with patch("syndicateclaw.audit.service._resolve_resource_scope", new=AsyncMock(return_value=(None, None))):
                svc = AuditService(factory)
                event = _make_audit_event()

                import pytest
                with pytest.raises(RuntimeError, match="db write failed"):
                    await svc.emit(event)


# ---------------------------------------------------------------------------
# DecisionLedger — convenience record methods
# ---------------------------------------------------------------------------


def _make_decision_row(inputs: dict) -> MagicMock:
    row = MagicMock()
    row.id = "dr-1"
    row.inputs = inputs
    row.context_hash = _hash_inputs(inputs)
    row.domain = "policy"
    row.decision_type = "policy_allow"
    row.actor = "user:1"
    row.effect = "allowed"
    row.justification = "rule matched"
    row.rules_evaluated = []
    row.matched_rule = None
    row.run_id = None
    row.trace_id = None
    row.created_at = datetime.now(UTC)
    row.node_execution_id = None
    row.side_effects = []
    row.confidence = 1.0
    return row


async def test_ledger_record_policy_decision() -> None:
    factory = _make_session_factory()

    with patch("syndicateclaw.audit.ledger.DecisionRecordRepository") as MockRepo:
        mock_repo = AsyncMock()
        mock_repo.append = AsyncMock()
        MockRepo.return_value = mock_repo

        ledger = DecisionLedger(factory)
        result = await ledger.record_policy_decision(
            actor="user:1",
            resource_type="tool",
            resource_id="my-tool",
            action="execute",
            all_rules=[],
            matched_rule=None,
            effect="allowed",
            justification="default allow",
            input_attributes={"env": "prod"},
        )

    assert result is not None
    mock_repo.append.assert_awaited_once()


async def test_ledger_record_tool_decision() -> None:
    factory = _make_session_factory()

    with patch("syndicateclaw.audit.ledger.DecisionRecordRepository") as MockRepo:
        mock_repo = AsyncMock()
        mock_repo.append = AsyncMock()
        MockRepo.return_value = mock_repo

        ledger = DecisionLedger(factory)
        result = await ledger.record_tool_decision(
            actor="user:1",
            tool_name="http_request",
            input_data={"url": "https://example.com"},
            policy_effect="allowed",
            justification="policy match",
            side_effects=["external_http_call"],
        )

    assert result is not None


async def test_ledger_record_memory_decision_read() -> None:
    factory = _make_session_factory()

    with patch("syndicateclaw.audit.ledger.DecisionRecordRepository") as MockRepo:
        mock_repo = AsyncMock()
        mock_repo.append = AsyncMock()
        MockRepo.return_value = mock_repo

        ledger = DecisionLedger(factory)
        result = await ledger.record_memory_decision(
            actor="user:1",
            namespace="my-ns",
            key="my-key",
            action="read",
            trust_score=0.9,
            justification="read allowed",
        )

    assert result is not None
    # "read" → decision_type="memory_read"
    assert result.decision_type == "memory_read"
    mock_repo.append.assert_awaited_once()


async def test_ledger_record_memory_decision_write() -> None:
    factory = _make_session_factory()

    with patch("syndicateclaw.audit.ledger.DecisionRecordRepository") as MockRepo:
        mock_repo = AsyncMock()
        mock_repo.append = AsyncMock()
        MockRepo.return_value = mock_repo

        ledger = DecisionLedger(factory)
        result = await ledger.record_memory_decision(
            actor="user:1",
            namespace="my-ns",
            key="my-key",
            action="write",
            trust_score=0.95,
            justification="write allowed",
        )

    assert result is not None
    assert result.decision_type == "memory_write"
    mock_repo.append.assert_awaited_once()


async def test_ledger_get_run_decisions() -> None:
    factory = _make_session_factory()
    row = _make_decision_row({"x": 1})

    with patch("syndicateclaw.audit.ledger.DecisionRecordRepository") as MockRepo:
        mock_repo = AsyncMock()
        mock_repo.get_by_run = AsyncMock(return_value=[row])
        MockRepo.return_value = mock_repo

        ledger = DecisionLedger(factory)
        with patch.object(
            __import__("syndicateclaw.models", fromlist=["DecisionRecord"]).DecisionRecord,
            "model_validate",
            return_value=MagicMock(),
        ):
            results = await ledger.get_run_decisions("run-1")

    mock_repo.get_by_run.assert_awaited_once_with("run-1")
    assert len(results) == 1


async def test_ledger_get_trace_decisions() -> None:
    factory = _make_session_factory()

    with patch("syndicateclaw.audit.ledger.DecisionRecordRepository") as MockRepo:
        mock_repo = AsyncMock()
        mock_repo.get_by_trace = AsyncMock(return_value=[])
        MockRepo.return_value = mock_repo

        ledger = DecisionLedger(factory)
        results = await ledger.get_trace_decisions("trace-abc")

    mock_repo.get_by_trace.assert_awaited_once_with("trace-abc")
    assert results == []


async def test_ledger_verify_integrity_matching_hash() -> None:
    inputs = {"resource": "wf-1"}
    row = _make_decision_row(inputs)
    factory = _make_session_factory(get_return=row)

    ledger = DecisionLedger(factory)
    result = await ledger.verify_integrity("dr-1")
    assert result is True


async def test_ledger_verify_integrity_tampered_hash() -> None:
    inputs = {"resource": "wf-1"}
    row = _make_decision_row(inputs)
    row.context_hash = "tampered"
    factory = _make_session_factory(get_return=row)

    ledger = DecisionLedger(factory)
    result = await ledger.verify_integrity("dr-1")
    assert result is False


async def test_ledger_verify_integrity_missing_record() -> None:
    factory = _make_session_factory(get_return=None)

    ledger = DecisionLedger(factory)
    result = await ledger.verify_integrity("nonexistent")
    assert result is False
