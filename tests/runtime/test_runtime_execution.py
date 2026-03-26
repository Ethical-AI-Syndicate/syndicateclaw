"""Single-skill execution and audit."""

from __future__ import annotations

from pathlib import Path

import pytest

from syndicateclaw.runtime.audit import FailingAuditSink, InMemoryAuditSink
from syndicateclaw.runtime.contracts.common import ResultStatus, ToolPolicy
from syndicateclaw.runtime.contracts.execution import ExecutionRequest, SkillRef
from syndicateclaw.runtime.errors import AuditSinkError
from syndicateclaw.runtime.execution import ExecutionEngine
from syndicateclaw.runtime.registry import SkillRegistry

FIXTURES = Path(__file__).parent / "fixtures"
SKILLS_MIN = FIXTURES / "skills_min"


def test_execute_success_emits_audit() -> None:
    reg = SkillRegistry.from_directory(SKILLS_MIN)
    manifest = reg.get("echo")
    sink = InMemoryAuditSink()
    engine = ExecutionEngine(audit_sink=sink)

    def handler(
        payload: dict[str, object],
        *,
        manifest,
        tool_invoker,
    ) -> dict[str, object]:
        return {"message": payload["message"]}

    req = ExecutionRequest(
        execution_id="exec_1",
        task_id="task_1",
        skill=SkillRef(skill_id="echo", version="1.0.0"),
        input_payload={"message": "hi"},
    )
    record = engine.execute_skill(
        req,
        manifest,
        handler,
        start_time="2025-03-24T12:00:00Z",
        end_time="2025-03-24T12:00:01Z",
        trigger_reason="test",
    )
    assert record.result_status == ResultStatus.SUCCESS
    assert record.output == {"message": "hi"}
    assert record.manifest_tool_policy == "explicit_allowlist"
    assert any("explicit_allowlist_empty_means_deny_all" in d for d in record.decisions)
    assert len(sink.records) == 1
    assert sink.records[0].execution_id == "exec_1"


def test_execute_missing_handler_fail_closed_record() -> None:
    reg = SkillRegistry.from_directory(SKILLS_MIN)
    manifest = reg.get("echo")
    sink = InMemoryAuditSink()
    engine = ExecutionEngine(audit_sink=sink)
    req = ExecutionRequest(
        execution_id="exec_2",
        task_id="task_1",
        skill=SkillRef(skill_id="echo", version="1.0.0"),
        input_payload={"message": "hi"},
    )
    record = engine.execute_skill(
        req,
        manifest,
        None,
        start_time="2025-03-24T12:00:00Z",
        end_time="2025-03-24T12:00:01Z",
        trigger_reason="test",
    )
    assert record.result_status == ResultStatus.FAILED
    assert record.error_code == "SkillHandlerMissingError"
    assert len(sink.records) == 1


def test_execute_invalid_input_json_schema() -> None:
    reg = SkillRegistry.from_directory(SKILLS_MIN)
    manifest = reg.get("echo")
    sink = InMemoryAuditSink()
    engine = ExecutionEngine(audit_sink=sink)
    req = ExecutionRequest(
        execution_id="exec_3",
        task_id="task_1",
        skill=SkillRef(skill_id="echo", version="1.0.0"),
        input_payload={},
    )
    record = engine.execute_skill(
        req,
        manifest,
        lambda payload, **_: {"message": "x"},
        start_time="2025-03-24T12:00:00Z",
        end_time="2025-03-24T12:00:01Z",
        trigger_reason="test",
    )
    assert record.result_status == ResultStatus.FAILED
    assert record.error_code == "ExecutionValidationError"
    assert len(sink.records) == 1


def test_execute_skill_ref_mismatch() -> None:
    reg = SkillRegistry.from_directory(SKILLS_MIN)
    manifest = reg.get("echo")
    sink = InMemoryAuditSink()
    engine = ExecutionEngine(audit_sink=sink)
    req = ExecutionRequest(
        execution_id="exec_4",
        task_id="task_1",
        skill=SkillRef(skill_id="other", version="1.0.0"),
        input_payload={"message": "hi"},
    )
    record = engine.execute_skill(
        req,
        manifest,
        lambda payload, **_: {"message": payload["message"]},
        start_time="2025-03-24T12:00:00Z",
        end_time="2025-03-24T12:00:01Z",
        trigger_reason="test",
    )
    assert record.result_status == ResultStatus.FAILED
    assert record.error_code == "SKILL_REF_MISMATCH"


def test_audit_sink_failure_is_fail_closed() -> None:
    reg = SkillRegistry.from_directory(SKILLS_MIN)
    manifest = reg.get("echo")
    engine = ExecutionEngine(audit_sink=FailingAuditSink())
    req = ExecutionRequest(
        execution_id="exec_5",
        task_id="task_1",
        skill=SkillRef(skill_id="echo", version="1.0.0"),
        input_payload={"message": "hi"},
    )
    with pytest.raises(AuditSinkError):
        engine.execute_skill(
            req,
            manifest,
            lambda payload, **_: {"message": payload["message"]},
            start_time="2025-03-24T12:00:00Z",
            end_time="2025-03-24T12:00:01Z",
            trigger_reason="test",
        )


def test_tool_invoker_deny_by_default() -> None:
    reg = SkillRegistry.from_directory(SKILLS_MIN)
    manifest = reg.get("echo").model_copy(update={"allowed_tools": []})
    sink = InMemoryAuditSink()
    engine = ExecutionEngine(audit_sink=sink)

    def bad(
        payload: dict[str, object],
        *,
        manifest,
        tool_invoker,
    ) -> dict[str, object]:
        tool_invoker.invoke(
            tool_name="nope",
            purpose="should fail",
            arguments={},
        )
        return {"message": "x"}

    req = ExecutionRequest(
        execution_id="exec_6",
        task_id="task_1",
        skill=SkillRef(skill_id="echo", version="1.0.0"),
        input_payload={"message": "hi"},
    )
    record = engine.execute_skill(
        req,
        manifest,
        bad,
        start_time="2025-03-24T12:00:00Z",
        end_time="2025-03-24T12:00:01Z",
        trigger_reason="test",
    )
    assert record.result_status == ResultStatus.FAILED
    assert record.error_code == "ToolNotAuthorizedError"


def test_tool_policy_deny_all_rejects_invocation_before_allowlist() -> None:
    reg = SkillRegistry.from_directory(SKILLS_MIN)
    manifest = reg.get("echo").model_copy(
        update={"tool_policy": ToolPolicy.DENY_ALL, "allowed_tools": []},
    )
    sink = InMemoryAuditSink()
    engine = ExecutionEngine(audit_sink=sink)

    def tries_tool(
        payload: dict[str, object],
        *,
        manifest,
        tool_invoker,
    ) -> dict[str, object]:
        tool_invoker.invoke(
            tool_name="anything",
            purpose="blocked",
            arguments={},
        )
        return {"message": "n"}

    req = ExecutionRequest(
        execution_id="exec_7",
        task_id="task_1",
        skill=SkillRef(skill_id="echo", version="1.0.0"),
        input_payload={"message": "hi"},
    )
    record = engine.execute_skill(
        req,
        manifest,
        tries_tool,
        start_time="2025-03-24T12:00:00Z",
        end_time="2025-03-24T12:00:01Z",
        trigger_reason="test",
    )
    assert record.result_status == ResultStatus.FAILED
    assert record.manifest_tool_policy == "deny_all"
    assert "deny_all" in (record.error_message or "")
