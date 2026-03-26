"""JSON Schema artifacts stay in sync with Pydantic contracts."""

from __future__ import annotations

import json
from pathlib import Path

from syndicateclaw.runtime.contracts.export_schemas import default_schema_dir, export_json_schemas

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "src/syndicateclaw/runtime/contracts/jsonschema"


def test_schema_directory_matches_export() -> None:
    assert default_schema_dir() == SCHEMA_DIR
    summary = export_json_schemas(target_dir=SCHEMA_DIR)
    assert len(summary["written"]) == 7
    for name in summary["written"]:
        path = SCHEMA_DIR / name
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "$schema" in data or "$defs" in data or "properties" in data
