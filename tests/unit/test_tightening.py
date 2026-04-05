"""Tests for tightening controls: readyz rate limit, asymmetric signing gate,
API key lifecycle, and memory write guardrails.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syndicateclaw.models import (
    MemoryDeletionStatus,
    MemoryLineage,
    MemoryRecord,
    MemoryType,
)

# =====================================================================
# 1. Readyz Rate Limiting Status
# =====================================================================


class TestReadyzRateLimitStatus:
    """Verify /readyz reports rate limiting posture."""

    @pytest.fixture(autouse=True)
    def _env(self, monkeypatch):
        monkeypatch.setenv("SYNDICATECLAW_DATABASE_URL", "postgresql+asyncpg://syndicateclaw:syndicateclaw@postgres:5432/syndicateclaw_test")
        monkeypatch.setenv("SYNDICATECLAW_SECRET_KEY", "test-key")

    def test_readyz_includes_rate_limiting_check(self) -> None:
        import importlib
        import inspect

        import syndicateclaw.api.main as main_mod

        importlib.reload(main_mod)
        source = inspect.getsource(main_mod.create_app)
        assert "rate_limiting" in source

    def test_config_has_rate_limit_strict(self) -> None:
        from syndicateclaw.config import Settings

        s = Settings()
        assert hasattr(s, "rate_limit_strict")
        assert s.rate_limit_strict is False

    def test_strict_mode_config(self, monkeypatch) -> None:
        monkeypatch.setenv("SYNDICATECLAW_RATE_LIMIT_STRICT", "true")
        from syndicateclaw.config import Settings

        s = Settings()
        assert s.rate_limit_strict is True


# =====================================================================
# 2. Asymmetric Signing Gate
# =====================================================================


class TestAsymmetricSigningGate:
    """Verify the system enforces Ed25519 key requirement when configured."""

    @pytest.fixture(autouse=True)
    def _env(self, monkeypatch):
        monkeypatch.setenv("SYNDICATECLAW_DATABASE_URL", "postgresql+asyncpg://syndicateclaw:syndicateclaw@postgres:5432/syndicateclaw_test")
        monkeypatch.setenv("SYNDICATECLAW_SECRET_KEY", "test-key")

    def test_config_has_require_asymmetric_signing(self) -> None:
        from syndicateclaw.config import Settings

        s = Settings()
        assert hasattr(s, "require_asymmetric_signing")
        assert s.require_asymmetric_signing is False

    def test_config_has_ed25519_key_path(self) -> None:
        from syndicateclaw.config import Settings

        s = Settings()
        assert hasattr(s, "ed25519_private_key_path")
        assert s.ed25519_private_key_path is None

    def test_lifespan_enforces_key_requirement(self) -> None:
        import importlib
        import inspect

        import syndicateclaw.api.main as main_mod

        importlib.reload(main_mod)
        source = inspect.getsource(main_mod.lifespan)
        assert "require_asymmetric_signing" in source
        assert "RuntimeError" in source
        assert "asymmetric_keypair" in source

    def test_ed25519_key_file_loading(self, tmp_path) -> None:
        from syndicateclaw.security.signing import SigningKeyPair

        kp = SigningKeyPair()
        key_file = tmp_path / "test_key.pem"
        key_file.write_bytes(kp.private_key_pem)

        loaded = SigningKeyPair(private_key_bytes=key_file.read_bytes())
        payload = {"test": True}
        sig = kp.sign(payload)
        assert loaded.verify(payload, sig)


# =====================================================================
# 3. API Key Lifecycle
# =====================================================================


class TestApiKeyHashing:
    """Verify key hashing is correct."""

    def test_key_hash_is_sha256(self) -> None:
        from syndicateclaw.security.api_keys import _hash_key

        raw = "sc-test-key-12345"
        expected = hashlib.sha256(raw.encode()).hexdigest()
        assert _hash_key(raw) == expected

    def test_hash_differs_for_different_keys(self) -> None:
        from syndicateclaw.security.api_keys import _hash_key

        assert _hash_key("key-a") != _hash_key("key-b")


class TestApiKeyServiceCreate:
    """Verify key creation returns key_id and raw key."""

    @pytest.mark.asyncio
    async def test_create_returns_id_and_raw_key(self) -> None:
        from syndicateclaw.security.api_keys import ApiKeyService

        session = MagicMock()
        session.add = MagicMock()
        session.flush = AsyncMock()
        tx = MagicMock()
        tx.__aenter__ = AsyncMock(return_value=None)
        tx.__aexit__ = AsyncMock(return_value=False)
        session.begin = MagicMock(return_value=tx)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)
        factory = MagicMock(return_value=cm)

        service = ApiKeyService(factory)

        with patch("syndicateclaw.security.api_keys.ApiKeyRow") as mock_row_cls:
            mock_row = MagicMock()
            mock_row.id = "key-001"
            mock_row_cls.return_value = mock_row

            key_id, raw_key = await service.create_key("user:alice", "test key")

        assert key_id == "key-001"
        assert raw_key.startswith("sc-")
        assert len(raw_key) > 20


class TestApiKeyServiceVerify:
    """Verify key validation handles valid, revoked, and expired keys."""

    @pytest.mark.asyncio
    async def test_verify_returns_actor_for_valid_key(self) -> None:
        from syndicateclaw.security.api_keys import ApiKeyService

        row = MagicMock()
        row.actor = "user:bob"
        row.revoked = False
        row.expires_at = None
        row.key_prefix = "sc-xxxx"

        session = MagicMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = row
        session.execute = AsyncMock(return_value=result_mock)
        tx = MagicMock()
        tx.__aenter__ = AsyncMock(return_value=None)
        tx.__aexit__ = AsyncMock(return_value=False)
        session.begin = MagicMock(return_value=tx)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)
        factory = MagicMock(return_value=cm)

        service = ApiKeyService(factory)
        actor = await service.verify_key("sc-test-key")
        assert actor == "user:bob"

    @pytest.mark.asyncio
    async def test_verify_returns_none_for_revoked_key(self) -> None:
        from syndicateclaw.security.api_keys import ApiKeyService

        row = MagicMock()
        row.revoked = True
        row.key_prefix = "sc-xxxx"

        session = MagicMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = row
        session.execute = AsyncMock(return_value=result_mock)
        tx = MagicMock()
        tx.__aenter__ = AsyncMock(return_value=None)
        tx.__aexit__ = AsyncMock(return_value=False)
        session.begin = MagicMock(return_value=tx)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)
        factory = MagicMock(return_value=cm)

        service = ApiKeyService(factory)
        assert await service.verify_key("sc-test") is None

    @pytest.mark.asyncio
    async def test_verify_returns_none_for_expired_key(self) -> None:
        from syndicateclaw.security.api_keys import ApiKeyService

        row = MagicMock()
        row.revoked = False
        row.expires_at = datetime.now(UTC) - timedelta(hours=1)
        row.key_prefix = "sc-xxxx"

        session = MagicMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = row
        session.execute = AsyncMock(return_value=result_mock)
        tx = MagicMock()
        tx.__aenter__ = AsyncMock(return_value=None)
        tx.__aexit__ = AsyncMock(return_value=False)
        session.begin = MagicMock(return_value=tx)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)
        factory = MagicMock(return_value=cm)

        service = ApiKeyService(factory)
        assert await service.verify_key("sc-test") is None

    @pytest.mark.asyncio
    async def test_verify_returns_none_for_unknown_key(self) -> None:
        from syndicateclaw.security.api_keys import ApiKeyService

        session = MagicMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result_mock)
        tx = MagicMock()
        tx.__aenter__ = AsyncMock(return_value=None)
        tx.__aexit__ = AsyncMock(return_value=False)
        session.begin = MagicMock(return_value=tx)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)
        factory = MagicMock(return_value=cm)

        service = ApiKeyService(factory)
        assert await service.verify_key("sc-nonexistent") is None


class TestApiKeyDbModel:
    """Verify the ApiKey DB model exists with correct fields."""

    def test_api_key_table_exists(self) -> None:
        from syndicateclaw.db.models import ApiKey

        assert ApiKey.__tablename__ == "api_keys"

    def test_api_key_has_lifecycle_fields(self) -> None:
        from syndicateclaw.db.models import ApiKey

        columns = {c.name for c in ApiKey.__table__.columns}
        assert "key_hash" in columns
        assert "key_prefix" in columns
        assert "actor" in columns
        assert "revoked" in columns
        assert "revoked_at" in columns
        assert "revoked_by" in columns
        assert "last_used_at" in columns
        assert "expires_at" in columns
        assert "created_at" in columns

    def test_dependency_wiring(self) -> None:
        import importlib
        import inspect
        import os

        os.environ.setdefault("SYNDICATECLAW_DATABASE_URL", "postgresql+asyncpg://syndicateclaw:syndicateclaw@postgres:5432/syndicateclaw_test")
        os.environ.setdefault("SYNDICATECLAW_SECRET_KEY", "test-key")
        import syndicateclaw.api.main as main_mod

        importlib.reload(main_mod)
        source = inspect.getsource(main_mod.lifespan)
        assert "ApiKeyService" in source
        assert "api_key_service" in source


# =====================================================================
# 4. Memory Write Guardrails
# =====================================================================


def _make_record(**kwargs) -> MemoryRecord:
    defaults = dict(
        namespace="ns",
        key="k1",
        value={"data": "test"},
        memory_type=MemoryType.STRUCTURED,
        source="test",
        actor="user:alice",
        confidence=1.0,
        access_policy="default",
        lineage=MemoryLineage(),
        deletion_status=MemoryDeletionStatus.ACTIVE,
        tags={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    defaults.update(kwargs)
    return MemoryRecord(**defaults)


class TestMemoryWriteGuardrails:
    """Verify size and structure constraints on memory writes."""

    def test_rejects_oversized_value(self) -> None:
        from syndicateclaw.memory.service import MemoryService

        service = MemoryService(MagicMock(), max_value_bytes=100)
        record = _make_record(value={"data": "x" * 200})
        with pytest.raises(ValueError, match="Value too large"):
            service._validate_write_guardrails(record)

    def test_accepts_small_value(self) -> None:
        from syndicateclaw.memory.service import MemoryService

        service = MemoryService(MagicMock(), max_value_bytes=10000)
        record = _make_record(value={"ok": True})
        service._validate_write_guardrails(record)

    def test_rejects_long_key(self) -> None:
        from syndicateclaw.memory.service import MemoryService

        service = MemoryService(MagicMock(), max_key_length=10)
        record = _make_record(key="a" * 50)
        with pytest.raises(ValueError, match="Key too long"):
            service._validate_write_guardrails(record)

    def test_rejects_long_namespace(self) -> None:
        from syndicateclaw.memory.service import MemoryService

        service = MemoryService(MagicMock(), max_namespace_length=10)
        record = _make_record(namespace="a" * 50)
        with pytest.raises(ValueError, match="Namespace too long"):
            service._validate_write_guardrails(record)

    def test_rejects_deeply_nested_value(self) -> None:
        from syndicateclaw.memory.service import MemoryService

        nested: dict[str, Any] = {"level": 0}
        current = nested
        for i in range(25):
            child: dict[str, Any] = {"level": i + 1}
            current["child"] = child
            current = child

        service = MemoryService(MagicMock(), max_nesting_depth=20)
        record = _make_record(value=nested)
        with pytest.raises(ValueError, match="nesting depth"):
            service._validate_write_guardrails(record)

    def test_accepts_moderately_nested_value(self) -> None:
        from syndicateclaw.memory.service import MemoryService

        nested: dict[str, Any] = {"a": {"b": {"c": {"d": "ok"}}}}
        service = MemoryService(MagicMock(), max_nesting_depth=20)
        record = _make_record(value=nested)
        service._validate_write_guardrails(record)

    def test_default_limits_are_reasonable(self) -> None:
        from syndicateclaw.memory.service import MemoryService

        service = MemoryService(MagicMock())
        assert service._max_value_bytes == 1_048_576
        assert service._max_key_length == 256
        assert service._max_namespace_length == 128
        assert service._max_nesting_depth == 20

    def test_config_has_memory_guardrail_fields(self) -> None:
        import os

        os.environ.setdefault("SYNDICATECLAW_DATABASE_URL", "postgresql+asyncpg://syndicateclaw:syndicateclaw@postgres:5432/syndicateclaw_test")
        os.environ.setdefault("SYNDICATECLAW_SECRET_KEY", "test-key")
        from syndicateclaw.config import Settings

        s = Settings()
        assert hasattr(s, "memory_max_value_bytes")
        assert hasattr(s, "memory_max_key_length")
        assert hasattr(s, "memory_max_namespace_length")
        assert s.memory_max_value_bytes == 1_048_576

    def test_write_calls_guardrails(self) -> None:
        """Verify that write() calls _validate_write_guardrails."""
        import inspect

        from syndicateclaw.memory.service import MemoryService

        source = inspect.getsource(MemoryService.write)
        assert "_validate_write_guardrails" in source

    def test_nesting_depth_check_handles_lists(self) -> None:
        from syndicateclaw.memory.service import _check_nesting_depth

        deep_list: list[Any] = [[[[[[[[[[[[[[[[[[[[[1]]]]]]]]]]]]]]]]]]]]]
        with pytest.raises(ValueError, match="nesting depth"):
            _check_nesting_depth(deep_list, max_depth=20, current=0)


# =====================================================================
# 5. Auth Dependency Wiring
# =====================================================================


class TestAuthDependencyWiring:
    """Verify auth dependency uses DB-backed API key service when available."""

    def test_dependency_checks_api_key_service(self) -> None:
        import inspect

        from syndicateclaw.api.dependencies import get_current_actor

        source = inspect.getsource(get_current_actor)
        assert "api_key_service" in source
        assert "verify_key" in source
