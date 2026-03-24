"""ProviderService — sole inference execution path; adapters are protocol-only."""

from __future__ import annotations

import os
import time
from collections.abc import AsyncIterator
from typing import Any

import structlog
from ulid import ULID

from syndicateclaw.audit.service import AuditService
from syndicateclaw.inference.adapters.factory import adapter_for
from syndicateclaw.inference.catalog import ModelCatalog
from syndicateclaw.inference.config_loader import ProviderConfigLoader
from syndicateclaw.inference.errors import InferenceError, InferenceExecutionError
from syndicateclaw.inference.execution_binding import ExecutionBinding, provider_from_binding
from syndicateclaw.inference.metrics import record_inference_outcome
from syndicateclaw.inference.policy_gates import BoundedPolicyCache
from syndicateclaw.inference.policy_port import PolicyEngineRoutingPort
from syndicateclaw.inference.registry import ProviderRegistry
from syndicateclaw.inference.router import InferenceRouter
from syndicateclaw.inference.types import (
    ChatInferenceRequest,
    ChatInferenceResponse,
    EmbeddingInferenceRequest,
    EmbeddingInferenceResponse,
    ErrorCategory,
)
from syndicateclaw.models import AuditEvent, AuditEventType
from syndicateclaw.policy.engine import PolicyEngine

logger = structlog.get_logger(__name__)


def _resolve_auth(cfg: Any) -> tuple[str | None, str | None]:
    """Resolve API key material once per request (env-backed)."""
    if not cfg.auth or not cfg.auth.env_var:
        return None, None
    v = os.environ.get(cfg.auth.env_var)
    return v, None


