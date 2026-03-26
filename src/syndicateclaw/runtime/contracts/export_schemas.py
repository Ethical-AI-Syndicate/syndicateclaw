"""Export Pydantic models to JSON Schema files (checked into the repo)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from syndicateclaw.runtime.contracts.execution import ExecutionRecord, ExecutionRequest
from syndicateclaw.runtime.contracts.routing import RoutingDecision
from syndicateclaw.runtime.contracts.skill_manifest import SkillManifest
from syndicateclaw.runtime.contracts.task_context import TaskContext
from syndicateclaw.runtime.contracts.tool import ToolRequest, ToolResponse

_SCHEMA_TARGETS: list[tuple[str, type[BaseModel]]] = [
    ("task_context.schema.json", TaskContext),
    ("skill_manifest.schema.json", SkillManifest),
    ("routing_decision.schema.json", RoutingDecision),
    ("execution_request.schema.json", ExecutionRequest),
    ("execution_record.schema.json", ExecutionRecord),
    ("tool_request.schema.json", ToolRequest),
    ("tool_response.schema.json", ToolResponse),
]


def default_schema_dir() -> Path:
    return Path(__file__).resolve().parent / "jsonschema"


def export_json_schemas(*, target_dir: Path | None = None) -> dict[str, Any]:
    """Write JSON Schema files for all primary contracts. Returns a summary dict."""
    out = target_dir or default_schema_dir()
    out.mkdir(parents=True, exist_ok=True)
    summary: dict[str, Any] = {"written": [], "directory": str(out)}
    for filename, model in _SCHEMA_TARGETS:
        path = out / filename
        schema = model.model_json_schema(mode="validation")
        path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        summary["written"].append(filename)
    return summary


if __name__ == "__main__":
    summary = export_json_schemas()
    print(json.dumps(summary, indent=2))
