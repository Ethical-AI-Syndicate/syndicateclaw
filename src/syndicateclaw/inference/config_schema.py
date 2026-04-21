"""Pydantic schema for YAML provider system configuration (Phase 1 — YAML authoritative)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from syndicateclaw.inference.types import (
    InferenceCapability,
    ModelDescriptor,
    ProviderConfig,
)


class RoutingWeights(BaseModel):
    """Explicit scoring weights (lower total score ranks higher)."""

    model_config = ConfigDict(frozen=True, ignored_types=(dict,))

    cost: float = 1.0
    latency_proxy: float = 0.001
    sensitivity_match_bonus: float = 2.0
    degraded_penalty: float = 100.0
    trust_tier_trusted_bonus: float = 0.0
    trust_tier_untrusted_penalty: float = 50.0


class RoutingPolicyConfig(BaseModel):
    model_config = ConfigDict(frozen=True, ignored_types=(dict,))

    weights: RoutingWeights = Field(default_factory=RoutingWeights)
    cost_weight_cap: float = 1_000_000.0
    policy_cache_ttl_seconds: float = 60.0
    policy_max_candidates_per_request: int = 64
    max_total_latency_ms: float = 120_000.0


class YamlCatalogCoexistence(BaseModel):
    """When static YAML and models.dev-derived rows share a snapshot, resolution is explicit."""

    model_config = ConfigDict(frozen=True, ignored_types=(dict,))

    yaml_wins_on_key_collision: bool = Field(
        True,
        description=(
            "Same (provider_id, model_id): keep YAML static descriptor; skip models.dev row."
        ),
    )


class ModelsDevSyncConfigStub(BaseModel):
    """Placeholder for models.dev sync (CP4). Disabled in Phase 1 wiring until sync exists."""

    model_config = ConfigDict(frozen=True, ignored_types=(dict,))

    enabled: bool = False


class StaticCatalogEntry(BaseModel):
    """YAML-seeded catalog row (does not activate providers; references ProviderConfig.id)."""

    model_config = ConfigDict(frozen=True, ignored_types=(dict,))

    provider_id: str
    model_id: str
    capability: InferenceCapability
    descriptor: ModelDescriptor

    @model_validator(mode="after")
    def align_descriptor_identity(self) -> StaticCatalogEntry:
        if self.descriptor.model_id != self.model_id:
            raise ValueError("descriptor.model_id must match model_id")
        if self.descriptor.provider_id != self.provider_id:
            raise ValueError("descriptor.provider_id must match provider_id")
        return self


class ProviderSystemConfig(BaseModel):
    """Full validated graph loaded before activation (see ProviderConfigLoader)."""

    model_config = ConfigDict(frozen=True, ignored_types=(dict,))

    inference_enabled: bool = True
    providers: tuple[ProviderConfig, ...] = ()
    routing: RoutingPolicyConfig = Field(default_factory=RoutingPolicyConfig)
    static_catalog: tuple[StaticCatalogEntry, ...] = ()
    catalog_coexistence: YamlCatalogCoexistence = Field(default_factory=YamlCatalogCoexistence)
    models_dev: ModelsDevSyncConfigStub = Field(default_factory=ModelsDevSyncConfigStub)

    @model_validator(mode="after")
    def validate_graph(self) -> ProviderSystemConfig:
        ids = [p.id for p in self.providers]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate provider id in providers")
        prov = set(ids)
        for entry in self.static_catalog:
            if entry.provider_id not in prov:
                raise ValueError(
                    f"static_catalog references unknown provider_id: {entry.provider_id}",
                )
        return self
