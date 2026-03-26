"""Manifest I/O schemas use the same validation path as execution."""

from __future__ import annotations

from pathlib import Path

from syndicateclaw.runtime.execution.validation import validate_payload_against_schema
from syndicateclaw.runtime.registry import load_manifest_file

FIXTURES = Path(__file__).parent / "fixtures" / "skills_min"


def test_manifest_schemas_match_execution_validator() -> None:
    manifest = load_manifest_file(FIXTURES / "echo.yaml")
    validate_payload_against_schema(
        {"message": "ok"},
        manifest.input_schema,
        label="parity",
    )
    validate_payload_against_schema(
        {"message": "out"},
        manifest.output_schema,
        label="parity",
    )
