"""Frozen execution binding — routing determinism is relative to this tuple + registry reads."""

from __future__ import annotations

from dataclasses import dataclass

from syndicateclaw.inference.catalog import ModelCatalog
from syndicateclaw.inference.config_loader import ProviderConfigLoader
from syndicateclaw.inference.config_schema import ProviderSystemConfig
from syndicateclaw.inference.types import ProviderConfig


@dataclass(frozen=True)
class ExecutionBinding:
    """Captured at request start; ProviderService must not swap to latest loader mid-attempt."""

    system_config: ProviderSystemConfig
    system_config_version: str
    catalog_snapshot_version: str

    @staticmethod
    def capture(loader: ProviderConfigLoader, catalog: ModelCatalog) -> ExecutionBinding:
        cfg, ver = loader.current()
        return ExecutionBinding(
            system_config=cfg,
            system_config_version=ver,
            catalog_snapshot_version=catalog.snapshot_version,
        )


def provider_from_binding(binding: ExecutionBinding, provider_id: str) -> ProviderConfig | None:
    for p in binding.system_config.providers:
        if p.id == provider_id:
            return p
    return None
