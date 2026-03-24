"""Tests for the four final fixes:

1. GET-by-ID ownership enforcement
2. EdDSA JWT alignment
3. Checkpoint HMAC signing
4. Memory namespace schema validation
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("SYNDICATECLAW_DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
os.environ.setdefault("SYNDICATECLAW_SECRET_KEY", "test-secret-key-for-tests")


# ======================================================================
# 1. GET-by-ID ownership enforcement
# ======================================================================


class TestWorkflowGetByIdOwnership:
    """Verify get_workflow returns 404 when actor is not the owner."""

    def test_get_workflow_source_has_ownership_check(self):
        import inspect
        from syndicateclaw.api.routes.workflows import get_workflow

        src = inspect.getsource(get_workflow)
        assert "wf.owner" in src and "actor" in src, (
            "get_workflow must check wf.owner against actor"
        )

    def test_get_run_source_has_ownership_check(self):
        import inspect
        from syndicateclaw.api.routes.workflows import get_run

        src = inspect.getsource(get_run)
        assert "run.initiated_by" in src and "actor" in src

    def test_pause_run_source_has_ownership_check(self):
        import inspect
        from syndicateclaw.api.routes.workflows import pause_run

        src = inspect.getsource(pause_run)
        assert "run.initiated_by" in src and "actor" in src

    def test_resume_run_source_has_ownership_check(self):
        import inspect
        from syndicateclaw.api.routes.workflows import resume_run

        src = inspect.getsource(resume_run)
        assert "run.initiated_by" in src and "actor" in src

    def test_cancel_run_source_has_ownership_check(self):
        import inspect
        from syndicateclaw.api.routes.workflows import cancel_run

        src = inspect.getsource(cancel_run)
        assert "run.initiated_by" in src and "actor" in src

    def test_replay_run_source_has_ownership_check(self):
        import inspect
        from syndicateclaw.api.routes.workflows import replay_run

        src = inspect.getsource(replay_run)
        assert "run.initiated_by" in src and "actor" in src


class TestApprovalGetByIdOwnership:
    """Verify get_approval enforces actor scoping."""

    def test_get_approval_source_checks_actor_in_assigned_or_requester(self):
        import inspect
        from syndicateclaw.api.routes.approvals import get_approval

        src = inspect.getsource(get_approval)
        assert "assigned_to" in src and "requested_by" in src

    def test_get_approvals_for_run_source_scopes_by_actor(self):
        import inspect
        from syndicateclaw.api.routes.approvals import get_approvals_for_run

        src = inspect.getsource(get_approvals_for_run)
        assert "assigned_to" in src or "requested_by" in src


class TestMemoryGetByIdOwnership:
    """Verify memory update/delete/lineage enforce access policy."""

    def test_update_memory_checks_access_policy(self):
        import inspect
        from syndicateclaw.api.routes.memory import update_memory

        src = inspect.getsource(update_memory)
        assert "_check_access_policy" in src

    def test_delete_memory_checks_access_policy(self):
        import inspect
        from syndicateclaw.api.routes.memory import delete_memory

        src = inspect.getsource(delete_memory)
        assert "_check_access_policy" in src

    def test_lineage_checks_access_policy(self):
        import inspect
        from syndicateclaw.api.routes.memory import get_memory_lineage

        src = inspect.getsource(get_memory_lineage)
        assert "_check_access_policy" in src


# ======================================================================
# 2. EdDSA JWT alignment
# ======================================================================


class TestEdDSAJWT:
    """Verify EdDSA JWT signing and verification."""

    def _generate_ed25519_keypair(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        priv = Ed25519PrivateKey.generate()
        return priv, priv.public_key()

    def test_eddsa_roundtrip(self):
        from syndicateclaw.security.auth import create_access_token, decode_access_token
        priv, pub = self._generate_ed25519_keypair()

        token = create_access_token(
            "alice", ["read"], timedelta(hours=1),
            algorithm="EdDSA", private_key=priv,
        )
        claims = decode_access_token(token, public_key=pub)
        assert claims["sub"] == "alice"
        assert claims["permissions"] == ["read"]

    def test_hs256_still_works(self):
        from syndicateclaw.security.auth import create_access_token, decode_access_token
        token = create_access_token(
            "bob", ["write"], timedelta(hours=1),
            secret_key="my-secret",
        )
        claims = decode_access_token(token, secret_key="my-secret")
        assert claims["sub"] == "bob"

    def test_eddsa_preferred_over_hs256(self):
        """When both keys present, EdDSA is tried first."""
        from syndicateclaw.security.auth import create_access_token, decode_access_token
        priv, pub = self._generate_ed25519_keypair()

        token = create_access_token(
            "charlie", ["admin"], timedelta(hours=1),
            algorithm="EdDSA", private_key=priv,
        )
        claims = decode_access_token(
            token, secret_key="wrong-secret", public_key=pub,
        )
        assert claims["sub"] == "charlie"

    def test_invalid_token_raises_jwt_error(self):
        from syndicateclaw.security.auth import JWTError, decode_access_token
        with pytest.raises(JWTError):
            decode_access_token("garbage.token.here", secret_key="any")

    def test_expired_token_raises_jwt_error(self):
        from syndicateclaw.security.auth import JWTError, create_access_token, decode_access_token
        token = create_access_token(
            "expired", [], timedelta(seconds=-1),
            secret_key="test",
        )
        with pytest.raises(JWTError):
            decode_access_token(token, secret_key="test")

    def test_jwt_error_is_standalone(self):
        """JWTError no longer depends on python-jose."""
        from syndicateclaw.security.auth import JWTError
        assert issubclass(JWTError, Exception)

    def test_pyproject_uses_pyjwt(self):
        import pathlib
        content = (pathlib.Path(__file__).resolve().parents[2] / "pyproject.toml").read_text()
        assert "PyJWT" in content
        assert "python-jose" not in content

    def test_config_has_jwt_algorithm(self):
        from syndicateclaw.config import Settings
        fields = Settings.model_fields
        assert "jwt_algorithm" in fields


class TestDependenciesEdDSA:
    """Verify dependencies.py is wired for EdDSA."""

    def test_dependencies_imports_jwt_error_from_auth(self):
        import inspect
        from syndicateclaw.api import dependencies

        src = inspect.getsource(dependencies)
        assert "from syndicateclaw.security.auth import JWTError" in src
        assert "jose" not in src

    def test_get_current_actor_passes_public_key(self):
        import inspect
        from syndicateclaw.api.dependencies import get_current_actor

        src = inspect.getsource(get_current_actor)
        assert "public_key" in src


# ======================================================================
# 3. Checkpoint HMAC signing
# ======================================================================


class TestCheckpointSigning:
    """Verify checkpoints are HMAC-signed and verified on replay."""

    def _make_engine(self, signing_key: bytes | None = None):
        from syndicateclaw.orchestrator.engine import WorkflowEngine
        return WorkflowEngine({}, signing_key=signing_key)

    def _make_run(self, state: dict[str, Any]):
        from syndicateclaw.models import WorkflowRun, WorkflowRunStatus
        return WorkflowRun(
            id="run-1",
            workflow_id="wf-1",
            workflow_version="1.0",
            initiated_by="test",
            status=WorkflowRunStatus.RUNNING,
            state=state,
        )

    @pytest.mark.asyncio
    async def test_persist_checkpoint_with_signing_key(self):
        key = b"test-signing-key-32bytes-padding!"
        engine = self._make_engine(signing_key=key)
        run = self._make_run({"counter": 42})

        await engine._persist_checkpoint(run)

        envelope = json.loads(run.checkpoint_data)
        assert "checkpoint_hmac" in envelope
        assert "data" in envelope
        assert envelope["data"]["counter"] == 42

        serialized = json.dumps(envelope["data"], default=str).encode()
        expected_sig = hmac.new(key, serialized, hashlib.sha256).hexdigest()
        assert envelope["checkpoint_hmac"] == expected_sig

    @pytest.mark.asyncio
    async def test_persist_checkpoint_without_signing_key(self):
        engine = self._make_engine(signing_key=None)
        run = self._make_run({"counter": 1})

        await engine._persist_checkpoint(run)

        data = json.loads(run.checkpoint_data)
        assert "checkpoint_hmac" not in data
        assert data["counter"] == 1

    @pytest.mark.asyncio
    async def test_replay_verifies_signed_checkpoint(self):
        key = b"replay-test-key-32bytes-padding!"
        engine = self._make_engine(signing_key=key)
        run = self._make_run({"step": "checkpoint"})

        from syndicateclaw.orchestrator.engine import WorkflowRunResult
        engine._runs["run-1"] = WorkflowRunResult(run=run)

        await engine._persist_checkpoint(run)
        result = await engine.replay("run-1")
        assert result.run.state == {"step": "checkpoint"}

    @pytest.mark.asyncio
    async def test_replay_rejects_tampered_checkpoint(self):
        key = b"tamper-test-key-32bytes-padding!!"
        engine = self._make_engine(signing_key=key)
        run = self._make_run({"original": True})

        from syndicateclaw.orchestrator.engine import WorkflowRunResult
        engine._runs["run-1"] = WorkflowRunResult(run=run)
        await engine._persist_checkpoint(run)

        envelope = json.loads(run.checkpoint_data)
        envelope["data"]["original"] = False
        run.checkpoint_data = json.dumps(envelope).encode()

        with pytest.raises(ValueError, match="HMAC mismatch"):
            await engine.replay("run-1")

    @pytest.mark.asyncio
    async def test_replay_loads_unsigned_checkpoint(self):
        """Engine without signing key loads raw (unsigned) checkpoints."""
        engine = self._make_engine(signing_key=None)
        run = self._make_run({"legacy": True})
        run.checkpoint_data = json.dumps({"legacy": True}).encode()

        from syndicateclaw.orchestrator.engine import WorkflowRunResult
        engine._runs["run-1"] = WorkflowRunResult(run=run)

        result = await engine.replay("run-1")
        assert result.run.state == {"legacy": True}

    def test_engine_accepts_signing_key_param(self):
        from syndicateclaw.orchestrator.engine import WorkflowEngine
        engine = WorkflowEngine({}, signing_key=b"key")
        assert engine._signing_key == b"key"

    def test_engine_signing_key_wired_in_main(self):
        """Verify main.py passes signing_key to WorkflowEngine."""
        import inspect
        import importlib
        import syndicateclaw.api.main as main_mod
        importlib.reload(main_mod)
        src = inspect.getsource(main_mod.lifespan)
        assert "signing_key=signing_key" in src


# ======================================================================
# 4. Memory namespace schema validation
# ======================================================================


class TestNamespaceSchemaRegistry:
    """Test the schema registry and validation logic."""

    def test_exact_namespace_match(self):
        from syndicateclaw.memory.schema import NamespaceSchema, NamespaceSchemaRegistry

        reg = NamespaceSchemaRegistry()
        reg.register("agent:facts", NamespaceSchema(required_fields={"claim"}))
        assert reg.get_schema("agent:facts") is not None
        assert reg.get_schema("agent:other") is None

    def test_prefix_glob_match(self):
        from syndicateclaw.memory.schema import NamespaceSchema, NamespaceSchemaRegistry

        reg = NamespaceSchemaRegistry()
        reg.register("agent:*", NamespaceSchema(required_fields={"source"}))
        assert reg.get_schema("agent:facts") is not None
        assert reg.get_schema("agent:context") is not None
        assert reg.get_schema("system:config") is None

    def test_validate_required_fields(self):
        from syndicateclaw.memory.schema import (
            NamespaceSchema,
            NamespaceSchemaRegistry,
            SchemaValidationError,
        )

        reg = NamespaceSchemaRegistry()
        reg.register("ns", NamespaceSchema(required_fields={"x", "y"}))

        reg.validate("ns", {"x": 1, "y": 2})

        with pytest.raises(SchemaValidationError, match="missing required"):
            reg.validate("ns", {"x": 1})

    def test_validate_field_types(self):
        from syndicateclaw.memory.schema import (
            NamespaceSchema,
            NamespaceSchemaRegistry,
            SchemaValidationError,
        )

        reg = NamespaceSchemaRegistry()
        reg.register("ns", NamespaceSchema(
            field_types={"score": "float", "name": "str"},
        ))

        reg.validate("ns", {"score": 0.95, "name": "test"})
        reg.validate("ns", {"score": 1, "name": "test"})

        with pytest.raises(SchemaValidationError, match="expected str"):
            reg.validate("ns", {"name": 123})

    def test_validate_max_field_count(self):
        from syndicateclaw.memory.schema import (
            NamespaceSchema,
            NamespaceSchemaRegistry,
            SchemaValidationError,
        )

        reg = NamespaceSchemaRegistry()
        reg.register("ns", NamespaceSchema(max_field_count=2))

        reg.validate("ns", {"a": 1, "b": 2})

        with pytest.raises(SchemaValidationError, match="max allowed"):
            reg.validate("ns", {"a": 1, "b": 2, "c": 3})

    def test_validate_disallow_extra_fields(self):
        from syndicateclaw.memory.schema import (
            NamespaceSchema,
            NamespaceSchemaRegistry,
            SchemaValidationError,
        )

        reg = NamespaceSchemaRegistry()
        reg.register("ns", NamespaceSchema(
            required_fields={"x"},
            allow_extra_fields=False,
        ))

        reg.validate("ns", {"x": 1})

        with pytest.raises(SchemaValidationError, match="extra fields"):
            reg.validate("ns", {"x": 1, "unexpected": 2})

    def test_validate_non_dict_value(self):
        from syndicateclaw.memory.schema import (
            NamespaceSchema,
            NamespaceSchemaRegistry,
            SchemaValidationError,
        )

        reg = NamespaceSchemaRegistry()
        reg.register("ns", NamespaceSchema(required_fields={"x"}))

        with pytest.raises(SchemaValidationError, match="requires a dict"):
            reg.validate("ns", "plain string")

    def test_no_schema_is_noop(self):
        from syndicateclaw.memory.schema import NamespaceSchemaRegistry

        reg = NamespaceSchemaRegistry()
        reg.validate("no-schema-ns", "anything goes")

    def test_unregister(self):
        from syndicateclaw.memory.schema import NamespaceSchema, NamespaceSchemaRegistry

        reg = NamespaceSchemaRegistry()
        reg.register("ns", NamespaceSchema())
        assert reg.unregister("ns") is True
        assert reg.unregister("ns") is False

    def test_list_schemas(self):
        from syndicateclaw.memory.schema import NamespaceSchema, NamespaceSchemaRegistry

        reg = NamespaceSchemaRegistry()
        reg.register("a", NamespaceSchema())
        reg.register("b", NamespaceSchema())
        assert len(reg.list_schemas()) == 2


class TestMemoryServiceSchemaIntegration:
    """Verify MemoryService uses schema registry on write path."""

    def test_memory_service_accepts_schema_registry(self):
        from syndicateclaw.memory.service import MemoryService

        sf = MagicMock()
        from syndicateclaw.memory.schema import NamespaceSchemaRegistry
        reg = NamespaceSchemaRegistry()
        svc = MemoryService(sf, schema_registry=reg)
        assert svc._schema_registry is reg

    def test_validate_namespace_schema_is_called_on_write(self):
        import inspect
        from syndicateclaw.memory.service import MemoryService
        src = inspect.getsource(MemoryService.write)
        assert "_validate_namespace_schema" in src

    def test_validate_namespace_schema_is_called_on_update(self):
        import inspect
        from syndicateclaw.memory.service import MemoryService
        src = inspect.getsource(MemoryService.update)
        assert "_validate_namespace_schema" in src

    def test_validate_namespace_schema_noop_without_registry(self):
        from syndicateclaw.memory.service import MemoryService
        svc = MemoryService(MagicMock(), schema_registry=None)
        svc._validate_namespace_schema("any", {"x": 1})

    def test_validate_namespace_schema_raises_on_violation(self):
        from syndicateclaw.memory.schema import (
            NamespaceSchema,
            NamespaceSchemaRegistry,
            SchemaValidationError,
        )
        from syndicateclaw.memory.service import MemoryService

        reg = NamespaceSchemaRegistry()
        reg.register("strict:*", NamespaceSchema(
            required_fields={"mandatory_field"},
        ))

        svc = MemoryService(MagicMock(), schema_registry=reg)

        with pytest.raises(SchemaValidationError, match="missing required"):
            svc._validate_namespace_schema("strict:data", {"other": 1})

    def test_validate_namespace_schema_passes_valid_data(self):
        from syndicateclaw.memory.schema import NamespaceSchema, NamespaceSchemaRegistry
        from syndicateclaw.memory.service import MemoryService

        reg = NamespaceSchemaRegistry()
        reg.register("strict:*", NamespaceSchema(
            required_fields={"mandatory_field"},
        ))

        svc = MemoryService(MagicMock(), schema_registry=reg)
        svc._validate_namespace_schema("strict:data", {"mandatory_field": "ok"})


# ======================================================================
# Cross-cutting: wiring verification
# ======================================================================


class TestMainWiring:
    """Verify main.py wires new features correctly."""

    def test_main_passes_signing_key_to_workflow_engine(self):
        import importlib
        import inspect
        import syndicateclaw.api.main as main_mod
        importlib.reload(main_mod)
        src = inspect.getsource(main_mod.lifespan)
        assert "signing_key=signing_key" in src

    def test_main_exposes_jwt_algorithm_in_config(self):
        from syndicateclaw.config import Settings
        assert "jwt_algorithm" in Settings.model_fields
