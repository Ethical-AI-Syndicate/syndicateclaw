"""Tests for boundary controls: rate limiting, approval authority, Ed25519 signing, state redaction.

These tests verify the four final controls before release readiness:
1. Per-actor rate limiting
2. Approval authority separation
3. Asymmetric signing (Ed25519)
4. Workflow state redaction
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syndicateclaw.models import (
    ApprovalRequest,
    ApprovalStatus,
    ToolRiskLevel,
)


# =====================================================================
# 1. Rate Limiting
# =====================================================================


class TestRateLimitMiddleware:
    """Verify rate limit middleware enforces per-actor limits."""

    def test_skip_paths_are_defined(self):
        from syndicateclaw.api.rate_limit import _RATE_LIMIT_SKIP_PATHS

        assert "/healthz" in _RATE_LIMIT_SKIP_PATHS
        assert "/readyz" in _RATE_LIMIT_SKIP_PATHS
        assert "/docs" in _RATE_LIMIT_SKIP_PATHS

    def test_rate_limit_response_format(self):
        from syndicateclaw.api.rate_limit import _rate_limit_response

        resp = _rate_limit_response("user:alice", 101, 100, 30, "sustained")
        assert resp.status_code == 429
        assert resp.headers.get("Retry-After") == "30"
        assert resp.headers.get("X-RateLimit-Remaining") == "0"
        body = json.loads(resp.body)
        assert "sustained" in body["detail"]
        assert body["retry_after"] == 30

    def test_burst_rate_limit_response(self):
        from syndicateclaw.api.rate_limit import _rate_limit_response

        resp = _rate_limit_response("user:bob", 25, 20, 1, "burst")
        assert resp.status_code == 429
        body = json.loads(resp.body)
        assert "burst" in body["detail"]

    def test_extract_actor_hint_from_api_key(self):
        from syndicateclaw.api.rate_limit import _extract_actor_hint

        request = MagicMock()
        request.headers = {"x-api-key": "abcdefgh12345678"}
        result = _extract_actor_hint(request)
        assert result == "apikey:abcdefgh"

    def test_extract_actor_hint_from_bearer(self):
        from syndicateclaw.api.rate_limit import _extract_actor_hint

        request = MagicMock()
        request.headers = {"authorization": "Bearer eyJhbGciOi"}
        result = _extract_actor_hint(request)
        assert result == "bearer:eyJhbGci"

    def test_extract_actor_hint_returns_none_without_auth(self):
        from syndicateclaw.api.rate_limit import _extract_actor_hint

        request = MagicMock()
        request.headers = {}
        result = _extract_actor_hint(request)
        assert result is None

    def test_config_has_rate_limit_fields(self):
        import os
        os.environ.setdefault("SYNDICATECLAW_DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
        os.environ.setdefault("SYNDICATECLAW_SECRET_KEY", "test-key")
        from syndicateclaw.config import Settings
        s = Settings()
        assert hasattr(s, "rate_limit_requests")
        assert hasattr(s, "rate_limit_window_seconds")
        assert hasattr(s, "rate_limit_burst")
        assert s.rate_limit_requests > 0
        assert s.rate_limit_window_seconds > 0
        assert s.rate_limit_burst > 0

    def test_middleware_is_wired_in_app(self):
        import inspect
        import os
        os.environ.setdefault("SYNDICATECLAW_DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
        os.environ.setdefault("SYNDICATECLAW_SECRET_KEY", "test-key")
        from syndicateclaw.api.main import create_app
        source = inspect.getsource(create_app)
        assert "RateLimitMiddleware" in source


# =====================================================================
# 2. Approval Authority Separation
# =====================================================================


class TestApprovalAuthorityResolver:
    """Verify approver resolution prevents requester self-selection."""

    @pytest.mark.asyncio
    async def test_resolve_by_risk_level(self):
        from syndicateclaw.approval.authority import ApprovalAuthorityResolver

        resolver = ApprovalAuthorityResolver()
        approvers = await resolver.resolve(
            tool_name="http_request",
            risk_level=ToolRiskLevel.HIGH,
            requester="user:alice",
        )
        assert len(approvers) > 0
        assert "user:alice" not in approvers

    @pytest.mark.asyncio
    async def test_requester_excluded_from_approvers(self):
        from syndicateclaw.approval.authority import (
            ApprovalAuthorityResolver,
            DEFAULT_APPROVAL_AUTHORITIES,
        )

        overrides = {ToolRiskLevel.LOW: ["admin:ops", "user:alice"]}
        resolver = ApprovalAuthorityResolver(authority_overrides=overrides)
        approvers = await resolver.resolve(
            tool_name="memory_write",
            risk_level=ToolRiskLevel.LOW,
            requester="user:alice",
        )
        assert "user:alice" not in approvers
        assert "admin:ops" in approvers

    @pytest.mark.asyncio
    async def test_fallback_when_all_resolved_match_requester(self):
        from syndicateclaw.approval.authority import ApprovalAuthorityResolver

        overrides = {ToolRiskLevel.LOW: ["admin:ops"]}
        resolver = ApprovalAuthorityResolver(authority_overrides=overrides)
        approvers = await resolver.resolve(
            tool_name="test_tool",
            risk_level=ToolRiskLevel.LOW,
            requester="admin:ops",
        )
        assert len(approvers) > 0
        assert "admin:ops" not in approvers

    @pytest.mark.asyncio
    async def test_custom_overrides(self):
        from syndicateclaw.approval.authority import ApprovalAuthorityResolver

        overrides = {ToolRiskLevel.CRITICAL: ["admin:ciso", "admin:board"]}
        resolver = ApprovalAuthorityResolver(authority_overrides=overrides)
        approvers = await resolver.resolve(
            tool_name="deploy",
            risk_level=ToolRiskLevel.CRITICAL,
            requester="user:dev",
        )
        assert "admin:ciso" in approvers
        assert "admin:board" in approvers

    @pytest.mark.asyncio
    async def test_default_authorities_cover_all_risk_levels(self):
        from syndicateclaw.approval.authority import DEFAULT_APPROVAL_AUTHORITIES

        for level in ToolRiskLevel:
            assert level in DEFAULT_APPROVAL_AUTHORITIES
            assert len(DEFAULT_APPROVAL_AUTHORITIES[level]) > 0


class TestApprovalServiceAuthority:
    """Verify ApprovalService uses authority resolver."""

    @pytest.mark.asyncio
    async def test_authority_overrides_assigned_to(self):
        from syndicateclaw.approval.authority import ApprovalAuthorityResolver
        from syndicateclaw.approval.service import ApprovalService

        resolver = ApprovalAuthorityResolver(
            authority_overrides={ToolRiskLevel.MEDIUM: ["admin:security"]}
        )

        session = MagicMock()
        session.execute = AsyncMock()
        session.flush = AsyncMock()
        tx_cm = MagicMock()
        tx_cm.__aenter__ = AsyncMock(return_value=None)
        tx_cm.__aexit__ = AsyncMock(return_value=False)
        session.begin = MagicMock(return_value=tx_cm)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)
        factory = MagicMock(return_value=cm)

        service = ApprovalService(factory, authority_resolver=resolver)

        request = ApprovalRequest.new(
            run_id="run-1",
            node_execution_id="node-1",
            action_description="test action",
            risk_level=ToolRiskLevel.MEDIUM,
            requested_by="user:alice",
            assigned_to=["user:colluder"],
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            context={"test": True},
        )

        with patch("syndicateclaw.approval.service.ApprovalRequestRepository") as mock_repo_cls, \
             patch.object(service, "_emit_audit", new_callable=AsyncMock):
            mock_repo = AsyncMock()
            mock_repo_cls.return_value = mock_repo

            result = await service.request_approval(request, "user:alice")

        assert result.assigned_to == ["admin:security"]
        assert "user:colluder" not in result.assigned_to

    @pytest.mark.asyncio
    async def test_no_resolver_requires_assigned_to(self):
        from syndicateclaw.approval.service import ApprovalService

        factory = MagicMock()
        service = ApprovalService(factory)

        request = ApprovalRequest.new(
            run_id="run-1",
            node_execution_id="node-1",
            action_description="test action",
            risk_level=ToolRiskLevel.MEDIUM,
            requested_by="user:alice",
            assigned_to=[],
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            context={},
        )

        with pytest.raises(ValueError, match="assigned_to"):
            await service.request_approval(request, "user:alice")


# =====================================================================
# 3. Ed25519 Asymmetric Signing
# =====================================================================


class TestEd25519Signing:
    """Verify asymmetric key generation, signing, and verification."""

    def test_key_pair_generation(self):
        from syndicateclaw.security.signing import SigningKeyPair

        kp = SigningKeyPair()
        assert kp.public_key_pem.startswith(b"-----BEGIN PUBLIC KEY-----")
        assert kp.private_key_pem.startswith(b"-----BEGIN PRIVATE KEY-----")

    def test_sign_and_verify_roundtrip(self):
        from syndicateclaw.security.signing import SigningKeyPair

        kp = SigningKeyPair()
        payload = {"action": "deploy", "env": "prod", "version": "1.2.3"}
        sig = kp.sign(payload)
        assert isinstance(sig, str)
        assert kp.verify(payload, sig)

    def test_tampered_payload_rejected(self):
        from syndicateclaw.security.signing import SigningKeyPair

        kp = SigningKeyPair()
        payload = {"action": "deploy"}
        sig = kp.sign(payload)
        tampered = {"action": "delete"}
        assert not kp.verify(tampered, sig)

    def test_wrong_key_rejected(self):
        from syndicateclaw.security.signing import SigningKeyPair

        kp1 = SigningKeyPair()
        kp2 = SigningKeyPair()
        payload = {"data": "sensitive"}
        sig = kp1.sign(payload)
        assert not kp2.verify(payload, sig)

    def test_verifier_from_public_key(self):
        from syndicateclaw.security.signing import Ed25519Verifier, SigningKeyPair

        kp = SigningKeyPair()
        payload = {"event": "audit", "id": "123"}
        sig = kp.sign(payload)

        verifier = Ed25519Verifier(kp.public_key_pem)
        assert verifier.verify(payload, sig)
        assert not verifier.verify({"event": "forged"}, sig)

    def test_key_persistence_roundtrip(self):
        from syndicateclaw.security.signing import SigningKeyPair

        kp1 = SigningKeyPair()
        private_pem = kp1.private_key_pem

        kp2 = SigningKeyPair(private_key_bytes=private_pem)
        payload = {"test": "roundtrip"}
        sig = kp1.sign(payload)
        assert kp2.verify(payload, sig)

    def test_from_public_key_pem_classmethod(self):
        from syndicateclaw.security.signing import SigningKeyPair

        kp = SigningKeyPair()
        verifier = SigningKeyPair.from_public_key_pem(kp.public_key_pem)
        payload = {"check": True}
        sig = kp.sign(payload)
        assert verifier.verify(payload, sig)

    def test_canonical_json_order_invariant(self):
        from syndicateclaw.security.signing import SigningKeyPair

        kp = SigningKeyPair()
        sig = kp.sign({"b": 2, "a": 1})
        assert kp.verify({"a": 1, "b": 2}, sig)


# =====================================================================
# 4. State Redaction
# =====================================================================


class TestStateRedaction:
    """Verify sensitive fields are stripped from workflow state."""

    def test_redacts_password_fields(self):
        from syndicateclaw.security.redaction import redact_state

        state = {"db_password": "hunter2", "name": "test"}
        result = redact_state(state)
        assert result["db_password"] == "[REDACTED]"
        assert result["name"] == "test"

    def test_redacts_nested_secrets(self):
        from syndicateclaw.security.redaction import redact_state

        state = {
            "config": {
                "api_key": "sk-12345",
                "endpoint": "https://api.example.com",
            }
        }
        result = redact_state(state)
        assert result["config"]["api_key"] == "[REDACTED]"
        assert result["config"]["endpoint"] == "https://api.example.com"

    def test_redacts_token_fields(self):
        from syndicateclaw.security.redaction import redact_state

        state = {"access_token": "abc", "refresh_token": "xyz", "user": "alice"}
        result = redact_state(state)
        assert result["access_token"] == "[REDACTED]"
        assert result["refresh_token"] == "[REDACTED]"
        assert result["user"] == "alice"

    def test_redacts_credential_fields(self):
        from syndicateclaw.security.redaction import redact_state

        state = {"aws_credentials": {"key": "AKIA..."}, "region": "us-east-1"}
        result = redact_state(state)
        assert result["aws_credentials"] == "[REDACTED]"
        assert result["region"] == "us-east-1"

    def test_preserves_allowlisted_fields(self):
        from syndicateclaw.security.redaction import redact_state

        state = {"_run_id": "run-123", "auth_token": "secret"}
        result = redact_state(state, allowlist={"_run_id"})
        assert result["_run_id"] == "run-123"
        assert result["auth_token"] == "[REDACTED]"

    def test_extra_patterns(self):
        from syndicateclaw.security.redaction import redact_state

        state = {"custom_field": "sensitive", "normal": "ok"}
        result = redact_state(state, extra_patterns=[r"custom_field"])
        assert result["custom_field"] == "[REDACTED]"
        assert result["normal"] == "ok"

    def test_does_not_mutate_original(self):
        from syndicateclaw.security.redaction import redact_state

        state = {"password": "hunter2", "name": "test"}
        result = redact_state(state)
        assert state["password"] == "hunter2"
        assert result["password"] == "[REDACTED]"

    def test_handles_lists_in_state(self):
        from syndicateclaw.security.redaction import redact_state

        state = {
            "items": [
                {"name": "a", "secret_key": "key1"},
                {"name": "b", "secret_key": "key2"},
            ]
        }
        result = redact_state(state)
        assert result["items"][0]["name"] == "a"
        assert result["items"][0]["secret_key"] == "[REDACTED]"
        assert result["items"][1]["secret_key"] == "[REDACTED]"

    def test_case_insensitive_matching(self):
        from syndicateclaw.security.redaction import redact_state

        state = {"PASSWORD": "x", "Api_Key": "y", "TOKEN": "z"}
        result = redact_state(state)
        assert result["PASSWORD"] == "[REDACTED]"
        assert result["Api_Key"] == "[REDACTED]"
        assert result["TOKEN"] == "[REDACTED]"

    def test_empty_state_unchanged(self):
        from syndicateclaw.security.redaction import redact_state

        assert redact_state({}) == {}

    def test_unknown_policy_fail_closed_for_unknown_patterns(self):
        """Non-sensitive fields should NOT be redacted."""
        from syndicateclaw.security.redaction import redact_state

        state = {"workflow_name": "test", "step_count": 5, "description": "a workflow"}
        result = redact_state(state)
        assert result == state


class TestWorkflowRunResponseRedaction:
    """Verify WorkflowRunResponse.from_orm_redacted applies redaction."""

    def test_from_orm_redacted_strips_secrets(self):
        from syndicateclaw.api.routes.workflows import WorkflowRunResponse

        obj = MagicMock()
        obj.id = "run-1"
        obj.workflow_id = "wf-1"
        obj.workflow_version = "1.0"
        obj.status = "RUNNING"
        obj.state = {"api_key": "sk-secret", "_run_id": "run-1", "data": "ok"}
        obj.parent_run_id = None
        obj.initiated_by = "user:alice"
        obj.started_at = datetime.now(UTC)
        obj.completed_at = None
        obj.error = None
        obj.tags = {}
        obj.created_at = datetime.now(UTC)
        obj.updated_at = datetime.now(UTC)

        result = WorkflowRunResponse.from_orm_redacted(obj)
        assert result.state["api_key"] == "[REDACTED]"
        assert result.state["_run_id"] == "run-1"
        assert result.state["data"] == "ok"

    def test_from_orm_redacted_preserves_internal_fields(self):
        from syndicateclaw.api.routes.workflows import WorkflowRunResponse

        obj = MagicMock()
        obj.id = "run-2"
        obj.workflow_id = "wf-2"
        obj.workflow_version = "2.0"
        obj.status = "COMPLETED"
        obj.state = {
            "_started_at": "2024-01-01T00:00:00",
            "_completed_at": "2024-01-01T01:00:00",
            "_decision": {"condition": "x > 1", "result": True},
            "password": "secret123",
        }
        obj.parent_run_id = None
        obj.initiated_by = "user:bob"
        obj.started_at = datetime.now(UTC)
        obj.completed_at = datetime.now(UTC)
        obj.error = None
        obj.tags = {}
        obj.created_at = datetime.now(UTC)
        obj.updated_at = datetime.now(UTC)

        result = WorkflowRunResponse.from_orm_redacted(obj)
        assert result.state["_started_at"] == "2024-01-01T00:00:00"
        assert result.state["_completed_at"] == "2024-01-01T01:00:00"
        assert result.state["_decision"]["result"] is True
        assert result.state["password"] == "[REDACTED]"


# =====================================================================
# 5. Wiring Verification
# =====================================================================


class TestAppWiring:
    """Verify all four controls are wired into the app lifecycle."""

    @pytest.fixture(autouse=True)
    def _env(self, monkeypatch):
        monkeypatch.setenv("SYNDICATECLAW_DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
        monkeypatch.setenv("SYNDICATECLAW_SECRET_KEY", "test-key")

    def test_lifespan_creates_authority_resolver(self):
        import importlib
        import inspect
        import syndicateclaw.api.main as main_mod
        importlib.reload(main_mod)
        source = inspect.getsource(main_mod.lifespan)
        assert "ApprovalAuthorityResolver" in source
        assert "authority_resolver" in source

    def test_create_app_has_rate_limit_middleware(self):
        import importlib
        import inspect
        import syndicateclaw.api.main as main_mod
        importlib.reload(main_mod)
        source = inspect.getsource(main_mod.create_app)
        assert "RateLimitMiddleware" in source
