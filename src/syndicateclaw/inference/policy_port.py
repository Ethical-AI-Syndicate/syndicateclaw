"""Bind PolicyEngine to PolicyRoutingPort (Gate 2–3 for inference; async)."""

from __future__ import annotations

from syndicateclaw.inference.policy_gates import BoundedPolicyCache
from syndicateclaw.inference.types import InferenceCapability
from syndicateclaw.models import PolicyEffect
from syndicateclaw.policy.engine import PolicyEngine


class PolicyEngineRoutingPort:
    """Gate 2: inference invoke; Gate 3: model:use — fail-closed on evaluate errors."""

    def __init__(self, policy_engine: PolicyEngine) -> None:
        self._pe = policy_engine

    async def gate_inference_capability(
        self,
        *,
        capability: InferenceCapability,
        actor: str,
        scope_type: str,
        scope_id: str,
    ) -> str:
        resource_id = "chat" if capability == InferenceCapability.CHAT else "embedding"
        try:
            d = await self._pe.evaluate(
                "inference",
                resource_id,
                "invoke",
                actor,
                {
                    "scope_type": scope_type,
                    "scope_id": scope_id,
                    "capability": capability.value,
                },
            )
        except Exception:
            return "deny"
        eff = d.effect if hasattr(d, "effect") else d
        return "allow" if eff != PolicyEffect.DENY else "deny"

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
    ) -> str:
        rid = f"{provider_id}:{model_id}"
        try:
            d = await self._pe.evaluate(
                "model",
                rid,
                "use",
                actor,
                {
                    "capability": capability.value,
                    "scope_type": scope_type,
                    "scope_id": scope_id,
                    "provider_id": provider_id,
                    "model_id": model_id,
                },
            )
        except Exception:
            return "deny"
        eff = d.effect if hasattr(d, "effect") else d
        return "allow" if eff != PolicyEffect.DENY else "deny"
