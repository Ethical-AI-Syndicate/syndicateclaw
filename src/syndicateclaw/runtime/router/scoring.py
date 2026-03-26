"""Deterministic trigger scoring — no randomness, stable tie detection."""

from __future__ import annotations

import unicodedata

from syndicateclaw.runtime.contracts.common import DeterminismTarget, RiskLevel, TriggerType
from syndicateclaw.runtime.contracts.skill_manifest import IntentTrigger, SkillManifest


def normalize_goal(goal: str) -> str:
    """Stable normalization: NFC + lowercase + trim (Phase 1 substring router)."""

    return unicodedata.normalize("NFC", goal).lower().strip()


def _risk_rank(level: RiskLevel) -> int:
    return {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2}[level]


def _determinism_rank(level: DeterminismTarget) -> int:
    # Lower rank = better (more deterministic)
    return {DeterminismTarget.HIGH: 0, DeterminismTarget.MEDIUM: 1, DeterminismTarget.LOW: 2}[level]


def goal_matches_non_trigger(goal_norm: str, triggers: list[IntentTrigger]) -> bool:
    """Hard veto: if any non-trigger phrase matches, the skill is excluded (not a score penalty)."""
    for t in triggers:
        if t.type != TriggerType.INTENT:
            continue
        for phrase in t.match:
            p = phrase.lower().strip()
            if p and p in goal_norm:
                return True
    return False


def trigger_match_score(goal_norm: str, triggers: list[IntentTrigger]) -> int:
    """Sum of phrase lengths for matched intent phrases (once per phrase)."""
    total = 0
    for t in triggers:
        if t.type != TriggerType.INTENT:
            continue
        for phrase in t.match:
            p = phrase.lower().strip()
            if p and p in goal_norm:
                total += len(p)
    return total


def compare_candidates(a: SkillManifest, b: SkillManifest, *, score_a: int, score_b: int) -> int:
    """Return <0 if a wins, >0 if b wins, 0 if tie on routing dimensions."""
    if score_a != score_b:
        return score_b - score_a
    ra, rb = _risk_rank(a.risk_level), _risk_rank(b.risk_level)
    if ra != rb:
        return ra - rb
    da, db = _determinism_rank(a.determinism_target), _determinism_rank(b.determinism_target)
    if da != db:
        return da - db
    return 0


def sort_key_for_manifest(m: SkillManifest, score: int) -> tuple[int, int, int, str, str]:
    """Deterministic total ordering for reporting (not used for ambiguity)."""
    return (
        -score,
        _risk_rank(m.risk_level),
        _determinism_rank(m.determinism_target),
        m.skill_id,
        m.version,
    )
