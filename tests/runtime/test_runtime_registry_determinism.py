"""Registry ordering, semver, and environment-stable behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

from syndicateclaw.runtime.contracts.skill_manifest import SkillManifest
from syndicateclaw.runtime.errors import ManifestValidationError
from syndicateclaw.runtime.registry import SkillRegistry, load_manifest_file

FIXTURES = Path(__file__).parent / "fixtures"
SKILLS_MIN = FIXTURES / "skills_min"


def test_latest_version_uses_packaging_semver_not_file_order(tmp_path: Path) -> None:
    (tmp_path / "v1.yaml").write_text(
        """
skill_id: semver_skill
version: "1.0.0"
description: v1
triggers:
  - type: intent
    match: [x]
non_triggers: []
risk_level: low
determinism_target: high
allowed_tools: []
denied_tools: []
memory_access: {read: [], write: [], persistent: false}
input_schema: {type: object, additionalProperties: true}
output_schema: {type: object, additionalProperties: true}
failure_modes: []
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "v2.yaml").write_text(
        (tmp_path / "v1.yaml").read_text(encoding="utf-8").replace("1.0.0", "2.0.0"),
        encoding="utf-8",
    )
    reg = SkillRegistry.from_directory(tmp_path)
    assert reg.get("semver_skill").version == "2.0.0"


def test_prerelease_ordering_is_explicit_not_accidental() -> None:
    from packaging.version import Version

    assert Version("2.0.0") > Version("2.0.0a1")


def test_manifest_json_roundtrip_matches_yaml_loaded_model() -> None:
    y = load_manifest_file(SKILLS_MIN / "echo.yaml")
    roundtrip = SkillManifest.model_validate_json(y.model_dump_json())
    assert roundtrip == y
    assert load_manifest_file(SKILLS_MIN / "echo.json").skill_id == "echo_json"


def test_tool_policy_deny_all_invalid_at_load(tmp_path: Path) -> None:
    text = (SKILLS_MIN / "echo.yaml").read_text(encoding="utf-8")
    bad = text.replace(
        "allowed_tools: []",
        "tool_policy: deny_all\nallowed_tools: [oops]",
    )
    p = tmp_path / "bad.yaml"
    p.write_text(bad, encoding="utf-8")
    with pytest.raises(ManifestValidationError, match="deny_all"):
        load_manifest_file(p)