class ProviderService:
    """Inference pipeline: capture ExecutionBinding once; no mid-attempt loader refresh."""

    def __init__(
        self,
        *,
        loader: ProviderConfigLoader,
        catalog: ModelCatalog,
        registry: ProviderRegistry,
        policy_engine: PolicyEngine,
        audit_service: AuditService,
    ) -> None:
        self._loader = loader
        self._catalog = catalog
        self._registry = registry
        self._policy_engine = policy_engine
        self._audit = audit_service
        self._policy_cache = BoundedPolicyCache(ttl_seconds=60.0, max_entries=256)

    async def infer_chat(self, req: ChatInferenceRequest) -> ChatInferenceResponse:
        """Buffered chat completion (tools and API non-streaming)."""
        binding = ExecutionBinding.capture(self._loader, self._catalog)
        inference_id = str(ULID())
        req = req.model_copy(update={"trace_id": req.trace_id or inference_id})

        router = InferenceRouter(binding.system_config.routing)
        policy_port = PolicyEngineRoutingPort(self._policy_engine)

        await self._emit_audit(
            AuditEventType.INFERENCE_STARTED,
            actor=req.actor,
            resource_id=inference_id,
            action="chat",
            trace_id=req.trace_id,
            details={
                "inference_id": inference_id,
                "system_config_version": binding.system_config_version,
                "catalog_snapshot_version": binding.catalog_snapshot_version,
                "request_hash": "pending",
            },
        )

        t_pipeline = time.monotonic()
        deadline = t_pipeline + binding.system_config.routing.max_total_latency_ms / 1000.0

        try:
            decision = await router.route(
                req,
                system=binding.system_config,
                registry=self._registry,
                catalog=self._catalog,
                policy=policy_port,
                policy_cache=self._policy_cache,
            )
        except Exception as exc:
            await self._emit_audit(
                AuditEventType.INFERENCE_FAILED,
                actor=req.actor,
                resource_id=inference_id,
                action="chat",
                trace_id=req.trace_id,
                details={
                    "inference_id": inference_id,
                    "phase": "route",
                    "error": str(exc),
                    "system_config_version": binding.system_config_version,
                    "catalog_snapshot_version": binding.catalog_snapshot_version,
                },
            )
            record_inference_outcome("chat", "route_failed")
            raise

        chain = [(decision.selected_provider_id, decision.selected_model_id)] + list(
            decision.fallback_chain,
        )

        auth_cache: dict[str, tuple[str | None, str | None]] = {}
        last_err: Exception | None = None

        for attempt_idx, (pid, mid) in enumerate(chain):
            if time.monotonic() > deadline:
                await self._emit_audit(
                    AuditEventType.INFERENCE_FAILED,
                    actor=req.actor,
                    resource_id=inference_id,
                    action="chat",
                    trace_id=req.trace_id,
                    details={
                        "inference_id": inference_id,
                        "phase": "deadline",
                        "attempt": attempt_idx,
                        "system_config_version": binding.system_config_version,
                    },
                )
                record_inference_outcome("chat", "timeout")
                raise InferenceExecutionError(
                    "global_latency_cap_exceeded",
                    category=ErrorCategory.TIMEOUT,
                    retryable=False,
                )

            prov = provider_from_binding(binding, pid)
            if prov is None or not prov.enabled or self._registry.is_runtime_disabled(pid):
                continue

            entry = self._catalog.get(pid, mid)
            if entry is None:
                continue

            req_attempt = req.model_copy(update={"provider_id": pid, "model_id": mid})

            if pid not in auth_cache:
                auth_cache[pid] = _resolve_auth(prov)
            api_key, bearer = auth_cache[pid]

            adapter = adapter_for(prov.adapter_protocol)
            try:
                raw = await adapter.infer_chat(
                    prov,
                    req_attempt,
                    api_key=api_key,
                    bearer_token=bearer,
                )
            except InferenceError as ie:
                last_err = ie
                if "http_404" in str(ie).lower() or "404" in str(ie):
                    continue
                if ie.category == ErrorCategory.VALIDATION:
                    await self._emit_audit(
                        AuditEventType.INFERENCE_FAILED,
                        actor=req.actor,
                        resource_id=inference_id,
                        action="chat",
                        trace_id=req.trace_id,
                        details={
                            "inference_id": inference_id,
                            "phase": "adapter",
                            "provider_id": pid,
                            "model_id": mid,
                            "error": str(ie),
                            "system_config_version": binding.system_config_version,
                        },
                    )
                    record_inference_outcome("chat", "validation_failed")
                    raise
                continue
            except Exception as exc:
                last_err = exc
                continue

            resolved_alias = raw.model_id if raw.model_id != mid else None
            out = raw.model_copy(
                update={
                    "inference_id": inference_id,
                    "provider_id": pid,
                    "model_id": raw.model_id,
                    "routing_decision_id": decision.id,
                    "latency_ms": raw.latency_ms + (time.monotonic() - t_pipeline) * 1000.0,
                },
            )
            _ = resolved_alias
            await self._emit_audit(
                AuditEventType.INFERENCE_COMPLETED,
                actor=req.actor,
                resource_id=inference_id,
                action="chat",
                trace_id=req.trace_id,
                details={
                    "inference_id": inference_id,
                    "provider_id": pid,
                    "model_id": out.model_id,
                    "routing_decision_id": decision.id,
                    "system_config_version": binding.system_config_version,
                    "catalog_snapshot_version": binding.catalog_snapshot_version,
                    "resolved_model_alias": resolved_alias,
                    "fallback_position": attempt_idx,
                },
            )
            record_inference_outcome("chat", "success")
            return out

        await self._emit_audit(
            AuditEventType.INFERENCE_FAILED,
            actor=req.actor,
            resource_id=inference_id,
            action="chat",
            trace_id=req.trace_id,
            details={
                "inference_id": inference_id,
                "phase": "exhausted",
                "last_error": str(last_err) if last_err else "",
                "system_config_version": binding.system_config_version,
            },
        )
        record_inference_outcome("chat", "exhausted")
        raise InferenceExecutionError(
            "all_candidates_failed",
            category=ErrorCategory.PROVIDER,
            retryable=False,
        )

    async def infer_embedding(self, req: EmbeddingInferenceRequest) -> EmbeddingInferenceResponse:
        """Buffered embedding inference."""
        binding = ExecutionBinding.capture(self._loader, self._catalog)
        inference_id = str(ULID())
        req = req.model_copy(update={"trace_id": req.trace_id or inference_id})

        router = InferenceRouter(binding.system_config.routing)
        policy_port = PolicyEngineRoutingPort(self._policy_engine)

        await self._emit_audit(
            AuditEventType.INFERENCE_STARTED,
            actor=req.actor,
            resource_id=inference_id,
            action="embedding",
            trace_id=req.trace_id,
            details={
                "inference_id": inference_id,
                "system_config_version": binding.system_config_version,
                "catalog_snapshot_version": binding.catalog_snapshot_version,
            },
        )

        t0 = time.monotonic()
        deadline = t0 + binding.system_config.routing.max_total_latency_ms / 1000.0

        try:
            decision = await router.route(
                req,
                system=binding.system_config,
                registry=self._registry,
                catalog=self._catalog,
                policy=policy_port,
                policy_cache=self._policy_cache,
            )
        except Exception as exc:
            await self._emit_audit(
                AuditEventType.INFERENCE_FAILED,
                actor=req.actor,
                resource_id=inference_id,
                action="embedding",
                trace_id=req.trace_id,
                details={
                    "inference_id": inference_id,
                    "phase": "route",
                    "error": str(exc),
                },
            )
            record_inference_outcome("embedding", "route_failed")
            raise

        chain = [(decision.selected_provider_id, decision.selected_model_id)] + list(
            decision.fallback_chain,
        )
        auth_cache: dict[str, tuple[str | None, str | None]] = {}
        last_err: Exception | None = None

        for attempt_idx, (pid, mid) in enumerate(chain):
            if time.monotonic() > deadline:
                record_inference_outcome("embedding", "timeout")
                raise InferenceExecutionError(
                    "global_latency_cap_exceeded",
                    category=ErrorCategory.TIMEOUT,
                    retryable=False,
                )

            prov = provider_from_binding(binding, pid)
            if prov is None or not prov.enabled:
                continue

            req_attempt = req.model_copy(update={"provider_id": pid, "model_id": mid})
            if pid not in auth_cache:
                auth_cache[pid] = _resolve_auth(prov)
            api_key, bearer = auth_cache[pid]

            adapter = adapter_for(prov.adapter_protocol)
            try:
                raw = await adapter.infer_embedding(
                    prov,
                    req_attempt,
                    api_key=api_key,
                    bearer_token=bearer,
                )
            except InferenceError as ie:
                last_err = ie
                if "http_404" in str(ie).lower():
                    continue
                raise
            except Exception as exc:
                last_err = exc
                continue

            out = raw.model_copy(
                update={
                    "inference_id": inference_id,
                    "provider_id": pid,
                    "routing_decision_id": decision.id,
                },
            )
            await self._emit_audit(
                AuditEventType.INFERENCE_COMPLETED,
                actor=req.actor,
                resource_id=inference_id,
                action="embedding",
                trace_id=req.trace_id,
                details={
                    "inference_id": inference_id,
                    "provider_id": pid,
                    "model_id": out.model_id,
                    "routing_decision_id": decision.id,
                    "system_config_version": binding.system_config_version,
                    "fallback_position": attempt_idx,
                },
            )
            record_inference_outcome("embedding", "success")
            return out

        await self._emit_audit(
            AuditEventType.INFERENCE_FAILED,
            actor=req.actor,
            resource_id=inference_id,
            action="embedding",
            trace_id=req.trace_id,
            details={
                "inference_id": inference_id,
                "phase": "exhausted",
                "last_error": str(last_err) if last_err else "",
            },
        )
        record_inference_outcome("embedding", "exhausted")
        raise InferenceExecutionError(
            "all_candidates_failed",
            category=ErrorCategory.PROVIDER,
            retryable=False,
        )

    async def stream_chat(self, req: ChatInferenceRequest) -> AsyncIterator[str]:
        """API-only streaming; emits provisional + final audit events.

        Phase 1: single primary candidate only (no streaming fallback chain).
        """
        binding = ExecutionBinding.capture(self._loader, self._catalog)
        inference_id = str(ULID())
        req = req.model_copy(update={"trace_id": req.trace_id or inference_id})

        router = InferenceRouter(binding.system_config.routing)
        policy_port = PolicyEngineRoutingPort(self._policy_engine)

        await self._emit_audit(
            AuditEventType.INFERENCE_STREAM_STARTED,
            actor=req.actor,
            resource_id=inference_id,
            action="chat_stream",
            trace_id=req.trace_id,
            details={
                "inference_id": inference_id,
                "system_config_version": binding.system_config_version,
                "catalog_snapshot_version": binding.catalog_snapshot_version,
                "status": "executing",
            },
        )

        decision = await router.route(
            req,
            system=binding.system_config,
            registry=self._registry,
            catalog=self._catalog,
            policy=policy_port,
            policy_cache=self._policy_cache,
        )
        pid, mid = decision.selected_provider_id, decision.selected_model_id
        prov = provider_from_binding(binding, pid)
        if prov is None:
            await self._emit_audit(
                AuditEventType.INFERENCE_STREAM_FAILED,
                actor=req.actor,
                resource_id=inference_id,
                action="chat_stream",
                trace_id=req.trace_id,
                details={"inference_id": inference_id, "error": "no_provider"},
            )
            return

        api_key, bearer = _resolve_auth(prov)
        adapter = adapter_for(prov.adapter_protocol)
        req_attempt = req.model_copy(update={"provider_id": pid, "model_id": mid})

        try:
            async for delta in adapter.stream_chat(
                prov,
                req_attempt,
                api_key=api_key,
                bearer_token=bearer,
            ):
                yield delta
        except Exception as exc:
            await self._emit_audit(
                AuditEventType.INFERENCE_STREAM_FAILED,
                actor=req.actor,
                resource_id=inference_id,
                action="chat_stream",
                trace_id=req.trace_id,
                details={"inference_id": inference_id, "error": str(exc)},
            )
            record_inference_outcome("chat_stream", "failed")
            raise

        await self._emit_audit(
            AuditEventType.INFERENCE_STREAM_COMPLETED,
            actor=req.actor,
            resource_id=inference_id,
            action="chat_stream",
            trace_id=req.trace_id,
            details={
                "inference_id": inference_id,
                "provider_id": pid,
                "model_id": mid,
                "routing_decision_id": decision.id,
                "system_config_version": binding.system_config_version,
            },
        )
        record_inference_outcome("chat_stream", "success")

    async def _emit_audit(
        self,
        event_type: AuditEventType,
        *,
        actor: str,
        resource_id: str,
        action: str,
        trace_id: str | None,
        details: dict[str, Any],
    ) -> None:
        ev = AuditEvent(
            event_type=event_type,
            actor=actor,
            resource_type="inference",
            resource_id=resource_id,
            action=action,
            details=details,
            trace_id=trace_id,
        )
        await self._audit.emit(ev)
