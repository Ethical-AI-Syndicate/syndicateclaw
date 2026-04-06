"""Deterministic skill router — ROUTING_UNCERTAIN when ties remain after tie-breakers."""

from __future__ import annotations

from syndicateclaw.runtime.contracts.common import RoutingStatus
from syndicateclaw.runtime.contracts.routing import RoutingDecision, SelectedSkill, SkillCandidate
from syndicateclaw.runtime.contracts.skill_manifest import SkillManifest
from syndicateclaw.runtime.contracts.task_context import TaskContext
from syndicateclaw.runtime.registry.registry import SkillRegistry
from syndicateclaw.runtime.router.scoring import (
    compare_candidates,
    goal_matches_non_trigger,
    normalize_goal,
    sort_key_for_manifest,
    trigger_match_score,
)


class SkillRouter:
    """Routes tasks to skills using registry metadata only."""

    def __init__(self, registry: SkillRegistry) -> None:
        self._registry = registry

    def route_task(self, task: TaskContext, *, timestamp: str) -> RoutingDecision:
        goal_norm = normalize_goal(task.goal)
        manifests = self._registry.list_skills(include_deprecated=False)
        candidates: list[tuple[SkillManifest, int, list[str]]] = []

        for m in manifests:
            reasons: list[str] = []
            if goal_matches_non_trigger(goal_norm, m.non_triggers):
                continue
            score = trigger_match_score(goal_norm, m.triggers)
            if score <= 0:
                continue
            reasons.append(f"intent match score={score}")
            reasons.append(f"risk={m.risk_level.value}")
            reasons.append(f"determinism_target={m.determinism_target.value}")
            candidates.append((m, score, reasons))

        if not candidates:
            return RoutingDecision(
                task_id=task.task_id,
                selected_skill=None,
                candidates=[],
                routing_status=RoutingStatus.BLOCKED,
                policy_notes=["no matching skill after trigger and non-trigger evaluation"],
                timestamp=timestamp,
            )

        # Find best; detect ambiguity on primary dimensions only.
        candidates.sort(
            key=lambda item: sort_key_for_manifest(item[0], item[1]),
        )
        scored = [
            SkillCandidate(
                skill_id=m.skill_id,
                version=m.version,
                score=float(score),
                reason=reasons,
            )
            for m, score, reasons in candidates
        ]
        best_m, best_score, _best_reasons = candidates[0]
        ambiguous = False
        if len(candidates) > 1:
            second_m, second_score, _ = candidates[1]
            if compare_candidates(best_m, second_m, score_a=best_score, score_b=second_score) == 0:
                ambiguous = True

        if ambiguous:
            return RoutingDecision(
                task_id=task.task_id,
                selected_skill=None,
                candidates=scored,
                routing_status=RoutingStatus.UNCERTAIN,
                policy_notes=["multiple skills tie on score, risk, and determinism"],
                timestamp=timestamp,
            )

        return RoutingDecision(
            task_id=task.task_id,
            selected_skill=SelectedSkill(skill_id=best_m.skill_id, version=best_m.version),
            candidates=scored,
            routing_status=RoutingStatus.SELECTED,
            policy_notes=[],
            timestamp=timestamp,
        )
