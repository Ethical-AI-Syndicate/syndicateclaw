"""Provider integration layer — inference orchestration (spec-driven)."""

from syndicateclaw.inference.hashing import canonical_json_hash
from syndicateclaw.inference.types import (
    AdapterProtocol,
    ChatInferenceRequest,
    EmbeddingInferenceRequest,
    InferenceCapability,
    ProviderConfig,
    ProviderType,
)

__all__ = [
    "AdapterProtocol",
    "canonical_json_hash",
    "ChatInferenceRequest",
    "EmbeddingInferenceRequest",
    "InferenceCapability",
    "ProviderConfig",
    "ProviderType",
]
