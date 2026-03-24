"""Provider integration layer — inference orchestration (spec-driven)."""

from syndicateclaw.inference.catalog import ModelCatalog
from syndicateclaw.inference.config_loader import ConfigReloadResult, ProviderConfigLoader
from syndicateclaw.inference.config_schema import ProviderSystemConfig
from syndicateclaw.inference.hashing import canonical_json_hash
from syndicateclaw.inference.registry import ProviderRegistry
from syndicateclaw.inference.router import InferenceRouter
from syndicateclaw.inference.service import ProviderService
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
    "ConfigReloadResult",
    "canonical_json_hash",
    "ChatInferenceRequest",
    "EmbeddingInferenceRequest",
    "InferenceCapability",
    "InferenceRouter",
    "ModelCatalog",
    "ProviderConfig",
    "ProviderConfigLoader",
    "ProviderRegistry",
    "ProviderService",
    "ProviderSystemConfig",
    "ProviderType",
]
