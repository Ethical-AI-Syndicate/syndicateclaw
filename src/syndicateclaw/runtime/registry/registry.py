"""In-memory skill registry — built from validated filesystem manifests."""

from __future__ import annotations

from pathlib import Path

from packaging.version import InvalidVersion, Version

from syndicateclaw.runtime.contracts.skill_manifest import SkillManifest
from syndicateclaw.runtime.errors import UnknownSkillError
from syndicateclaw.runtime.registry.loader import (
    load_manifests_from_directory,
    sort_manifests_by_key,
)


class SkillRegistry:
    """Version-aware registry. No mutable global state — construct per load.

    Effective registry content depends only on the set of manifests, not on filesystem
    iteration order: duplicates are rejected, and internal indexes are built from sorted
    manifests (``skill_id``, then ``packaging.version.Version``).
    """

    def __init__(self, manifests: list[SkillManifest]) -> None:
        ordered = sort_manifests_by_key(manifests)
        self._by_key: dict[tuple[str, str], SkillManifest] = {}
        self._ids: dict[str, list[SkillManifest]] = {}
        for m in ordered:
            self._by_key[(m.skill_id, m.version)] = m
            self._ids.setdefault(m.skill_id, []).append(m)

    @classmethod
    def from_directory(cls, directory: Path | str) -> SkillRegistry:
        path = Path(directory)
        manifests = load_manifests_from_directory(path)
        return cls(manifests)

    def get(self, skill_id: str, version: str | None = None) -> SkillManifest:
        """Resolve a skill. If version is None, pick highest per ``packaging.version.Version``.

        Prerelease and local segments participate in ordering (PEP 440 semantics via
        ``packaging``). Authors should treat version strings as canonical for a skill_id.
        """
        if version is not None:
            key = (skill_id, version)
            found = self._by_key.get(key)
            if found is None:
                raise UnknownSkillError(f"unknown skill {skill_id}@{version}")
            return found
        versions = self._ids.get(skill_id)
        if not versions:
            raise UnknownSkillError(f"unknown skill_id {skill_id}")
        return max(versions, key=lambda m: Version(m.version))

    def list_skills(
        self,
        *,
        include_deprecated: bool = False,
    ) -> list[SkillManifest]:
        out = list(self._by_key.values())
        if not include_deprecated:
            out = [m for m in out if not m.deprecated]
        return sort_manifests_by_key(out)

    def list_versions(self, skill_id: str) -> list[str]:
        ms = self._ids.get(skill_id, [])
        vers = [m.version for m in ms]
        try:
            return sorted(vers, key=lambda v: Version(v))
        except InvalidVersion:
            return sorted(vers)
