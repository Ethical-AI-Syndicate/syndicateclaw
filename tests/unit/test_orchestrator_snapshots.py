"""Unit tests for orchestrator/snapshots.py — InputSnapshotStore async methods."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from syndicateclaw.orchestrator.snapshots import InputSnapshotStore, _hash_response


def _make_session_factory(*, get_return=None, repo_override=None):
    """Return a mock session factory; optionally inject a custom repo."""
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.get = AsyncMock(return_value=get_return)

    mock_begin = AsyncMock()
    mock_begin.__aenter__ = AsyncMock(return_value=None)
    mock_begin.__aexit__ = AsyncMock(return_value=False)
    mock_session.begin = MagicMock(return_value=mock_begin)

    return MagicMock(return_value=mock_session), mock_session


def _make_snapshot_row(**kwargs):
    row = MagicMock()
    defaults = {
        "id": "snap-1",
        "run_id": "run-1",
        "node_execution_id": "node-exec-1",
        "snapshot_type": "tool_response",
        "source_identifier": "tool:http_request",
        "request_data": {"url": "https://example.com"},
        "response_data": {"status": 200, "body": "ok"},
        "content_hash": _hash_response({"status": 200, "body": "ok"}),
        "captured_at": datetime.now(UTC),
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    defaults.update(kwargs)
    for k, v in defaults.items():
        setattr(row, k, v)
    # Make model_validate work by supporting dict()-like conversion
    row.__dict__.update(defaults)
    return row


# ---------------------------------------------------------------------------
# Pure function
# ---------------------------------------------------------------------------


def test_hash_response_is_deterministic() -> None:
    data = {"b": 2, "a": 1}
    assert _hash_response(data) == _hash_response(data)


def test_hash_response_order_independent() -> None:
    assert _hash_response({"a": 1, "b": 2}) == _hash_response({"b": 2, "a": 1})


# ---------------------------------------------------------------------------
# capture
# ---------------------------------------------------------------------------


async def test_capture_persists_snapshot_and_returns_model() -> None:
    factory, session = _make_session_factory()

    mock_repo = AsyncMock()
    mock_repo.create = AsyncMock()

    with patch(
        "syndicateclaw.orchestrator.snapshots.InputSnapshotRepository",
        return_value=mock_repo,
    ):
        store = InputSnapshotStore(factory)
        snap = await store.capture(
            run_id="run-1",
            node_execution_id="node-exec-1",
            snapshot_type="tool_response",
            source_identifier="tool:http_request",
            request_data={"url": "https://example.com"},
            response_data={"status": 200},
        )

    assert snap.run_id == "run-1"
    assert snap.snapshot_type == "tool_response"
    assert len(snap.content_hash) == 64  # sha256 hex
    mock_repo.create.assert_awaited_once()


# ---------------------------------------------------------------------------
# get_frozen
# ---------------------------------------------------------------------------


async def test_get_frozen_returns_response_data_when_found() -> None:
    factory, _ = _make_session_factory()
    row = MagicMock()
    row.response_data = {"status": 200, "body": "ok"}

    mock_repo = AsyncMock()
    mock_repo.get_for_replay = AsyncMock(return_value=row)

    with patch(
        "syndicateclaw.orchestrator.snapshots.InputSnapshotRepository",
        return_value=mock_repo,
    ):
        store = InputSnapshotStore(factory)
        result = await store.get_frozen(
            original_run_id="run-1", source_identifier="tool:http_request"
        )

    assert result == {"status": 200, "body": "ok"}


async def test_get_frozen_returns_none_when_not_found() -> None:
    factory, _ = _make_session_factory()
    mock_repo = AsyncMock()
    mock_repo.get_for_replay = AsyncMock(return_value=None)

    with patch(
        "syndicateclaw.orchestrator.snapshots.InputSnapshotRepository",
        return_value=mock_repo,
    ):
        store = InputSnapshotStore(factory)
        result = await store.get_frozen(
            original_run_id="run-1", source_identifier="tool:http_request"
        )
    assert result is None


# ---------------------------------------------------------------------------
# get_run_snapshots
# ---------------------------------------------------------------------------


async def test_get_run_snapshots_returns_validated_models() -> None:
    factory, _ = _make_session_factory()
    row = _make_snapshot_row()

    mock_repo = AsyncMock()
    mock_repo.get_by_run = AsyncMock(return_value=[row])

    with (
        patch(
            "syndicateclaw.orchestrator.snapshots.InputSnapshotRepository",
            return_value=mock_repo,
        ),
        patch(
            "syndicateclaw.orchestrator.snapshots.InputSnapshot.model_validate",
            return_value=MagicMock(run_id="run-1"),
        ),
    ):
        store = InputSnapshotStore(factory)
        snaps = await store.get_run_snapshots("run-1")

    assert len(snaps) == 1


async def test_get_run_snapshots_empty() -> None:
    factory, _ = _make_session_factory()
    mock_repo = AsyncMock()
    mock_repo.get_by_run = AsyncMock(return_value=[])

    with patch(
        "syndicateclaw.orchestrator.snapshots.InputSnapshotRepository",
        return_value=mock_repo,
    ):
        store = InputSnapshotStore(factory)
        snaps = await store.get_run_snapshots("run-empty")
    assert snaps == []


# ---------------------------------------------------------------------------
# verify_snapshot_integrity
# ---------------------------------------------------------------------------


async def test_verify_snapshot_integrity_matches() -> None:
    response = {"status": 200}
    row = MagicMock()
    row.response_data = response
    row.content_hash = _hash_response(response)

    factory, _ = _make_session_factory(get_return=row)
    store = InputSnapshotStore(factory)
    assert await store.verify_snapshot_integrity("snap-1") is True


async def test_verify_snapshot_integrity_mismatch() -> None:
    row = MagicMock()
    row.response_data = {"status": 200}
    row.content_hash = "wrong-hash"

    factory, _ = _make_session_factory(get_return=row)
    store = InputSnapshotStore(factory)
    assert await store.verify_snapshot_integrity("snap-1") is False


async def test_verify_snapshot_integrity_not_found() -> None:
    factory, _ = _make_session_factory(get_return=None)
    store = InputSnapshotStore(factory)
    assert await store.verify_snapshot_integrity("missing") is False


# ---------------------------------------------------------------------------
# detect_replay_divergence
# ---------------------------------------------------------------------------


async def test_detect_replay_divergence_no_frozen_returns_none() -> None:
    factory, _ = _make_session_factory()
    store = InputSnapshotStore(factory)

    store.get_frozen = AsyncMock(return_value=None)  # type: ignore[method-assign]
    result = await store.detect_replay_divergence(
        run_id="run-1",
        source_identifier="tool:x",
        live_response={"data": "live"},
    )
    assert result is None


async def test_detect_replay_divergence_identical_returns_none() -> None:
    factory, _ = _make_session_factory()
    store = InputSnapshotStore(factory)

    frozen = {"data": "same"}
    store.get_frozen = AsyncMock(return_value=frozen)  # type: ignore[method-assign]
    result = await store.detect_replay_divergence(
        run_id="run-1",
        source_identifier="tool:x",
        live_response={"data": "same"},
    )
    assert result is None


async def test_detect_replay_divergence_different_returns_report() -> None:
    factory, _ = _make_session_factory()
    store = InputSnapshotStore(factory)

    store.get_frozen = AsyncMock(  # type: ignore[method-assign]
        return_value={"data": "frozen"}
    )
    result = await store.detect_replay_divergence(
        run_id="run-1",
        source_identifier="tool:x",
        live_response={"data": "live"},
    )
    assert result is not None
    assert result["run_id"] == "run-1"
    assert result["source_identifier"] == "tool:x"
    assert "frozen_hash" in result
    assert "live_hash" in result
