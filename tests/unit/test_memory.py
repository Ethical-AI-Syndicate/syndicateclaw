from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from syndicateclaw.models import (
    MemoryDeletionStatus,
    MemoryLineage,
    MemoryRecord,
    MemoryType,
)


class TestMemoryRecordProvenance:
    def test_memory_record_provenance_required_source(self):
        """Source is a required field and cannot be omitted."""
        with pytest.raises((ValidationError, TypeError)):
            MemoryRecord.new(
                namespace="ns",
                key="k",
                value="v",
                memory_type=MemoryType.SEMANTIC,
                actor="actor",
                # source omitted
            )

    def test_memory_record_provenance_required_actor(self):
        """Actor is a required field and cannot be omitted."""
        with pytest.raises((ValidationError, TypeError)):
            MemoryRecord.new(
                namespace="ns",
                key="k",
                value="v",
                memory_type=MemoryType.SEMANTIC,
                source="src",
                # actor omitted
            )

    def test_memory_record_provenance_empty_rejected_by_service(self):
        """MemoryService._validate_provenance rejects empty source/actor."""
        from syndicateclaw.memory.service import MemoryService

        record = MemoryRecord.new(
            namespace="ns",
            key="k",
            value="v",
            memory_type=MemoryType.SEMANTIC,
            source="",
            actor="actor",
        )
        with pytest.raises(ValueError, match="source"):
            MemoryService._validate_provenance(record)

        record2 = MemoryRecord.new(
            namespace="ns",
            key="k",
            value="v",
            memory_type=MemoryType.SEMANTIC,
            source="src",
            actor="",
        )
        with pytest.raises(ValueError, match="actor"):
            MemoryService._validate_provenance(record2)

    def test_memory_record_provenance_valid(self):
        record = MemoryRecord.new(
            namespace="ns",
            key="k",
            value="v",
            memory_type=MemoryType.SEMANTIC,
            source="test-source",
            actor="test-actor",
        )
        assert record.source == "test-source"
        assert record.actor == "test-actor"


class TestMemoryLineageDefaults:
    def test_memory_record_lineage_defaults(self):
        record = MemoryRecord.new(
            namespace="ns",
            key="k",
            value="v",
            memory_type=MemoryType.EPISODIC,
            source="src",
            actor="actor",
        )
        assert record.lineage.parent_ids == []
        assert record.lineage.workflow_run_id is None
        assert record.lineage.node_execution_id is None
        assert record.lineage.tool_name is None
        assert record.lineage.derivation_method is None

    def test_memory_record_lineage_custom(self):
        lineage = MemoryLineage(
            parent_ids=["parent1"],
            workflow_run_id="wfr-001",
            derivation_method="llm_extraction",
        )
        record = MemoryRecord.new(
            namespace="ns",
            key="k",
            value="v",
            memory_type=MemoryType.STRUCTURED,
            source="src",
            actor="actor",
            lineage=lineage,
        )
        assert record.lineage.parent_ids == ["parent1"]
        assert record.lineage.workflow_run_id == "wfr-001"
        assert record.lineage.derivation_method == "llm_extraction"


class TestMemoryRecordTTL:
    def test_memory_record_ttl_calculation(self):
        record = MemoryRecord.new(
            namespace="ns",
            key="k",
            value="v",
            memory_type=MemoryType.EPISODIC,
            source="src",
            actor="actor",
            ttl_seconds=3600,
        )
        assert record.ttl_seconds == 3600

    def test_memory_record_ttl_none_by_default(self):
        record = MemoryRecord.new(
            namespace="ns",
            key="k",
            value="v",
            memory_type=MemoryType.EPISODIC,
            source="src",
            actor="actor",
        )
        assert record.ttl_seconds is None
        assert record.expires_at is None

    def test_memory_record_ttl_with_explicit_expiry(self):
        future = datetime.now(UTC) + timedelta(hours=2)
        record = MemoryRecord.new(
            namespace="ns",
            key="k",
            value="v",
            memory_type=MemoryType.EPISODIC,
            source="src",
            actor="actor",
            ttl_seconds=7200,
            expires_at=future,
        )
        assert record.ttl_seconds == 7200
        assert record.expires_at == future


class TestMemoryDeletionStatusLifecycle:
    def test_memory_deletion_status_lifecycle(self):
        record = MemoryRecord.new(
            namespace="ns",
            key="k",
            value="v",
            memory_type=MemoryType.SEMANTIC,
            source="src",
            actor="actor",
        )
        assert record.deletion_status == MemoryDeletionStatus.ACTIVE
        assert record.deleted_at is None

        record.deletion_status = MemoryDeletionStatus.MARKED_FOR_DELETION
        record.deleted_at = datetime.now(UTC)
        assert record.deletion_status == MemoryDeletionStatus.MARKED_FOR_DELETION
        assert record.deleted_at is not None

        record.deletion_status = MemoryDeletionStatus.DELETED
        assert record.deletion_status == MemoryDeletionStatus.DELETED

    def test_all_deletion_statuses_exist(self):
        expected = {"ACTIVE", "MARKED_FOR_DELETION", "DELETED"}
        actual = {s.value for s in MemoryDeletionStatus}
        assert actual == expected
