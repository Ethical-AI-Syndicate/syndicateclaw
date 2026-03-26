"""Routing decisions are deterministic for identical inputs."""

from __future__ import annotations

from pathlib import Path

from syndicateclaw.runtime.contracts.common import RequesterType
from syndicateclaw.runtime.contracts.task_context import Requester, TaskContext
from syndicateclaw.runtime.registry import SkillRegistry
from syndicateclaw.runtime.router import SkillRouter

FIXTURES = Path(__file__).parent / "fixtures" / "skills_min"


def test_route_task_is_deterministic() -> None:
    reg = SkillRegistry.from_directory(FIXTURES)
    router = SkillRouter(reg)
    task = TaskContext(
        task_id="t1",
        requester=Requester(type=RequesterType.USER, id="u1"),
        goal="echo the payload",
        timestamp="2025-03-24T12:00:00Z",
    )
    a = router.route_task(task, timestamp="2025-03-24T12:00:01Z")
    b = router.route_task(task, timestamp="2025-03-24T12:00:01Z")
    assert a.model_dump() == b.model_dump()
