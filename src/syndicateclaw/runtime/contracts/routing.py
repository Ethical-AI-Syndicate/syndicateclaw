"""Routing decision contract (§12.3)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from syndicateclaw.runtime.contracts.common import RoutingStatus


class SkillCandidate(BaseModel):
    model_config = {"extra": "forbid"}

    skill_id: str
    version: str
    score: float
    reason: list[str] = Field(default_factory=list)


class SelectedSkill(BaseModel):
    model_config = {"extra": "forbid"}

    skill_id: str
    version: str


class RoutingDecision(BaseModel):
    model_config = {"extra": "forbid"}

    task_id: str
    selected_skill: SelectedSkill | None = None
    candidates: list[SkillCandidate] = Field(default_factory=list)
    routing_status: RoutingStatus
    policy_notes: list[str] = Field(default_factory=list)
    timestamp: str
