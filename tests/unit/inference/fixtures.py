"""Shared builders for inference unit tests."""

from __future__ import annotations

from syndicateclaw.inference.config_schema import (
    ProviderSystemConfig,
    RoutingPolicyConfig,
    StaticCatalogEntry,
)
from syndicateclaw.inference.types import (
    AdapterProtocol,
    InferenceCapability,
    ModelDescriptor,
    ProviderConfig,
    ProviderType,
)


def provider(
    pid: str,
    *,
    capabilities: list[InferenceCapability] | None = None,
    enabled: bool = True,
) -> ProviderConfig:
    return ProviderConfig(
        id=pid,
        name=f"name-{pid}",
        provider_type=ProviderType.LOCAL,
        adapter_protocol=AdapterProtocol.OLLAMA_NATIVE,
        base_url="http://127.0.0.1:1",
        capabilities=capabilities or [InferenceCapability.CHAT],
        enabled=enabled,
    )


def chat_descriptor(provider_id: str, model_id: str) -> ModelDescriptor:
    return ModelDescriptor(
        model_id=model_id,
        name=model_id,
        provider_id=provider_id,
        is_embedding_model=False,
    )


def static_chat_row(provider_id: str, model_id: str) -> StaticCatalogEntry:
    return StaticCatalogEntry(
        provider_id=provider_id,
        model_id=model_id,
        capability=InferenceCapability.CHAT,
        descriptor=chat_descriptor(provider_id, model_id),
    )


def minimal_system(
    *providers: ProviderConfig,
    static: tuple[StaticCatalogEntry, ...] = (),
    routing: RoutingPolicyConfig | None = None,
) -> ProviderSystemConfig:
    return ProviderSystemConfig(
        inference_enabled=True,
        providers=tuple(providers),
        static_catalog=static,
        routing=routing or RoutingPolicyConfig(),
    )
