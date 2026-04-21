"""ModelCatalog — in-memory catalog keyed by canonical (provider_id, model_id).

Facts here are materialized views: YAML static rows, optional models.dev rows (CP4),
and future validation hooks. Provider topology remains YAML-authoritative (Phase 1).

When ``yaml_wins_on_key_collision`` is True, a models.dev row with the same
``(provider_id, model_id)`` as a YAML-static row is skipped so static operator
intent wins; the snapshot version still advances for traceability.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from collections.abc import Iterator, Sequence

from pydantic import BaseModel, ConfigDict

from syndicateclaw.inference.config_schema import ProviderSystemConfig, StaticCatalogEntry
from syndicateclaw.inference.types import (
    CatalogEntrySource,
    CatalogEntryStatus,
    InferenceCapability,
    ModelDescriptor,
)


class CatalogEntryRecord(BaseModel):
    """Single canonical row per (provider_id, model_id)."""

    model_config = ConfigDict(frozen=True, ignored_types=(dict,))

    provider_id: str
    model_id: str
    descriptor: ModelDescriptor
    capabilities: frozenset[InferenceCapability]
    status: CatalogEntryStatus = CatalogEntryStatus.ACTIVE
    source: CatalogEntrySource = CatalogEntrySource.YAML_STATIC


class ModelCatalog:
    """Thread-safe catalog with atomic snapshot swap and secondary indexes."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._snapshot_version: str = "0"
        self._entries: dict[tuple[str, str], CatalogEntryRecord] = {}
        self._by_capability_provider: dict[tuple[InferenceCapability, str], list[str]] = (
            defaultdict(list)
        )
        self._by_model_id: dict[str, list[tuple[str, str]]] = defaultdict(list)

    @property
    def snapshot_version(self) -> str:
        with self._lock:
            return self._snapshot_version

    @property
    def entry_count(self) -> int:
        with self._lock:
            return len(self._entries)

    def get(self, provider_id: str, model_id: str) -> CatalogEntryRecord | None:
        with self._lock:
            return self._entries.get((provider_id, model_id))

    def iter_by_capability(self, capability: InferenceCapability) -> Iterator[CatalogEntryRecord]:
        with self._lock:
            items = list(self._entries.values())
        for row in items:
            if capability in row.capabilities and row.status == CatalogEntryStatus.ACTIVE:
                yield row

    def models_for_capability_and_provider(
        self,
        capability: InferenceCapability,
        provider_id: str,
    ) -> tuple[str, ...]:
        """Index: (capability, provider_id) → model_ids (sorted for determinism)."""
        with self._lock:
            key = (capability, provider_id)
            mids = list(self._by_capability_provider.get(key, ()))
        return tuple(sorted(mids))

    def providers_for_model_id(self, model_id: str) -> tuple[tuple[str, str], ...]:
        """Secondary index: model_id → (provider_id, model_id) pairs."""
        with self._lock:
            pairs = list(self._by_model_id.get(model_id, ()))
        return tuple(sorted(pairs))

    def replace_from_yaml_static(
        self,
        system: ProviderSystemConfig,
        *,
        snapshot_version: str,
    ) -> None:
        """Build catalog from YAML static entries only (merged by canonical key)."""
        merged = _merge_static_catalog_rows(system.static_catalog)
        self._replace_entries(merged, snapshot_version=snapshot_version)

    def merge_yaml_and_models_dev(
        self,
        *,
        yaml_rows: Sequence[StaticCatalogEntry],
        models_dev_rows: Sequence[CatalogEntryRecord],
        snapshot_version: str,
        yaml_wins_on_key_collision: bool,
    ) -> None:
        """Atomic merge for snapshots that combine static YAML with models.dev-derived rows."""
        merged_yaml = _merge_static_catalog_rows(tuple(yaml_rows))
        combined: dict[tuple[str, str], CatalogEntryRecord] = {}
        for k, row in merged_yaml.items():
            combined[k] = row
        for row in sorted(models_dev_rows, key=lambda r: (r.provider_id, r.model_id)):
            k = (row.provider_id, row.model_id)
            if k in combined and yaml_wins_on_key_collision:
                continue
            combined[k] = row
        self._replace_entries(combined, snapshot_version=snapshot_version)

    def _replace_entries(
        self,
        entries: dict[tuple[str, str], CatalogEntryRecord],
        *,
        snapshot_version: str,
    ) -> None:
        by_cp: dict[tuple[InferenceCapability, str], list[str]] = defaultdict(list)
        by_mid: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for (pid, mid), row in entries.items():
            if row.status != CatalogEntryStatus.ACTIVE:
                continue
            for cap in row.capabilities:
                by_cp[(cap, pid)].append(mid)
            by_mid[mid].append((pid, mid))
        for k in by_cp:
            by_cp[k] = sorted(set(by_cp[k]))
        for mid in by_mid:
            by_mid[mid] = sorted(set(by_mid[mid]))
        with self._lock:
            self._snapshot_version = snapshot_version
            self._entries = dict(entries)
            self._by_capability_provider = by_cp
            self._by_model_id = dict(by_mid)


def _merge_static_catalog_rows(
    rows: tuple[StaticCatalogEntry, ...],
) -> dict[tuple[str, str], CatalogEntryRecord]:
    grouped: dict[tuple[str, str], list[StaticCatalogEntry]] = defaultdict(list)
    for e in rows:
        grouped[(e.provider_id, e.model_id)].append(e)
    out: dict[tuple[str, str], CatalogEntryRecord] = {}
    for key, group in grouped.items():
        group.sort(key=lambda e: e.capability.value)
        desc = group[0].descriptor
        for e in group[1:]:
            if e.descriptor != desc:
                raise ValueError(
                    f"conflicting ModelDescriptor for {key}: merge static_catalog rows",
                )
        caps = frozenset(e.capability for e in group)
        out[key] = CatalogEntryRecord(
            provider_id=key[0],
            model_id=key[1],
            descriptor=desc,
            capabilities=caps,
            status=CatalogEntryStatus.ACTIVE,
            source=CatalogEntrySource.YAML_STATIC,
        )
    return out
