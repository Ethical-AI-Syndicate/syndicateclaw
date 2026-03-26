"""Load skill manifests from YAML/JSON files — deterministic order, fail closed."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from packaging.version import Version
from pydantic import ValidationError

from syndicateclaw.runtime.contracts.skill_manifest import SkillManifest
from syndicateclaw.runtime.errors import ManifestValidationError, RegistryLoadError


def _parse_file(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        data = yaml.safe_load(text)
    elif suffix == ".json":
        import json

        data = json.loads(text)
    else:
        msg = f"unsupported manifest suffix: {path}"
        raise RegistryLoadError(msg)
    if not isinstance(data, dict):
        msg = f"manifest root must be an object: {path}"
        raise RegistryLoadError(msg)
    return data


def load_manifest_file(path: Path) -> SkillManifest:
    """Parse and validate a single manifest file."""
    try:
        raw = _parse_file(path)
        return SkillManifest.model_validate(raw)
    except ValidationError as e:
        msg = f"invalid manifest {path}: {e}"
        raise ManifestValidationError(msg) from e
    except ManifestValidationError:
        raise
    except RegistryLoadError:
        raise
    except Exception as e:
        msg = f"invalid manifest {path}: {e}"
        raise ManifestValidationError(msg) from e


def iter_manifest_paths(directory: Path) -> list[Path]:
    """List manifest files in deterministic order (lexicographic basename / readdir order).

    Load order affects only which duplicate key fails first; it does not change the
    resolved registry after a successful load.
    """
    if not directory.is_dir():
        msg = f"not a directory: {directory}"
        raise RegistryLoadError(msg)
    paths: list[Path] = []
    for p in sorted(directory.iterdir()):
        if p.is_file() and p.suffix.lower() in {".yaml", ".yml", ".json"}:
            paths.append(p)
    return paths


def load_manifests_from_directory(directory: Path) -> list[SkillManifest]:
    """Load all manifests. Duplicate (skill_id, version) is an error."""
    manifests: list[SkillManifest] = []
    seen: set[tuple[str, str]] = set()
    for path in iter_manifest_paths(directory):
        m = load_manifest_file(path)
        key = (m.skill_id, m.version)
        if key in seen:
            msg = f"duplicate skill manifest for {m.skill_id}@{m.version}"
            raise RegistryLoadError(msg)
        seen.add(key)
        manifests.append(m)
    return manifests


def sort_manifests_by_key(manifests: list[SkillManifest]) -> list[SkillManifest]:
    """Stable ordering: skill_id, then semver version."""
    return sorted(
        manifests,
        key=lambda m: (m.skill_id, Version(m.version)),
    )
