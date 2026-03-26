"""Handler surface area — tools only via ToolInvoker in the runtime contract."""

from __future__ import annotations

from pathlib import Path

from syndicateclaw.runtime.audit import InMemoryAuditSink
from syndicateclaw.runtime.contracts.common import ToolPolicy
from syndicateclaw.runtime.contracts.execution import ExecutionRequest, SkillRef
from syndicateclaw.runtime.execution import ExecutionEngine
from syndicateclaw.runtime.registry import SkillRegistry

FIXTURES = Path(__file__).parent / "fixtures" / "skills_min"


def test_handler_receives_only_declared_arguments() -> None:
    """Runtime passes payload + manifest + tool_invoker — no tool registry on the handler."""

    reg = SkillRegistry.from_directory(FIXTURES)
    manifest = reg.get("echo")
    manifest = manifest.model_copy(
        update={
            "allowed_tools": ["approved"],
            "tool_policy": ToolPolicy.EXPLICIT_ALLOWLIST,
        },
    )
    sink = InMemoryAuditSink()
    engine = ExecutionEngine(audit_sink=sink)

    seen: dict[str, object] = {}

    def handler(payload: dict[str, object], *, manifest, tool_invoker) -> dict[str, object]:
        seen["has_invoker"] = tool_invoker is not None
        seen["manifest_id"] = manifest.skill_id
        out = tool_invoker.invoke(
            tool_name="approved",
            purpose="test",
            arguments={},
        )
        return {"message": str(out)}

    req = ExecutionRequest(
        execution_id="hb1",
        task_id="t1",
        skill=SkillRef(skill_id="echo", version="1.0.0"),
        input_payload={"message": "x"},
    )
    engine.execute_skill(
        req,
        manifest,
        handler,
        start_time="2025-03-24T12:00:00Z",
        end_time="2025-03-24T12:00:01Z",
        trigger_reason="boundary",
    )
    assert seen.get("has_invoker") is True
    assert seen.get("manifest_id") == "echo"
    assert len(sink.records[0].tools_invoked) == 1
