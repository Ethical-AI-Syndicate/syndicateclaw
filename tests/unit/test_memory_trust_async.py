"""Mocked unit tests for MemoryTrustService async DB methods."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from syndicateclaw.memory.trust import MemoryTrustService


def _make_session_factory(records=(), get_return=None):
    """Return a mock session factory that yields a mock session."""
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = list(records)

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


def _make_record(**kwargs):
    """Return a MagicMock shaped like a DBMemoryRecord."""
    rec = MagicMock()
    defaults = {
        "last_validated_at": datetime.now(UTC) - timedelta(days=1),
        "trust_score": 0.9,
        "decay_rate": 0.01,
        "trust_frozen": False,
        "updated_at": datetime.now(UTC),
        "source_type": "HUMAN",
        "namespace": "ns",
        "key": "k",
        "value": "v",
        "deletion_status": "active",
        "conflict_set_id": None,
        "id": "rec-1",
        "validation_count": 0,
    }
    defaults.update(kwargs)
    for attr, val in defaults.items():
        setattr(rec, attr, val)
    return rec


# ---------------------------------------------------------------------------
# apply_decay
# ---------------------------------------------------------------------------


async def test_apply_decay_no_records_returns_zero() -> None:
    factory = _make_session_factory(records=[])
    svc = MemoryTrustService(factory)
    count = await svc.apply_decay()
    assert count == 0


async def test_apply_decay_record_with_none_last_validated_skipped() -> None:
    rec = _make_record(last_validated_at=None, trust_score=0.9)
    factory = _make_session_factory(records=[rec])
    svc = MemoryTrustService(factory)
    count = await svc.apply_decay()
    assert count == 0


async def test_apply_decay_updates_score_and_counts_degraded() -> None:
    # Record with high decay rate to drop below threshold
    rec = _make_record(
        last_validated_at=datetime.now(UTC) - timedelta(days=100),
        trust_score=0.9,
        decay_rate=0.02,
    )
    factory = _make_session_factory(records=[rec])
    svc = MemoryTrustService(factory, min_usable_trust=0.5)
    count = await svc.apply_decay()
    assert count == 1
    assert rec.trust_score == 0.0  # clamped by max(0.0, ...)


async def test_apply_decay_no_change_when_score_unchanged() -> None:
    # Frozen-equivalent: new_score == trust_score (record with 0 elapsed)
    now = datetime.now(UTC)
    rec = _make_record(last_validated_at=now, trust_score=0.9, decay_rate=0.0)
    factory = _make_session_factory(records=[rec])
    svc = MemoryTrustService(factory)
    count = await svc.apply_decay()
    assert count == 0


# ---------------------------------------------------------------------------
# validate_record
# ---------------------------------------------------------------------------


async def test_validate_record_updates_trust_to_ceiling() -> None:
    rec = _make_record(source_type="HUMAN", trust_score=0.5)
    factory = _make_session_factory(get_return=rec)
    svc = MemoryTrustService(factory)
    new_trust = await svc.validate_record("rec-1", validator="admin")
    assert new_trust == 1.0  # human ceiling
    assert rec.trust_score == 1.0
    assert rec.validation_count == 1


async def test_validate_record_unknown_source_uses_default_ceiling() -> None:
    rec = _make_record(source_type="UNKNOWN_TYPE", trust_score=0.5)
    factory = _make_session_factory(get_return=rec)
    svc = MemoryTrustService(factory)
    new_trust = await svc.validate_record("rec-1", validator="admin")
    assert new_trust == 0.8  # default ceiling for unknown source types


async def test_validate_record_not_found_raises() -> None:
    factory = _make_session_factory(get_return=None)
    svc = MemoryTrustService(factory)
    with pytest.raises(ValueError, match="not found"):
        await svc.validate_record("missing-id", validator="admin")


# ---------------------------------------------------------------------------
# freeze_record
# ---------------------------------------------------------------------------


async def test_freeze_record_sets_frozen_flag() -> None:
    rec = _make_record(trust_frozen=False)
    factory = _make_session_factory(get_return=rec)
    svc = MemoryTrustService(factory)
    await svc.freeze_record("rec-1", actor="admin")
    assert rec.trust_frozen is True


async def test_freeze_record_not_found_raises() -> None:
    factory = _make_session_factory(get_return=None)
    svc = MemoryTrustService(factory)
    with pytest.raises(ValueError, match="not found"):
        await svc.freeze_record("missing-id", actor="admin")


# ---------------------------------------------------------------------------
# detect_conflicts
# ---------------------------------------------------------------------------


async def test_detect_conflicts_single_record_returns_empty() -> None:
    rec = _make_record(value="v1")
    factory = _make_session_factory(records=[rec])
    svc = MemoryTrustService(factory)
    result = await svc.detect_conflicts("ns", "k")
    assert result == []


async def test_detect_conflicts_same_values_returns_empty() -> None:
    r1 = _make_record(value="same", trust_frozen=False, trust_score=0.9, id="r1")
    r2 = _make_record(value="same", trust_frozen=False, trust_score=0.9, id="r2")
    factory = _make_session_factory(records=[r1, r2])
    svc = MemoryTrustService(factory)
    result = await svc.detect_conflicts("ns", "k")
    assert result == []


async def test_detect_conflicts_different_values_creates_conflict_set() -> None:
    r1 = _make_record(value="v1", trust_frozen=False, trust_score=0.9, id="r1")
    r2 = _make_record(value="v2", trust_frozen=False, trust_score=0.9, id="r2")
    factory = _make_session_factory(records=[r1, r2])
    svc = MemoryTrustService(factory)
    result = await svc.detect_conflicts("ns", "k")
    assert len(result) == 1
    assert r1.trust_score == pytest.approx(0.45)  # halved
    assert r2.trust_score == pytest.approx(0.45)


async def test_detect_conflicts_frozen_record_trust_not_halved() -> None:
    r1 = _make_record(value="v1", trust_frozen=True, trust_score=0.9, id="r1")
    r2 = _make_record(value="v2", trust_frozen=False, trust_score=0.9, id="r2")
    factory = _make_session_factory(records=[r1, r2])
    svc = MemoryTrustService(factory)
    await svc.detect_conflicts("ns", "k")
    assert r1.trust_score == 0.9  # frozen — unchanged
    assert r2.trust_score == pytest.approx(0.45)


# ---------------------------------------------------------------------------
# get_trust_report
# ---------------------------------------------------------------------------


async def test_get_trust_report_empty_namespace() -> None:
    factory = _make_session_factory(records=[])
    svc = MemoryTrustService(factory)
    report = await svc.get_trust_report("empty-ns")
    assert report == []


async def test_get_trust_report_returns_record_dict() -> None:
    rec = _make_record(
        id="rec-report",
        namespace="ns",
        key="mykey",
        source_type="HUMAN",
        trust_score=0.8,
        decay_rate=0.01,
        last_validated_at=None,
        trust_frozen=False,
        conflict_set_id=None,
    )
    factory = _make_session_factory(records=[rec])
    svc = MemoryTrustService(factory)
    report = await svc.get_trust_report("ns")
    assert len(report) == 1
    entry = report[0]
    assert entry["id"] == "rec-report"
    assert entry["key"] == "mykey"
    assert "effective_trust" in entry
    assert "usable" in entry
