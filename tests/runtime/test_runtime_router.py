"""Deterministic skill routing."""

from __future__ import annotations

from pathlib import Path

from syndicateclaw.runtime.contracts.common import RequesterType, RoutingStatus
from syndicateclaw.runtime.contracts.task_context import Requester, TaskContext
from syndicateclaw.runtime.registry import SkillRegistry
from syndicateclaw.runtime.router import SkillRouter

FIXTURES = Path(__file__).parent / "fixtures"
SKILLS_MIN = FIXTURES / "skills_min"
SKILLS = FIXTURES / "skills"


def _task(goal: str) -> TaskContext:
    return TaskContext(
        task_id="t1",
        requester=Requester(type=RequesterType.USER, id="u1"),
        goal=goal,
        timestamp="2025-03-24T12:00:00Z",
    )


def test_route_selected() -> None:
    reg = SkillRegistry.from_directory(SKILLS_MIN)
    router = SkillRouter(reg)
    task = _task("please echo the payload")
    decision = router.route_task(task, timestamp="2025-03-24T12:00:01Z")
    assert decision.routing_status == RoutingStatus.SELECTED
    assert decision.selected_skill is not None
    assert decision.selected_skill.skill_id == "echo"


def test_route_uncertain_tie() -> None:
    reg = SkillRegistry.from_directory(SKILLS)
    router = SkillRouter(reg)
    task = _task("echo this")
    decision = router.route_task(task, timestamp="2025-03-24T12:00:01Z")
    assert decision.routing_status == RoutingStatus.UNCERTAIN
    assert decision.selected_skill is None


def test_route_blocked_no_match() -> None:
    reg = SkillRegistry.from_directory(SKILLS_MIN)
    router = SkillRouter(reg)
    task = _task("nothing relevant here")
    decision = router.route_task(task, timestamp="2025-03-24T12:00:01Z")
    assert decision.routing_status == RoutingStatus.BLOCKED


def test_non_trigger_excludes_skill() -> None:
    reg = SkillRegistry.from_directory(SKILLS)
    router = SkillRouter(reg)
    task = _task("need legal advice even with a sample in it")
    decision = router.route_task(task, timestamp="2025-03-24T12:00:01Z")
    assert decision.selected_skill is None or decision.selected_skill.skill_id != "blocked_sample"


def test_trigger_matches_blocked_sample_when_allowed() -> None:
    reg = SkillRegistry.from_directory(SKILLS)
    router = SkillRouter(reg)
    task = _task("draft a sample paragraph")
    decision = router.route_task(task, timestamp="2025-03-24T12:00:01Z")
    assert decision.routing_status == RoutingStatus.SELECTED
    assert decision.selected_skill is not None
    assert decision.selected_skill.skill_id == "blocked_sample"
