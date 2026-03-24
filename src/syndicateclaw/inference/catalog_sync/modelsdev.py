"""models.dev-style JSON merge: never activates providers; only YAML-known provider_ids."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict

from syndicateclaw.inference.catalog import CatalogEntryRecord, ModelCatalog
from syndicateclaw.inference.config_schema import ProviderSystemConfig, StaticCatalogEntry
from syndicateclaw.inference.types import (
    CatalogEntrySource,
    CatalogEntryStatus,
    InferenceCapability,
    ModelDescriptor,
)


class ModelsDevSyncResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    applied: bool
    snapshot_version: str
    records_accepted: int
    records_skipped: int
    previous_snapshot_version: str | None = None
    aborted_reason: str | None = None


class ModelsDevCatalogSync:
    """Merge validated rows into ModelCatalog; skip unmapped providers; anomaly abort."""

    def __init__(
        self,
        *,
        base_system_config: ProviderSystemConfig,
        allowed_provider_ids: frozenset[str],
        catalog: ModelCatalog,
        yaml_static_rows: tuple[StaticCatalogEntry, ...],
        yaml_wins_on_key_collision: bool = True,
        anomaly_max_drop_ratio: float = 0.5,
    ) -> None:
        self._base_system = base_system_config
        self._allowed = allowed_provider_ids
        self._catalog = catalog
        self._yaml_rows = yaml_static_rows
        self._yaml_wins = yaml_wins_on_key_collision
        self._anomaly_max_drop = anomaly_max_drop_ratio
        self._rollback_stack: list[tuple[str, str]] = []

    def sync_from_parsed_records(
        self,
        records: list[dict[str, Any]],
        *,
        snapshot_version: str,
        previous_count: int | None = None,
    ) -> ModelsDevSyncResult:
        """Full parse failure should be handled by caller; here we skip bad rows."""
        if previous_count is None:
            previous_count = self._catalog.entry_count

        accepted: list[CatalogEntryRecord] = []
        skipped = 0
        for raw in records:
            try:
                row = _record_to_catalog_entry(raw)
            except (KeyError, ValueError, TypeError):
                skipped += 1
                continue
            if row.provider_id not in self._allowed:
                skipped += 1
                continue
            accepted.append(row)

        if previous_count > 0 and len(accepted) < (1.0 - self._anomaly_max_drop) * previous_count:
            return ModelsDevSyncResult(
                applied=False,
                snapshot_version=self._catalog.snapshot_version,
                records_accepted=0,
                records_skipped=skipped,
                aborted_reason="systemic_anomaly_drop",
            )

        prev_ver = self._catalog.snapshot_version
        self._rollback_stack.append((prev_ver, snapshot_version))
        self._catalog.merge_yaml_and_models_dev(
            yaml_rows=self._yaml_rows,
            models_dev_rows=tuple(accepted),
            snapshot_version=snapshot_version,
            yaml_wins_on_key_collision=self._yaml_wins,
        )
        return ModelsDevSyncResult(
            applied=True,
            snapshot_version=snapshot_version,
            records_accepted=len(accepted),
            records_skipped=skipped,
            previous_snapshot_version=prev_ver,
        )

    def rollback_to_snapshot(self, snapshot_version: str) -> bool:
        """Restore YAML-static materialization to ``prev`` after a failed or bad apply."""
        for prev, ver in self._rollback_stack:
            if ver == snapshot_version:
                self._catalog.replace_from_yaml_static(
                    self._base_system,
                    snapshot_version=prev,
                )
                return True
        return False


def _record_to_catalog_entry(raw: dict[str, Any]) -> CatalogEntryRecord:
    pid = str(raw["provider_id"])
    mid = str(raw["model_id"])
    cap = InferenceCapability(raw.get("capability", "chat"))
    desc = ModelDescriptor(
        model_id=mid,
        name=str(raw.get("name", mid)),
        provider_id=pid,
        is_embedding_model=raw.get("is_embedding_model", False),
        embedding_dimensions=raw.get("embedding_dimensions"),
    )
    return CatalogEntryRecord(
        provider_id=pid,
        model_id=mid,
        descriptor=desc,
        capabilities=frozenset({cap}),
        status=CatalogEntryStatus.ACTIVE,
        source=CatalogEntrySource.MODELS_DEV,
    )


def parse_models_dev_json(text: str) -> list[dict[str, Any]]:
    """Full parse failure → raise (caller retains previous catalog)."""
    data = json.loads(text)
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict) and "models" in data:
        m = data["models"]
        if isinstance(m, list):
            return [x for x in m if isinstance(x, dict)]
    raise ValueError("models.dev JSON: expected list or {models: [...]}")
