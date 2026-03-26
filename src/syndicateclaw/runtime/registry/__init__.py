"""Filesystem-backed skill registry."""

from __future__ import annotations

from syndicateclaw.runtime.registry.loader import (
    iter_manifest_paths,
    load_manifest_file,
    load_manifests_from_directory,
)
from syndicateclaw.runtime.registry.registry import SkillRegistry

__all__ = [
    "SkillRegistry",
    "iter_manifest_paths",
    "load_manifest_file",
    "load_manifests_from_directory",
]
