"""Skill registry loading and resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from syndicateclaw.runtime.errors import (
    ManifestValidationError,
    RegistryLoadError,
    UnknownSkillError,
)
from syndicateclaw.runtime.registry import SkillRegistry, load_manifest_file

FIXTURES = Path(__file__).parent / "fixtures"
SKILLS_MIN = FIXTURES / "skills_min"
SKILLS = FIXTURES / "skills"


def test_load_valid_manifest() -> None:
    m = load_manifest_file(SKILLS_MIN / "echo.yaml")
    assert m.skill_id == "echo"
    assert m.version == "1.0.0"


def test_registry_from_directory() -> None:
    reg = SkillRegistry.from_directory(SKILLS_MIN)
    m = reg.get("echo")
    assert m.skill_id == "echo"


def test_registry_unknown_skill() -> None:
    reg = SkillRegistry.from_directory(SKILLS_MIN)
    with pytest.raises(UnknownSkillError):
        reg.get("missing")


def test_registry_latest_version() -> None:
    reg = SkillRegistry.from_directory(SKILLS_MIN)
    assert reg.get("echo", version=None).version == "1.0.0"


def test_duplicate_manifest_rejected(tmp_path: Path) -> None:
    (tmp_path / "a.yaml").write_text(
        (SKILLS_MIN / "echo.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (tmp_path / "b.yaml").write_text(
        (SKILLS_MIN / "echo.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    with pytest.raises(RegistryLoadError, match="duplicate"):
        SkillRegistry.from_directory(tmp_path)


def test_invalid_manifest(tmp_path: Path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text("skill_id: '!!!INVALID!!!'\nversion: '1.0.0'\n", encoding="utf-8")
    with pytest.raises(ManifestValidationError):
        load_manifest_file(p)
