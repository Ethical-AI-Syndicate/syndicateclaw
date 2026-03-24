"""Stable fingerprints for idempotency hashing (excludes trace_id and idempotency_key)."""

from __future__ import annotations

from syndicateclaw.inference.types import ChatInferenceRequest, EmbeddingInferenceRequest


def fingerprint_chat(req: ChatInferenceRequest) -> dict:
    """Canonical dict for chat idempotency (same logical request → same hash)."""
    return {
        "actor": req.actor,
        "capability": req.capability,
        "max_tokens": req.max_tokens,
        "messages": [m.model_dump() for m in req.messages],
        "model_id": req.model_id,
        "model_pinning": req.model_pinning.value
        if hasattr(req.model_pinning, "value")
        else str(req.model_pinning),
        "provider_id": req.provider_id,
        "scope_id": req.scope_id,
        "scope_type": req.scope_type,
        "sensitivity": req.sensitivity.value
        if hasattr(req.sensitivity, "value")
        else str(req.sensitivity),
        "temperature": req.temperature,
    }


def fingerprint_embedding(req: EmbeddingInferenceRequest) -> dict:
    return {
        "actor": req.actor,
        "capability": req.capability,
        "inputs": list(req.inputs),
        "model_id": req.model_id,
        "model_pinning": req.model_pinning.value
        if hasattr(req.model_pinning, "value")
        else str(req.model_pinning),
        "provider_id": req.provider_id,
        "scope_id": req.scope_id,
        "scope_type": req.scope_type,
    }
