"""Router normalization, substring brittleness, and hard non-triggers."""

from __future__ import annotations

from pathlib import Path

from syndicateclaw.runtime.contracts.common import RequesterType, RoutingStatus, TriggerType
from syndicateclaw.runtime.contracts.skill_manifest import IntentTrigger
from syndicateclaw.runtime.contracts.task_context import Requester, TaskContext
from syndicateclaw.runtime.registry import SkillRegistry
from syndicateclaw.runtime.router import SkillRouter, normalize_goal
from syndicateclaw.runtime.router.scoring import goal_matches_non_trigger, trigger_match_score

FIXTURES = Path(__file__).parent / "fixtures"
SKILLS_MIN = FIXTURES / "skills_min"


def test_normalize_goal_case_and_unicode_nfc() -> None:
    g = normalize_goal("  ECHO caf\u00e9 ")
    assert g == "echo café"
    assert normalize_goal("caf\u0065\u0301") == normalize_goal("café")


def test_non_trigger_is_hard_veto_not_penalty() -> None:
    nt = [IntentTrigger(type=TriggerType.INTENT, match=["forbidden"])]
    assert goal_matches_non_trigger("prefix forbidden suffix", nt) is True
    unrelated = [IntentTrigger(type=TriggerType.INTENT, match=["nomatchphrase"])]
    assert trigger_match_score("prefix forbidden suffix", unrelated) == 0


def test_substring_false_positive_documented() -> None:
    """'echo' matches inside 'echolocation' — Phase 1 accepts this brittleness."""

    reg = SkillRegistry.from_directory(SKILLS_MIN)
    router = SkillRouter(reg)
    task = TaskContext(
        task_id="t1",
        requester=Requester(type=RequesterType.USER, id="u1"),
        goal="echolocation study",
        timestamp="2025-03-24T12:00:00Z",
    )
    decision = router.route_task(task, timestamp="2025-03-24T12:00:01Z")
    assert decision.routing_status == RoutingStatus.SELECTED
    assert decision.selected_skill is not None
