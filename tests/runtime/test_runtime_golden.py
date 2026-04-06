"""Golden execution records — semantic stability for replay."""

from __future__ import annotations

import json
from pathlib import Path

from syndicateclaw.runtime.audit import InMemoryAuditSink
from syndicateclaw.runtime.contracts.execution import ExecutionRequest, SkillRef
from syndicateclaw.runtime.execution import ExecutionEngine
from syndicateclaw.runtime.registry import SkillRegistry
from syndicateclaw.runtime.router import SkillRouter

FIXTURES = Path(__file__).parent / "fixtures"
SKILLS_MIN = FIXTURES / "skills_min"
GOLDEN = FIXTURES / "golden"


def test_golden_success_execution_record_shape() -> None:
    reg = SkillRegistry.from_directory(SKILLS_MIN)
    manifest = reg.get("echo")
    sink = InMemoryAuditSink()
    engine = ExecutionEngine(audit_sink=sink)

    def handler(payload: dict[str, object], **kwargs: object) -> dict[str, object]:
        return {"message": payload["message"]}

    req = ExecutionRequest(
        execution_id="golden_exec",
        task_id="golden_task",
        skill=SkillRef(skill_id="echo", version="1.0.0"),
        input_payload={"message": "golden"},
    )
    record = engine.execute_skill(
        req,
        manifest,
        handler,
        start_time="2025-03-24T12:00:00Z",
        end_time="2025-03-24T12:00:01Z",
        trigger_reason="golden",
    )
    path = GOLDEN / "execution_record_success.json"
    expected = json.loads(path.read_text(encoding="utf-8"))
    actual = json.loads(record.model_dump_json())
    assert actual == expected


def test_router_replay_stable() -> None:
    from syndicateclaw.runtime.contracts.common import RequesterType
    from syndicateclaw.runtime.contracts.task_context import Requester, TaskContext

    reg = SkillRegistry.from_directory(SKILLS_MIN)
    router = SkillRouter(reg)
    task = TaskContext(
        task_id="t1",
        requester=Requester(type=RequesterType.USER, id="u1"),
        goal="echo the golden path",
        timestamp="2025-03-24T12:00:00Z",
    )
    path = GOLDEN / "routing_decision_echo.json"
    expected = json.loads(path.read_text(encoding="utf-8"))
    d = router.route_task(task, timestamp="2025-03-24T12:00:01Z")
    actual = json.loads(d.model_dump_json())
    assert actual == expected
