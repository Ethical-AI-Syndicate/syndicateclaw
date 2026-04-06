"""Unit tests for audit/integrity.py — IntegrityVerifier, all methods."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from syndicateclaw.audit.integrity import IntegrityVerifier

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session_factory(scalars_all=None):
    """Return a mock async_sessionmaker whose sessions yield mock results."""
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = list(scalars_all or [])

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock(return_value=mock_result)

    mock_begin = AsyncMock()
    mock_begin.__aenter__ = AsyncMock(return_value=None)
    mock_begin.__aexit__ = AsyncMock(return_value=False)
    mock_session.begin = MagicMock(return_value=mock_begin)

    return MagicMock(return_value=mock_session)


def _hash(data: dict) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def _make_decision_record(inputs: Any, *, tampered: bool = False) -> Any:
    rec = MagicMock()
    rec.id = "dr-1"
    rec.inputs = inputs
    rec.context_hash = "bad-hash" if tampered else _hash(inputs or {})
    rec.domain = "policy"
    rec.created_at = datetime.now(UTC)
    return rec


def _make_snapshot(response_data: Any, *, tampered: bool = False) -> Any:
    snap = MagicMock()
    snap.id = "snap-1"
    snap.run_id = "run-1"
    snap.response_data = response_data
    snap.content_hash = "bad-hash" if tampered else _hash(response_data or {})
    snap.snapshot_type = "tool_output"
    return snap


def _make_tool_execution(tool_name="http_request"):
    ex = MagicMock()
    ex.id = "te-1"
    ex.tool_name = tool_name
    ex.run_id = "run-orphan"
    ex.created_at = datetime.now(UTC)
    return ex


def _make_workflow_run(manifest):
    run = MagicMock()
    run.id = f"run-{id(manifest)}"
    run.version_manifest = manifest
    run.created_at = datetime.now(UTC)
    return run


# ---------------------------------------------------------------------------
# verify_decision_hashes
# ---------------------------------------------------------------------------


async def test_verify_decision_hashes_no_records() -> None:
    verifier = IntegrityVerifier(_make_session_factory([]))
    violations = await verifier.verify_decision_hashes()
    assert violations == []


async def test_verify_decision_hashes_no_violations() -> None:
    inputs = {"resource": "wf-1", "actor": "agent:1"}
    rec = _make_decision_record(inputs)
    verifier = IntegrityVerifier(_make_session_factory([rec]))
    violations = await verifier.verify_decision_hashes()
    assert violations == []


async def test_verify_decision_hashes_detects_tampered_hash() -> None:
    inputs = {"resource": "wf-1"}
    rec = _make_decision_record(inputs, tampered=True)
    verifier = IntegrityVerifier(_make_session_factory([rec]))
    violations = await verifier.verify_decision_hashes()
    assert len(violations) == 1
    assert violations[0]["decision_record_id"] == "dr-1"
    assert violations[0]["stored_hash"] == "bad-hash"
    assert violations[0]["domain"] == "policy"


async def test_verify_decision_hashes_none_inputs_treated_as_empty() -> None:
    rec = _make_decision_record(None)
    rec.context_hash = _hash({})
    verifier = IntegrityVerifier(_make_session_factory([rec]))
    violations = await verifier.verify_decision_hashes()
    assert violations == []


async def test_verify_decision_hashes_none_context_hash_is_violation() -> None:
    inputs = {"x": 1}
    rec = _make_decision_record(inputs)
    rec.context_hash = None  # stored as None → empty string compare fails
    verifier = IntegrityVerifier(_make_session_factory([rec]))
    violations = await verifier.verify_decision_hashes()
    assert len(violations) == 1


async def test_verify_decision_hashes_created_at_none() -> None:
    rec = _make_decision_record({"k": "v"})
    rec.created_at = None
    verifier = IntegrityVerifier(_make_session_factory([rec]))
    violations = await verifier.verify_decision_hashes()
    # No exception; violation still reported if hash mismatch
    assert isinstance(violations, list)


# ---------------------------------------------------------------------------
# verify_snapshot_hashes
# ---------------------------------------------------------------------------


async def test_verify_snapshot_hashes_no_records() -> None:
    verifier = IntegrityVerifier(_make_session_factory([]))
    violations = await verifier.verify_snapshot_hashes()
    assert violations == []


async def test_verify_snapshot_hashes_no_violations() -> None:
    snap = _make_snapshot({"output": "ok"})
    verifier = IntegrityVerifier(_make_session_factory([snap]))
    violations = await verifier.verify_snapshot_hashes()
    assert violations == []


async def test_verify_snapshot_hashes_detects_tampering() -> None:
    snap = _make_snapshot({"output": "real"}, tampered=True)
    verifier = IntegrityVerifier(_make_session_factory([snap]))
    violations = await verifier.verify_snapshot_hashes()
    assert len(violations) == 1
    assert violations[0]["snapshot_id"] == "snap-1"
    assert violations[0]["run_id"] == "run-1"
    assert violations[0]["snapshot_type"] == "tool_output"


async def test_verify_snapshot_hashes_none_response_data() -> None:
    snap = _make_snapshot(None)
    snap.content_hash = _hash({})
    verifier = IntegrityVerifier(_make_session_factory([snap]))
    violations = await verifier.verify_snapshot_hashes()
    assert violations == []


# ---------------------------------------------------------------------------
# find_unlinked_tool_executions
# ---------------------------------------------------------------------------


async def test_find_unlinked_tool_executions_empty() -> None:
    verifier = IntegrityVerifier(_make_session_factory([]))
    orphans = await verifier.find_unlinked_tool_executions()
    assert orphans == []


async def test_find_unlinked_tool_executions_returns_orphans() -> None:
    ex = _make_tool_execution("http_request")
    verifier = IntegrityVerifier(_make_session_factory([ex]))
    orphans = await verifier.find_unlinked_tool_executions()
    assert len(orphans) == 1
    assert orphans[0]["tool_execution_id"] == "te-1"
    assert orphans[0]["tool_name"] == "http_request"
    assert orphans[0]["run_id"] == "run-orphan"


async def test_find_unlinked_tool_executions_none_created_at() -> None:
    ex = _make_tool_execution()
    ex.created_at = None
    verifier = IntegrityVerifier(_make_session_factory([ex]))
    orphans = await verifier.find_unlinked_tool_executions()
    assert orphans[0]["created_at"] is None


# ---------------------------------------------------------------------------
# detect_version_drift
# ---------------------------------------------------------------------------


async def test_detect_version_drift_no_runs() -> None:
    verifier = IntegrityVerifier(_make_session_factory([]))
    reports = await verifier.detect_version_drift()
    assert reports == []


async def test_detect_version_drift_single_run_no_comparison() -> None:
    verifier = IntegrityVerifier(_make_session_factory([_make_workflow_run({"model": "v1"})]))
    reports = await verifier.detect_version_drift()
    assert reports == []


async def test_detect_version_drift_no_differences() -> None:
    manifest = {"model": "v1", "sdk": "1.0"}
    runs = [_make_workflow_run(manifest), _make_workflow_run(manifest)]
    verifier = IntegrityVerifier(_make_session_factory(runs))
    reports = await verifier.detect_version_drift()
    assert reports == []


async def test_detect_version_drift_detects_model_change() -> None:
    run1 = _make_workflow_run({"model": "v1"})
    run2 = _make_workflow_run({"model": "v2"})
    verifier = IntegrityVerifier(_make_session_factory([run1, run2]))
    reports = await verifier.detect_version_drift()
    assert len(reports) == 1
    assert "model" in reports[0]["differences"]
    assert reports[0]["differences"]["model"]["baseline"] == "v1"
    assert reports[0]["differences"]["model"]["this_run"] == "v2"


async def test_detect_version_drift_extra_key_in_run() -> None:
    run1 = _make_workflow_run({"model": "v1"})
    run2 = _make_workflow_run({"model": "v1", "extra": "added"})
    verifier = IntegrityVerifier(_make_session_factory([run1, run2]))
    reports = await verifier.detect_version_drift()
    assert len(reports) == 1
    assert "extra" in reports[0]["differences"]


async def test_detect_version_drift_none_manifest_treated_as_empty() -> None:
    run1 = _make_workflow_run(None)
    run2 = _make_workflow_run(None)
    verifier = IntegrityVerifier(_make_session_factory([run1, run2]))
    reports = await verifier.detect_version_drift()
    assert reports == []


# ---------------------------------------------------------------------------
# full_check
# ---------------------------------------------------------------------------


async def test_full_check_healthy_all_empty() -> None:
    # All four sub-checks return empty → healthy
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock(return_value=mock_result)

    mock_begin = AsyncMock()
    mock_begin.__aenter__ = AsyncMock(return_value=None)
    mock_begin.__aexit__ = AsyncMock(return_value=False)
    mock_session.begin = MagicMock(return_value=mock_begin)

    verifier = IntegrityVerifier(MagicMock(return_value=mock_session))
    report = await verifier.full_check()

    assert report["healthy"] is True
    assert report["decision_hash_violations"] == 0
    assert report["snapshot_hash_violations"] == 0
    assert report["unlinked_tool_executions"] == 0
    assert report["version_drift_instances"] == 0
    assert "checked_at" in report
    assert "details" in report


async def test_full_check_unhealthy_when_violations_exist() -> None:
    inputs = {"x": 1}
    rec = _make_decision_record(inputs, tampered=True)

    mock_result = MagicMock()
    # First call (decision records) returns tampered rec; rest return empty
    mock_result.scalars.return_value.all.side_effect = [
        [rec],
        [],
        [],
        [],
    ]

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock(return_value=mock_result)

    mock_begin = AsyncMock()
    mock_begin.__aenter__ = AsyncMock(return_value=None)
    mock_begin.__aexit__ = AsyncMock(return_value=False)
    mock_session.begin = MagicMock(return_value=mock_begin)

    verifier = IntegrityVerifier(MagicMock(return_value=mock_session))
    report = await verifier.full_check()
    assert report["healthy"] is False
    assert report["decision_hash_violations"] == 1
