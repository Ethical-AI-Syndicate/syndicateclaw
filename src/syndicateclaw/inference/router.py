"""InferenceRouter — deterministic, side-effect-free routing (pure read of registry + catalog).

Does not mutate circuit state, cooldowns, health, or catalog contents. ProviderService
owns those side effects after routing.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from ulid import ULID

from syndicateclaw.inference.catalog import CatalogEntryRecord, ModelCatalog
from syndicateclaw.inference.config_schema import (
    ProviderSystemConfig,
    RoutingPolicyConfig,
    RoutingWeights,
)
from syndicateclaw.inference.errors import InferenceRoutingError
from syndicateclaw.inference.hashing import canonical_json_hash
from syndicateclaw.inference.policy_gates import BoundedPolicyCache
from syndicateclaw.inference.registry import ProviderRegistryRead
from syndicateclaw.inference.types import (
    ChatInferenceRequest,
    CircuitState,
    DataSensitivity,
    EmbeddingInferenceRequest,
    InferenceCapability,
    ModelDescriptor,
    ModelPinning,
    ProviderConfig,
    ProviderStatus,
    ProviderTrustTier,
    RoutingDecision,
    RoutingFailureReason,
)


def _sensitivity_rank(s: DataSensitivity) -> int:
    return {
        DataSensitivity.PUBLIC: 0,
        DataSensitivity.INTERNAL: 1,
        DataSensitivity.CONFIDENTIAL: 2,
        DataSensitivity.RESTRICTED: 3,
    }[s]


def _sensitivity_allowed(request_level: DataSensitivity, provider_max: DataSensitivity) -> bool:
    return _sensitivity_rank(request_level) <= _sensitivity_rank(provider_max)


def _capability_for(
    request: ChatInferenceRequest | EmbeddingInferenceRequest,
) -> InferenceCapability:
    if request.capability == "chat":
        return InferenceCapability.CHAT
    return InferenceCapability.EMBEDDING


def _policy_model_key(
    *,
    provider_id: str,
    model_id: str,
    capability: InferenceCapability,
    actor: str,
    scope_type: str,
    scope_id: str,
) -> str:
    return canonical_json_hash(
        {
            "provider_id": provider_id,
            "model_id": model_id,
            "capability": capability.value,
            "actor": actor,
            "scope_type": scope_type,
            "scope_id": scope_id,
        },
    )


@runtime_checkable
class PolicyRoutingPort(Protocol):
    """Policy hooks for routing (async PolicyEngine.evaluate from ProviderService)."""

    async def gate_inference_capability(
        self,
        *,
        capability: InferenceCapability,
        actor: str,
        scope_type: str,
        scope_id: str,
    ) -> Literal["allow", "deny"]: ...

    async def gate_model_use(
        self,
        *,
        provider_id: str,
        model_id: str,
        capability: InferenceCapability,
        actor: str,
        scope_type: str,
        scope_id: str,
        cache: BoundedPolicyCache,
    ) -> Literal["allow", "deny"]: ...


@dataclass(frozen=True)
class _Scored:
    provider_id: str
    model_id: str
    score: float


class InferenceRouter:
    """Deterministic routing for identical inputs, catalog snapshot, config, registry view."""

    def __init__(self, routing: RoutingPolicyConfig) -> None:
        self._routing = routing

    async def route(
        self,
        request: ChatInferenceRequest | EmbeddingInferenceRequest,
        *,
        system: ProviderSystemConfig,
        registry: ProviderRegistryRead,
        catalog: ModelCatalog,
        policy: PolicyRoutingPort,
        policy_cache: BoundedPolicyCache,
        resolved_pin: tuple[str, str] | None = None,
        now: float | None = None,
    ) -> RoutingDecision:
        """Return a primary selection and ordered fallback chain (re-validate per attempt)."""
        t = time.monotonic() if now is None else now
        if not system.inference_enabled:
            raise InferenceRoutingError(
                "inference_disabled",
                failure_reason=RoutingFailureReason.NO_CANDIDATES,
            )

        cap = _capability_for(request)
        if await policy.gate_inference_capability(
            capability=cap,
            actor=request.actor,
            scope_type=request.scope_type,
            scope_id=request.scope_id,
        ) != "allow":
            raise InferenceRoutingError(
                "inference_capability_denied",
                failure_reason=RoutingFailureReason.POLICY_DENIED,
            )

        if not _pin_satisfied(request, resolved_pin):
            raise InferenceRoutingError(
                "model_pin_required",
                failure_reason=RoutingFailureReason.PIN_MISMATCH,
            )

        candidates = sorted(
            list(catalog.iter_by_capability(cap)),
            key=lambda r: (r.provider_id, r.model_id),
        )
        considered = len(candidates)

        narrowed = _narrow_explicit(request, candidates)
        filtered_pre = considered - len(narrowed)

        scored: list[_Scored] = []
        weights = self._routing.weights
        cap_w = self._routing.cost_weight_cap
        dropped = 0

        for entry in narrowed:
            if len(scored) >= self._routing.policy_max_candidates_per_request:
                break
            pid, mid = entry.provider_id, entry.model_id
            prov = registry.get_provider(pid)
            if prov is None:
                dropped += 1
                continue
            if not prov.enabled:
                dropped += 1
                continue
            if registry.is_runtime_disabled(pid):
                dropped += 1
                continue
            if registry.circuit_state(pid, now=t) == CircuitState.OPEN:
                dropped += 1
                continue
            if registry.is_rate_limit_cooldown(pid, now=t):
                dropped += 1
                continue
            hs = registry.health_status(pid)
            if hs == ProviderStatus.UNAVAILABLE:
                dropped += 1
                continue
            if not _sensitivity_allowed(request.sensitivity, prov.max_allowed_sensitivity):
                dropped += 1
                continue

            pkey = _policy_model_key(
                provider_id=pid,
                model_id=mid,
                capability=cap,
                actor=request.actor,
                scope_type=request.scope_type,
                scope_id=request.scope_id,
            )
            cached = policy_cache.get(pkey, now=t)
            if cached is None:
                ans = await policy.gate_model_use(
                    provider_id=pid,
                    model_id=mid,
                    capability=cap,
                    actor=request.actor,
                    scope_type=request.scope_type,
                    scope_id=request.scope_id,
                    cache=policy_cache,
                )
                policy_cache.set(pkey, ans, now=t)
            else:
                ans = cached
            if ans != "allow":
                dropped += 1
                continue

            degraded = hs == ProviderStatus.DEGRADED
            score = _score(
                entry.descriptor,
                prov,
                request.sensitivity,
                weights,
                cap_w,
                degraded=degraded,
            )
            scored.append(_Scored(pid, mid, score))

        if not scored:
            raise InferenceRoutingError(
                "no_routable_candidates",
                failure_reason=RoutingFailureReason.NO_CANDIDATES,
            )

        scored.sort(key=lambda s: (s.score, s.provider_id, s.model_id))
        primary = scored[0]
        rest = [(s.provider_id, s.model_id) for s in scored[1:]]

        return RoutingDecision(
            id=str(ULID()),
            selected_provider_id=primary.provider_id,
            selected_model_id=primary.model_id,
            selection_reason="lowest_score_lex_tiebreak",
            fallback_chain=rest,
            candidates_considered=considered,
            candidates_filtered=filtered_pre + dropped,
        )


def _pin_satisfied(
    request: ChatInferenceRequest | EmbeddingInferenceRequest,
    resolved_pin: tuple[str, str] | None,
) -> bool:
    if request.model_pinning != ModelPinning.REQUIRED:
        return True
    if request.model_id and request.provider_id:
        return True
    return resolved_pin is not None


def _narrow_explicit(
    request: ChatInferenceRequest | EmbeddingInferenceRequest,
    rows: list[CatalogEntryRecord],
) -> list[CatalogEntryRecord]:
    if request.provider_id and request.model_id:
        return [
            r
            for r in rows
            if r.provider_id == request.provider_id and r.model_id == request.model_id
        ]
    if request.provider_id:
        return [r for r in rows if r.provider_id == request.provider_id]
    if request.model_id:
        return [r for r in rows if r.model_id == request.model_id]
    return rows


def _score(
    descriptor: ModelDescriptor,
    provider: ProviderConfig,
    req_sensitivity: DataSensitivity,
    weights: RoutingWeights,
    cost_cap: float,
    *,
    degraded: bool,
) -> float:
    cost = min(
        descriptor.cost.input_per_million + descriptor.cost.output_per_million,
        cost_cap,
    )
    latency_proxy = 1.0 / max(descriptor.limits.context_window, 1)
    score = weights.cost * cost + weights.latency_proxy * latency_proxy
    if degraded:
        score += weights.degraded_penalty
    if provider.trust_tier == ProviderTrustTier.TRUSTED:
        score -= weights.trust_tier_trusted_bonus
    if provider.trust_tier == ProviderTrustTier.UNTRUSTED:
        score += weights.trust_tier_untrusted_penalty
    if _sensitivity_rank(req_sensitivity) == _sensitivity_rank(provider.max_allowed_sensitivity):
        score -= weights.sensitivity_match_bonus
    return score
