"""Tests for release-gate controls: cache isolation, ownership scoping, and HMAC signing.

These tests verify the three final residual controls before release readiness.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syndicateclaw.models import (
    AuditEvent,
    AuditEventType,
    MemoryDeletionStatus,
    MemoryLineage,
    MemoryRecord,
    MemoryType,
)
from syndicateclaw.security.signing import (
    derive_signing_key,
    sign_payload,
    sign_record,
    verify_record,
    verify_signature,
)

# =====================================================================
# 1. HMAC Signing
# =====================================================================


class TestHMACSigning:
    """Verify signing utility correctness and tamper detection."""

    def test_derive_signing_key_deterministic(self):
        k1 = derive_signing_key("secret-a")
        k2 = derive_signing_key("secret-a")
        assert k1 == k2

    def test_derive_signing_key_differs_per_secret(self):
        k1 = derive_signing_key("secret-a")
        k2 = derive_signing_key("secret-b")
        assert k1 != k2

    def test_sign_and_verify_roundtrip(self):
        key = derive_signing_key("test")
        payload = {"tool": "fetch", "url": "https://example.com", "ts": 12345}
        sig = sign_payload(payload, key)
        assert verify_signature(payload, sig, key)

    def test_verify_rejects_tampered_payload(self):
        key = derive_signing_key("test")
        payload = {"action": "execute", "risk": "high"}
        sig = sign_payload(payload, key)
        tampered = {**payload, "risk": "low"}
        assert not verify_signature(tampered, sig, key)

    def test_verify_rejects_wrong_key(self):
        k1 = derive_signing_key("real-key")
        k2 = derive_signing_key("wrong-key")
        payload = {"a": 1}
        sig = sign_payload(payload, k1)
        assert not verify_signature(payload, sig, k2)

    def test_sign_record_adds_integrity_field(self):
        key = derive_signing_key("test")
        rec = {"event_type": "TOOL_EXECUTED", "actor": "user:alice"}
        signed = sign_record(rec, key)
        assert "integrity_signature" in signed
        assert signed["event_type"] == "TOOL_EXECUTED"
        assert signed["actor"] == "user:alice"

    def test_verify_record_roundtrip(self):
        key = derive_signing_key("test")
        rec = {"event_type": "TOOL_EXECUTED", "details": {"tool": "fetch"}}
        signed = sign_record(rec, key)
        assert verify_record(signed, key)

    def test_verify_record_detects_tamper(self):
        key = derive_signing_key("test")
        signed = sign_record({"x": 1, "y": 2}, key)
        signed["x"] = 999
        assert not verify_record(signed, key)

    def test_verify_record_fails_without_signature(self):
        key = derive_signing_key("test")
        assert not verify_record({"no_sig": True}, key)

    def test_canonical_json_order_invariant(self):
        key = derive_signing_key("test")
        p1 = {"b": 2, "a": 1}
        p2 = {"a": 1, "b": 2}
        assert sign_payload(p1, key) == sign_payload(p2, key)


def _make_session_factory():
    """Create a mock async session factory with proper context manager protocol."""
    session = MagicMock()
    mock_result = MagicMock()
    mock_result.first.return_value = None
    mock_result.scalar.return_value = None
    session.execute = AsyncMock(return_value=mock_result)
    session.flush = AsyncMock()
    session.get = AsyncMock()

    tx_cm = MagicMock()
    tx_cm.__aenter__ = AsyncMock(return_value=None)
    tx_cm.__aexit__ = AsyncMock(return_value=False)
    session.begin = MagicMock(return_value=tx_cm)

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)

    factory = MagicMock(return_value=cm)
    return factory, session


class TestAuditServiceSigning:
    """Verify that AuditService signs events when a key is provided."""

    @pytest.mark.asyncio
    async def test_emit_signs_details_when_key_provided(self):
        from syndicateclaw.audit.service import AuditService

        key = derive_signing_key("audit-secret")
        factory, session = _make_session_factory()

        service = AuditService(factory, signing_key=key)

        event = AuditEvent.new(
            event_type=AuditEventType.TOOL_EXECUTION_COMPLETED,
            actor="user:bob",
            resource_type="tool",
            resource_id="tool-1",
            action="execute",
            details={"tool_name": "fetch", "status": "success"},
        )

        with patch("syndicateclaw.audit.service.AuditEventRepository") as mock_repo_cls:
            mock_repo = AsyncMock()
            mock_repo_cls.return_value = mock_repo
            await service.emit(event)

            call_args = mock_repo.append.call_args
            row = call_args[0][0]
            assert "integrity_signature" in row.details
            assert verify_record(row.details, key)

    @pytest.mark.asyncio
    async def test_emit_skips_signing_when_no_key(self):
        from syndicateclaw.audit.service import AuditService

        factory, session = _make_session_factory()
        service = AuditService(factory)

        event = AuditEvent.new(
            event_type=AuditEventType.TOOL_EXECUTION_COMPLETED,
            actor="user:bob",
            resource_type="tool",
            resource_id="tool-1",
            action="execute",
            details={"tool_name": "fetch"},
        )

        with patch("syndicateclaw.audit.service.AuditEventRepository") as mock_repo_cls:
            mock_repo = AsyncMock()
            mock_repo_cls.return_value = mock_repo
            await service.emit(event)

            row = mock_repo.append.call_args[0][0]
            assert "integrity_signature" not in row.details


class TestDecisionLedgerSigning:
    """Verify that DecisionLedger signs records when a key is provided."""

    @pytest.mark.asyncio
    async def test_record_appends_hmac_to_side_effects(self):
        from syndicateclaw.audit.ledger import DecisionLedger
        from syndicateclaw.models import DecisionDomain

        key = derive_signing_key("ledger-secret")

        session_mock = AsyncMock()
        session_mock.__aenter__ = AsyncMock(return_value=session_mock)
        session_mock.__aexit__ = AsyncMock(return_value=False)
        session_mock.begin = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(),
                __aexit__=AsyncMock(return_value=False),
            ),
        )
        factory = MagicMock(return_value=session_mock)

        ledger = DecisionLedger(factory, signing_key=key)

        with patch("syndicateclaw.audit.ledger.DecisionRecordRepository") as mock_repo_cls:
            mock_repo = AsyncMock()
            mock_repo_cls.return_value = mock_repo

            decision = await ledger.record(
                domain=DecisionDomain.TOOL_EXECUTION,
                decision_type="tool_invocation",
                actor="user:alice",
                inputs={"tool_name": "fetch", "url": "https://example.com"},
                rules_evaluated=[],
                matched_rule=None,
                effect="ALLOW",
                justification="Policy allowed",
            )

            assert any(se.startswith("hmac:") for se in decision.side_effects)

    @pytest.mark.asyncio
    async def test_record_no_hmac_without_key(self):
        from syndicateclaw.audit.ledger import DecisionLedger
        from syndicateclaw.models import DecisionDomain

        session_mock = AsyncMock()
        session_mock.__aenter__ = AsyncMock(return_value=session_mock)
        session_mock.__aexit__ = AsyncMock(return_value=False)
        session_mock.begin = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(),
                __aexit__=AsyncMock(return_value=False),
            ),
        )
        factory = MagicMock(return_value=session_mock)

        ledger = DecisionLedger(factory)

        with patch("syndicateclaw.audit.ledger.DecisionRecordRepository") as mock_repo_cls:
            mock_repo = AsyncMock()
            mock_repo_cls.return_value = mock_repo

            decision = await ledger.record(
                domain=DecisionDomain.TOOL_EXECUTION,
                decision_type="tool_invocation",
                actor="user:alice",
                inputs={"tool_name": "fetch"},
                rules_evaluated=[],
                matched_rule=None,
                effect="ALLOW",
                justification="ok",
            )

            assert not any(se.startswith("hmac:") for se in decision.side_effects)


class TestExportBundleSigning:
    """Verify evidence bundle HMAC."""

    @pytest.mark.asyncio
    async def test_export_includes_hmac_when_key_provided(self):
        from syndicateclaw.audit.export import RunExporter

        key = derive_signing_key("export-secret")

        run_mock = MagicMock()
        run_mock.__table__ = MagicMock()
        run_mock.__table__.columns = []
        run_mock.version_manifest = {"tools": "v1"}

        session_mock = AsyncMock()
        session_mock.__aenter__ = AsyncMock(return_value=session_mock)
        session_mock.__aexit__ = AsyncMock(return_value=False)
        session_mock.get = AsyncMock(return_value=run_mock)

        empty_result = MagicMock()
        empty_result.scalars.return_value.all.return_value = []
        session_mock.execute = AsyncMock(return_value=empty_result)

        factory = MagicMock(return_value=session_mock)

        exporter = RunExporter(factory, signing_key=key)
        bundle = await exporter.export_run("run-001")

        assert "bundle_hmac" in bundle
        assert "bundle_hash" in bundle
        assert verify_signature(
            {k: v for k, v in bundle.items() if k != "bundle_hmac"},
            bundle["bundle_hmac"],
            key,
        )


# =====================================================================
# 2. Memory Cache Isolation
# =====================================================================


def _make_record(
    access_policy: str = "default",
    actor: str = "user:alice",
    namespace: str = "ns",
    key: str = "k1",
) -> MemoryRecord:
    return MemoryRecord(
        id="rec-1",
        namespace=namespace,
        key=key,
        value={"data": "test"},
        memory_type=MemoryType.STRUCTURED,
        source="test",
        actor=actor,
        confidence=1.0,
        access_policy=access_policy,
        lineage=MemoryLineage(),
        deletion_status=MemoryDeletionStatus.ACTIVE,
        tags={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


class TestMemoryCacheIsolation:
    """Cache must not leak protected records across actors."""

    @pytest.mark.asyncio
    async def test_owner_only_record_not_cached(self):
        """Records with non-default access_policy should not be written to cache."""
        from syndicateclaw.memory.service import MemoryService

        redis_mock = AsyncMock()
        redis_mock.get = AsyncMock(return_value=None)
        redis_mock.setex = AsyncMock()

        record = _make_record(access_policy="owner_only", actor="user:alice")

        factory, session = _make_session_factory()
        db_record_mock = MagicMock()

        service = MemoryService(factory, redis_client=redis_mock)

        with patch.object(service, "_db_to_domain", return_value=record), \
             patch("syndicateclaw.memory.service.MemoryRecordRepository") as mock_repo_cls, \
             patch("syndicateclaw.memory.service.AuditEventRepository") as mock_audit_cls:
            mock_repo = AsyncMock()
            mock_repo.get_by_key = AsyncMock(return_value=db_record_mock)
            mock_repo_cls.return_value = mock_repo
            mock_audit_cls.return_value = AsyncMock()

            result = await service.read("ns", "k1", "user:alice")

        assert result is not None
        redis_mock.setex.assert_not_called()

    @pytest.mark.asyncio
    async def test_default_record_is_cached(self):
        """Records with default access_policy should be cached normally."""
        from syndicateclaw.memory.service import MemoryService

        redis_mock = AsyncMock()
        redis_mock.get = AsyncMock(return_value=None)
        redis_mock.setex = AsyncMock()

        record = _make_record(access_policy="default", actor="user:alice")

        factory, session = _make_session_factory()
        db_record_mock = MagicMock()

        service = MemoryService(factory, redis_client=redis_mock)

        with patch.object(service, "_db_to_domain", return_value=record), \
             patch("syndicateclaw.memory.service.MemoryRecordRepository") as mock_repo_cls, \
             patch("syndicateclaw.memory.service.AuditEventRepository") as mock_audit_cls:
            mock_repo = AsyncMock()
            mock_repo.get_by_key = AsyncMock(return_value=db_record_mock)
            mock_repo_cls.return_value = mock_repo
            mock_audit_cls.return_value = AsyncMock()

            result = await service.read("ns", "k1", "user:anyone")

        assert result is not None
        redis_mock.setex.assert_called_once()

    @pytest.mark.asyncio
    async def test_cached_owner_only_denied_to_other_actor(self):
        """If a protected record is somehow in cache, access check still blocks other actors."""
        from syndicateclaw.memory.service import MemoryService

        record = _make_record(access_policy="owner_only", actor="user:alice")
        redis_mock = AsyncMock()
        redis_mock.get = AsyncMock(return_value=record.model_dump_json())

        factory = MagicMock()
        service = MemoryService(factory, redis_client=redis_mock)

        result = await service.read("ns", "k1", "user:bob")
        assert result is None

    @pytest.mark.asyncio
    async def test_cached_owner_only_allowed_to_owner(self):
        """Cache hit with owner_only policy returns record to the owner."""
        from syndicateclaw.memory.service import MemoryService

        record = _make_record(access_policy="owner_only", actor="user:alice")
        redis_mock = AsyncMock()
        redis_mock.get = AsyncMock(return_value=record.model_dump_json())

        factory = MagicMock()
        service = MemoryService(factory, redis_client=redis_mock)

        result = await service.read("ns", "k1", "user:alice")
        assert result is not None
        assert result.id == "rec-1"

    @pytest.mark.asyncio
    async def test_system_only_denied_from_cache_to_regular_user(self):
        """system_only record in cache is denied to non-system actors."""
        from syndicateclaw.memory.service import MemoryService

        record = _make_record(access_policy="system_only", actor="system:core")
        redis_mock = AsyncMock()
        redis_mock.get = AsyncMock(return_value=record.model_dump_json())

        factory = MagicMock()
        service = MemoryService(factory, redis_client=redis_mock)

        result = await service.read("ns", "k1", "user:alice")
        assert result is None

    @pytest.mark.asyncio
    async def test_system_only_allowed_from_cache_to_system_actor(self):
        """system_only record in cache is accessible to system: actors."""
        from syndicateclaw.memory.service import MemoryService

        record = _make_record(access_policy="system_only", actor="system:core")
        redis_mock = AsyncMock()
        redis_mock.get = AsyncMock(return_value=record.model_dump_json())

        factory = MagicMock()
        service = MemoryService(factory, redis_client=redis_mock)

        result = await service.read("ns", "k1", "system:scheduler")
        assert result is not None


# =====================================================================
# 3. Ownership Filtering
# =====================================================================


class TestOwnershipFiltering:
    """Verify list endpoints scope results to the requesting actor."""

    def test_workflow_list_query_filters_by_owner(self):
        """The list_workflows endpoint should filter by WFModel.owner == actor."""
        import inspect

        from syndicateclaw.api.routes.workflows import list_workflows

        source = inspect.getsource(list_workflows)
        assert "WFModel.owner == actor" in source, (
            "list_workflows must filter by owner"
        )

    def test_run_list_query_filters_by_initiated_by(self):
        """The list_runs endpoint should filter by RunModel.initiated_by == actor."""
        import inspect

        from syndicateclaw.api.routes.workflows import list_runs

        source = inspect.getsource(list_runs)
        assert "RunModel.initiated_by == actor" in source, (
            "list_runs must filter by initiated_by"
        )

    def test_approvals_list_scoped_to_actor(self):
        """Approvals list should filter by assigned_to or requested_by."""
        import inspect

        from syndicateclaw.api.routes.approvals import list_pending_approvals

        source = inspect.getsource(list_pending_approvals)
        assert "ARModel.assigned_to.contains([actor])" in source
        assert "ARModel.requested_by == actor" in source


class TestAccessPolicyLogic:
    """Verify the MemoryService._check_access_policy static method directly."""

    def test_default_allows_anyone(self):
        from syndicateclaw.memory.service import MemoryService
        rec = _make_record(access_policy="default")
        assert MemoryService._check_access_policy(rec, "user:stranger") is True

    def test_owner_only_allows_owner(self):
        from syndicateclaw.memory.service import MemoryService
        rec = _make_record(access_policy="owner_only", actor="user:alice")
        assert MemoryService._check_access_policy(rec, "user:alice") is True

    def test_owner_only_denies_other(self):
        from syndicateclaw.memory.service import MemoryService
        rec = _make_record(access_policy="owner_only", actor="user:alice")
        assert MemoryService._check_access_policy(rec, "user:bob") is False

    def test_system_only_allows_system(self):
        from syndicateclaw.memory.service import MemoryService
        rec = _make_record(access_policy="system_only", actor="system:core")
        assert MemoryService._check_access_policy(rec, "system:scheduler") is True

    def test_system_only_denies_user(self):
        from syndicateclaw.memory.service import MemoryService
        rec = _make_record(access_policy="system_only", actor="system:core")
        assert MemoryService._check_access_policy(rec, "user:alice") is False

    def test_restricted_allows_record_actor(self):
        from syndicateclaw.memory.service import MemoryService
        rec = _make_record(access_policy="restricted", actor="user:alice")
        assert MemoryService._check_access_policy(rec, "user:alice") is True

    def test_restricted_denies_other(self):
        from syndicateclaw.memory.service import MemoryService
        rec = _make_record(access_policy="restricted", actor="user:alice")
        assert MemoryService._check_access_policy(rec, "user:bob") is False

    def test_unknown_policy_fails_closed(self):
        from syndicateclaw.memory.service import MemoryService
        rec = _make_record(access_policy="nonexistent_policy")
        assert MemoryService._check_access_policy(rec, "user:alice") is False


class TestSigningKeyWiring:
    """Verify the signing key is derived and wired in the app lifespan."""

    @pytest.fixture(autouse=True)
    def _env_vars(self, monkeypatch):
        monkeypatch.setenv("SYNDICATECLAW_DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
        monkeypatch.setenv("SYNDICATECLAW_SECRET_KEY", "test-secret-key")

    def _get_lifespan_source(self):
        import importlib
        import inspect

        import syndicateclaw.api.main as main_mod
        importlib.reload(main_mod)
        return inspect.getsource(main_mod.lifespan)

    def test_lifespan_creates_signing_key(self):
        source = self._get_lifespan_source()
        assert "derive_signing_key" in source
        assert "signing_key" in source
        assert "app.state.signing_key" in source

    def test_lifespan_passes_key_to_audit_service(self):
        source = self._get_lifespan_source()
        assert "AuditService(session_factory, signing_key=signing_key)" in source

    def test_lifespan_passes_key_to_decision_ledger(self):
        source = self._get_lifespan_source()
        assert "DecisionLedger(session_factory, signing_key=signing_key)" in source
