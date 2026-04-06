"""Load and atomically activate YAML provider system configuration."""

from __future__ import annotations

import os
import threading
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from syndicateclaw.inference.config_schema import ProviderSystemConfig
from syndicateclaw.inference.hashing import canonical_json_hash


class ProviderConfigDiff(BaseModel):
    """Structured diff between two provider sets (identity = provider id)."""

    model_config = ConfigDict(frozen=True)

    added_provider_ids: tuple[str, ...] = ()
    removed_provider_ids: tuple[str, ...] = ()
    modified_provider_ids: tuple[str, ...] = ()


class ConfigReloadResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    system_config_version: str
    diff: ProviderConfigDiff


def _provider_config_fingerprint(cfg: ProviderSystemConfig) -> dict[str, str]:
    return {p.id: canonical_json_hash(p.model_dump(mode="json")) for p in cfg.providers}


def compute_provider_diff(
    old: ProviderSystemConfig | None,
    new: ProviderSystemConfig,
) -> ProviderConfigDiff:
    """Compute added / removed / modified provider ids using canonical JSON hashes."""
    new_fp = _provider_config_fingerprint(new)
    if old is None:
        return ProviderConfigDiff(
            added_provider_ids=tuple(sorted(new_fp.keys())),
        )
    old_fp = _provider_config_fingerprint(old)
    old_ids = set(old_fp)
    new_ids = set(new_fp)
    added = tuple(sorted(new_ids - old_ids))
    removed = tuple(sorted(old_ids - new_ids))
    common = old_ids & new_ids
    modified = tuple(sorted(pid for pid in common if old_fp[pid] != new_fp[pid]))
    return ProviderConfigDiff(
        added_provider_ids=added,
        removed_provider_ids=removed,
        modified_provider_ids=modified,
    )


class ProviderConfigLoader:
    """Parse YAML, validate full graph, atomically swap active config, emit structured diff."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._lock = threading.RLock()
        self._active: ProviderSystemConfig | None = None
        self._version_seq: int = 0

    @property
    def path(self) -> Path:
        return self._path

    def current(self) -> tuple[ProviderSystemConfig, str]:
        """Return active config and monotonic ``system_config_version`` string."""
        with self._lock:
            if self._active is None:
                raise RuntimeError("ProviderConfigLoader: no successful load yet")
            return self._active, str(self._version_seq)

    def load_validate(self) -> ProviderSystemConfig:
        """Read YAML from disk and validate the full graph (no activation)."""
        text = self._path.read_text(encoding="utf-8")
        raw = yaml.safe_load(text)
        if raw is None:
            raise ValueError("provider YAML is empty")
        return ProviderSystemConfig.model_validate(raw)

    def activate(self, config: ProviderSystemConfig) -> ConfigReloadResult:
        """Atomically replace active config after external validation."""
        with self._lock:
            old = self._active
            diff = compute_provider_diff(old, config)
            self._version_seq += 1
            self._active = config
            return ConfigReloadResult(
                system_config_version=str(self._version_seq),
                diff=diff,
            )

    def load_and_activate(self) -> ConfigReloadResult:
        """Validate from disk and activate in one step."""
        cfg = self.load_validate()
        return self.activate(cfg)


class ConfigurationError(Exception):
    """Raised for fatal provider configuration startup errors."""


def validate_provider_env_vars(config: ProviderSystemConfig) -> None:
    """Fail fast when configured provider auth env vars are missing/empty."""
    for provider in config.providers:
        auth = provider.auth
        if auth is None or not auth.env_var:
            continue
        value = os.environ.get(auth.env_var)
        if value is None or not value.strip():
            raise ConfigurationError(f"Provider '{provider.id}' requires env var '{auth.env_var}'")
