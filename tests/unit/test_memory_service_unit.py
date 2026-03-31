"""Unit tests for memory/service.py — MemoryService CRUD paths."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syndicateclaw.memory.service import MemoryService, _check_nesting_depth
from syndicateclaw.models import (
    MemoryDeletionStatus,
    MemoryRecord,
    MemoryType,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session_factory():
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_begin = AsyncMock()
    mock_begin.__aenter__ = AsyncMock(return_value=None)
    mock_begin.__aexit__ = AsyncMock(return_value=False)
    mock_session.begin = MagicMock(return_value=mock_begin)

    return MagicMock(return_value=mock_session)


def _make_domain_record(**overrides) -> MemoryRecord:
    defaults: dict[str, Any] = {
        "namespace": "ns",
        "key": "k",
        "value": {"data": "val"},
        "memory_type": MemoryType.SEMANTIC,
        "source": "test",
        "actor": "user:1",
    }
    defaults.update(overrides)
    return MemoryRecord.new(**defaults)


def _make_db_record(**overrides) -> MagicMock:
    rec = MagicMock()
    rec.id = "rec-1"
    rec.namespace = "ns"
    rec.key = "k"
    rec.value = {"data": "val"}
    rec.memory_type = "SEMANTIC"
    rec.source = "test"
    rec.actor = "user:1"
    rec.confidence = 1.0
    rec.access_policy = "default"
    rec.lineage = {}
    rec.ttl_seconds = None
    rec.expires_at = None
    rec.deletion_status = MemoryDeletionStatus.ACTIVE.value
    rec.deleted_at = None
    rec.tags = {}
    rec.created_at = datetime.now(UTC)
    rec.updated_at = datetime.now(UTC)
    for k, v in overrides.items():
        setattr(rec, k, v)
    return rec


def _make_service(**kwargs) -> MemoryService:
    return MemoryService(_make_session_factory(), **kwargs)


# ---------------------------------------------------------------------------
# _check_nesting_depth
# ---------------------------------------------------------------------------


def test_check_nesting_depth_flat_dict_ok() -> None:
    _check_nesting_depth({"a": 1}, max_depth=5, current=0)  # no exception


def test_check_nesting_depth_exceeds_raises() -> None:
    with pytest.raises(ValueError, match="nesting depth"):
        _check_nesting_depth({"a": {"b": {"c": {"d": {"e": {}}}}}}, max_depth=2, current=0)


def test_check_nesting_depth_list_ok() -> None:
    _check_nesting_depth([1, 2, [3]], max_depth=5, current=0)


# ---------------------------------------------------------------------------
# _validate_provenance / _validate_confidence / _validate_write_guardrails
# ---------------------------------------------------------------------------


def test_validate_provenance_missing_source_raises() -> None:
    rec = _make_domain_record(source="")
    with pytest.raises(ValueError, match="source"):
        MemoryService._validate_provenance(rec)


def test_validate_provenance_missing_actor_raises() -> None:
    rec = _make_domain_record(actor="")
    with pytest.raises(ValueError, match="actor"):
        MemoryService._validate_provenance(rec)


def test_validate_confidence_out_of_range_raises() -> None:
    MemoryService._validate_confidence(0.0)  # valid
    MemoryService._validate_confidence(1.0)  # valid
    with pytest.raises(ValueError, match="Confidence"):
        MemoryService._validate_confidence(1.1)
    with pytest.raises(ValueError, match="Confidence"):
        MemoryService._validate_confidence(-0.1)


def test_validate_write_guardrails_namespace_too_long() -> None:
    svc = MemoryService(_make_session_factory(), max_namespace_length=5)
    rec = _make_domain_record(namespace="toolongns")
    with pytest.raises(ValueError, match="Namespace too long"):
        svc._validate_write_guardrails(rec)


def test_validate_write_guardrails_key_too_long() -> None:
    svc = MemoryService(_make_session_factory(), max_key_length=3)
    rec = _make_domain_record(key="toolong")
    with pytest.raises(ValueError, match="Key too long"):
        svc._validate_write_guardrails(rec)


def test_validate_write_guardrails_value_too_large() -> None:
    svc = MemoryService(_make_session_factory(), max_value_bytes=5)
    rec = _make_domain_record(value={"data": "way too much data here"})
    with pytest.raises(ValueError, match="Value too large"):
        svc._validate_write_guardrails(rec)


# ---------------------------------------------------------------------------
# _check_access_policy
# ---------------------------------------------------------------------------


def test_check_access_policy_default_allows_any() -> None:
    rec = _make_domain_record()
    rec.access_policy = "default"
    assert MemoryService._check_access_policy(rec, "anyone") is True


def test_check_access_policy_owner_only() -> None:
    rec = _make_domain_record(actor="user:owner")
    rec.access_policy = "owner_only"
    assert MemoryService._check_access_policy(rec, "user:owner") is True
    assert MemoryService._check_access_policy(rec, "user:other") is False


def test_check_access_policy_system_only() -> None:
    rec = _make_domain_record()
    rec.access_policy = "system_only"
    assert MemoryService._check_access_policy(rec, "system:svc") is True
    assert MemoryService._check_access_policy(rec, "user:1") is False


def test_check_access_policy_restricted() -> None:
    rec = _make_domain_record(actor="user:owner")
    rec.access_policy = "restricted"
    assert MemoryService._check_access_policy(rec, "user:owner") is True
    assert MemoryService._check_access_policy(rec, "user:other") is False


def test_check_access_policy_unknown_denies() -> None:
    rec = _make_domain_record()
    rec.access_policy = "unknown_policy"
    assert MemoryService._check_access_policy(rec, "anyone") is False


# ---------------------------------------------------------------------------
# MemoryService.write
# ---------------------------------------------------------------------------


async def test_write_persists_record_and_returns_domain() -> None:
    factory = _make_session_factory()
    db_rec = _make_db_record()

    with patch("syndicateclaw.memory.service.MemoryRecordRepository") as MockRepo:
        mock_repo = AsyncMock()
        mock_repo.create = AsyncMock(return_value=db_rec)
        MockRepo.return_value = mock_repo

        with patch("syndicateclaw.memory.service.AuditEventRepository") as MockAudit:
            mock_audit = AsyncMock()
            mock_audit.append = AsyncMock()
            MockAudit.return_value = mock_audit

            svc = MemoryService(factory)
            result = await svc.write(_make_domain_record(), actor="user:1")

    assert result.id == "rec-1"
    mock_repo.create.assert_awaited_once()


async def test_write_sets_expires_at_from_ttl() -> None:
    factory = _make_session_factory()
    db_rec = _make_db_record()

    with patch("syndicateclaw.memory.service.MemoryRecordRepository") as MockRepo:
        mock_repo = AsyncMock()
        mock_repo.create = AsyncMock(return_value=db_rec)
        MockRepo.return_value = mock_repo

        with patch("syndicateclaw.memory.service.AuditEventRepository") as MockAudit:
            mock_audit = AsyncMock()
            mock_audit.append = AsyncMock()
            MockAudit.return_value = mock_audit

            svc = MemoryService(factory)
            rec = _make_domain_record()
            rec.ttl_seconds = 3600
            rec.expires_at = None
            await svc.write(rec, actor="user:1")

    # expires_at should have been set
    assert rec.expires_at is not None


async def test_write_validates_provenance_before_persist() -> None:
    factory = _make_session_factory()
    svc = MemoryService(factory)
    bad_rec = _make_domain_record(source="")
    with pytest.raises(ValueError, match="source"):
        await svc.write(bad_rec, actor="user:1")


# ---------------------------------------------------------------------------
# MemoryService.read
# ---------------------------------------------------------------------------


async def test_read_returns_none_for_missing_record() -> None:
    factory = _make_session_factory()

    with patch("syndicateclaw.memory.service.MemoryRecordRepository") as MockRepo:
        mock_repo = AsyncMock()
        mock_repo.get_by_key = AsyncMock(return_value=None)
        MockRepo.return_value = mock_repo

        svc = MemoryService(factory)
        result = await svc.read("ns", "k", actor="user:1")

    assert result is None


async def test_read_returns_none_for_deleted_record() -> None:
    factory = _make_session_factory()
    db_rec = _make_db_record(deletion_status=MemoryDeletionStatus.MARKED_FOR_DELETION.value)

    with patch("syndicateclaw.memory.service.MemoryRecordRepository") as MockRepo:
        mock_repo = AsyncMock()
        mock_repo.get_by_key = AsyncMock(return_value=db_rec)
        MockRepo.return_value = mock_repo

        svc = MemoryService(factory)
        result = await svc.read("ns", "k", actor="user:1")

    assert result is None


async def test_read_returns_none_for_expired_record() -> None:
    factory = _make_session_factory()
    db_rec = _make_db_record(expires_at=datetime.now(UTC) - timedelta(hours=1))

    with patch("syndicateclaw.memory.service.MemoryRecordRepository") as MockRepo:
        mock_repo = AsyncMock()
        mock_repo.get_by_key = AsyncMock(return_value=db_rec)
        MockRepo.return_value = mock_repo

        svc = MemoryService(factory)
        result = await svc.read("ns", "k", actor="user:1")

    assert result is None


async def test_read_returns_none_when_access_denied() -> None:
    factory = _make_session_factory()
    db_rec = _make_db_record(access_policy="owner_only", actor="user:owner")

    with patch("syndicateclaw.memory.service.MemoryRecordRepository") as MockRepo:
        mock_repo = AsyncMock()
        mock_repo.get_by_key = AsyncMock(return_value=db_rec)
        MockRepo.return_value = mock_repo

        svc = MemoryService(factory)
        result = await svc.read("ns", "k", actor="user:other")

    assert result is None


async def test_read_returns_record_and_emits_audit() -> None:
    factory = _make_session_factory()
    db_rec = _make_db_record()

    with patch("syndicateclaw.memory.service.MemoryRecordRepository") as MockRepo:
        mock_repo = AsyncMock()
        mock_repo.get_by_key = AsyncMock(return_value=db_rec)
        MockRepo.return_value = mock_repo

        with patch("syndicateclaw.memory.service.AuditEventRepository") as MockAudit:
            mock_audit = AsyncMock()
            mock_audit.append = AsyncMock()
            MockAudit.return_value = mock_audit

            svc = MemoryService(factory)
            result = await svc.read("ns", "k", actor="user:1")

    assert result is not None
    mock_audit.append.assert_awaited_once()


async def test_read_cache_hit_returns_early() -> None:
    factory = _make_session_factory()
    cached_rec = _make_domain_record()

    redis = AsyncMock()
    redis.get = AsyncMock(return_value=cached_rec.model_dump_json().encode())

    svc = MemoryService(factory, redis_client=redis)
    result = await svc.read("ns", "k", actor="user:1")

    assert result is not None


async def test_read_cache_hit_access_denied() -> None:
    factory = _make_session_factory()
    cached_rec = _make_domain_record(actor="user:owner")
    cached_rec.access_policy = "owner_only"

    redis = AsyncMock()
    redis.get = AsyncMock(return_value=cached_rec.model_dump_json().encode())

    svc = MemoryService(factory, redis_client=redis)
    result = await svc.read("ns", "k", actor="user:other")

    assert result is None


# ---------------------------------------------------------------------------
# MemoryService.update
# ---------------------------------------------------------------------------


async def test_update_raises_if_not_found() -> None:
    factory = _make_session_factory()

    with patch("syndicateclaw.memory.service.MemoryRecordRepository") as MockRepo:
        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=None)
        MockRepo.return_value = mock_repo

        svc = MemoryService(factory)
        with pytest.raises(ValueError, match="not found"):
            await svc.update("missing", {"confidence": 0.5}, actor="user:1")


async def test_update_raises_if_deleted() -> None:
    factory = _make_session_factory()
    db_rec = _make_db_record(deletion_status=MemoryDeletionStatus.MARKED_FOR_DELETION.value)

    with patch("syndicateclaw.memory.service.MemoryRecordRepository") as MockRepo:
        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=db_rec)
        MockRepo.return_value = mock_repo

        svc = MemoryService(factory)
        with pytest.raises(ValueError, match="deleted"):
            await svc.update("rec-1", {"confidence": 0.5}, actor="user:1")


async def test_update_raises_on_invalid_field() -> None:
    factory = _make_session_factory()
    db_rec = _make_db_record()

    with patch("syndicateclaw.memory.service.MemoryRecordRepository") as MockRepo:
        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=db_rec)
        MockRepo.return_value = mock_repo

        svc = MemoryService(factory)
        with pytest.raises(ValueError, match="Cannot update field"):
            await svc.update("rec-1", {"namespace": "new-ns"}, actor="user:1")


async def test_update_happy_path() -> None:
    factory = _make_session_factory()
    db_rec = _make_db_record()

    with patch("syndicateclaw.memory.service.MemoryRecordRepository") as MockRepo:
        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=db_rec)
        mock_repo.update = AsyncMock(return_value=db_rec)
        MockRepo.return_value = mock_repo

        with patch("syndicateclaw.memory.service.AuditEventRepository") as MockAudit:
            mock_audit = AsyncMock()
            mock_audit.append = AsyncMock()
            MockAudit.return_value = mock_audit

            svc = MemoryService(factory)
            result = await svc.update("rec-1", {"confidence": 0.8}, actor="user:1")

    assert result is not None


# ---------------------------------------------------------------------------
# MemoryService.delete
# ---------------------------------------------------------------------------


async def test_delete_soft_marks_for_deletion() -> None:
    factory = _make_session_factory()
    db_rec = _make_db_record()

    with patch("syndicateclaw.memory.service.MemoryRecordRepository") as MockRepo:
        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=db_rec)
        mock_repo.update = AsyncMock(return_value=db_rec)
        MockRepo.return_value = mock_repo

        with patch("syndicateclaw.memory.service.AuditEventRepository") as MockAudit:
            mock_audit = AsyncMock()
            mock_audit.append = AsyncMock()
            MockAudit.return_value = mock_audit

            svc = MemoryService(factory)
            await svc.delete("rec-1", actor="user:1")

    assert db_rec.deletion_status == MemoryDeletionStatus.MARKED_FOR_DELETION.value


async def test_delete_soft_raises_if_not_found() -> None:
    factory = _make_session_factory()

    with patch("syndicateclaw.memory.service.MemoryRecordRepository") as MockRepo:
        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=None)
        MockRepo.return_value = mock_repo

        svc = MemoryService(factory)
        with pytest.raises(ValueError, match="not found"):
            await svc.delete("missing", actor="user:1")


async def test_delete_hard_calls_repo_delete() -> None:
    factory = _make_session_factory()
    db_rec = _make_db_record()

    with patch("syndicateclaw.memory.service.MemoryRecordRepository") as MockRepo:
        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=db_rec)
        mock_repo.delete = AsyncMock()
        MockRepo.return_value = mock_repo

        with patch("syndicateclaw.memory.service.AuditEventRepository") as MockAudit:
            mock_audit = AsyncMock()
            mock_audit.append = AsyncMock()
            MockAudit.return_value = mock_audit

            svc = MemoryService(factory)
            await svc.delete("rec-1", actor="user:1", hard=True)

    mock_repo.delete.assert_awaited_once_with("rec-1")


async def test_delete_hard_no_op_if_not_found() -> None:
    factory = _make_session_factory()

    with patch("syndicateclaw.memory.service.MemoryRecordRepository") as MockRepo:
        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=None)
        mock_repo.delete = AsyncMock()
        MockRepo.return_value = mock_repo

        svc = MemoryService(factory)
        await svc.delete("missing", actor="user:1", hard=True)

    mock_repo.delete.assert_not_awaited()


# ---------------------------------------------------------------------------
# MemoryService.enforce_retention
# ---------------------------------------------------------------------------


async def test_enforce_retention_returns_purged_count() -> None:
    factory = _make_session_factory()

    with patch("syndicateclaw.memory.service.MemoryRecordRepository") as MockRepo:
        mock_repo = AsyncMock()
        mock_repo.purge_expired = AsyncMock(return_value=7)
        MockRepo.return_value = mock_repo

        with patch("syndicateclaw.memory.service.AuditEventRepository") as MockAudit:
            mock_audit = AsyncMock()
            mock_audit.append = AsyncMock()
            MockAudit.return_value = mock_audit

            svc = MemoryService(factory)
            count = await svc.enforce_retention()

    assert count == 7


async def test_enforce_retention_no_purge_skips_audit() -> None:
    factory = _make_session_factory()

    with patch("syndicateclaw.memory.service.MemoryRecordRepository") as MockRepo:
        mock_repo = AsyncMock()
        mock_repo.purge_expired = AsyncMock(return_value=0)
        MockRepo.return_value = mock_repo

        with patch("syndicateclaw.memory.service.AuditEventRepository") as MockAudit:
            mock_audit = AsyncMock()
            mock_audit.append = AsyncMock()
            MockAudit.return_value = mock_audit

            svc = MemoryService(factory)
            count = await svc.enforce_retention()

    assert count == 0
    mock_audit.append.assert_not_awaited()


# ---------------------------------------------------------------------------
# MemoryService.search — filter and access policy
# ---------------------------------------------------------------------------


async def test_search_filters_deleted_records() -> None:
    factory = _make_session_factory()
    db_rec = _make_db_record(deletion_status=MemoryDeletionStatus.MARKED_FOR_DELETION.value)

    with patch("syndicateclaw.memory.service.MemoryRecordRepository") as MockRepo:
        mock_repo = AsyncMock()
        mock_repo.get_by_namespace = AsyncMock(return_value=[db_rec])
        MockRepo.return_value = mock_repo

        with patch("syndicateclaw.memory.service.AuditEventRepository") as MockAudit:
            mock_audit = AsyncMock()
            mock_audit.append = AsyncMock()
            MockAudit.return_value = mock_audit

            svc = MemoryService(factory)
            results = await svc.search("ns", {}, actor="user:1")

    assert results == []


async def test_search_filters_by_access_policy() -> None:
    factory = _make_session_factory()
    db_rec = _make_db_record(access_policy="owner_only", actor="user:owner")

    with patch("syndicateclaw.memory.service.MemoryRecordRepository") as MockRepo:
        mock_repo = AsyncMock()
        mock_repo.get_by_namespace = AsyncMock(return_value=[db_rec])
        MockRepo.return_value = mock_repo

        with patch("syndicateclaw.memory.service.AuditEventRepository") as MockAudit:
            mock_audit = AsyncMock()
            mock_audit.append = AsyncMock()
            MockAudit.return_value = mock_audit

            svc = MemoryService(factory)
            results = await svc.search("ns", {}, actor="user:other")

    assert results == []
