"""Skill manifest contract (§12.2) — filesystem source of truth."""

from __future__ import annotations

import re
from typing import Any

from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, Field, field_validator, model_validator

from syndicateclaw.runtime.contracts.common import (
    DeterminismTarget,
    RiskLevel,
    ToolPolicy,
    TriggerType,
)

_SKILL_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class IntentTrigger(BaseModel):
    model_config = {"extra": "forbid"}

    type: TriggerType
    match: list[str] = Field(min_length=1)


class MemoryAccess(BaseModel):
    model_config = {"extra": "forbid"}

    read: list[str] = Field(default_factory=list)
    write: list[str] = Field(default_factory=list)
    persistent: bool = False


class ApprovalRequirements(BaseModel):
    model_config = {"extra": "forbid"}

    tool_actions: list[str] = Field(default_factory=list)
    state_mutations: list[str] = Field(default_factory=list)


class SkillProvenance(BaseModel):
    model_config = {"extra": "forbid"}

    author: str | None = None
    source: str | None = None
    validation_status: str | None = None


class SkillManifest(BaseModel):
    """Authoritative skill definition loaded from disk."""

    model_config = {"extra": "forbid"}

    skill_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    description: str = Field(min_length=1)
    triggers: list[IntentTrigger] = Field(min_length=1)
    non_triggers: list[IntentTrigger] = Field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.MEDIUM
    determinism_target: DeterminismTarget = DeterminismTarget.MEDIUM
    tool_policy: ToolPolicy = ToolPolicy.EXPLICIT_ALLOWLIST
    allowed_tools: list[str] = Field(default_factory=list)
    denied_tools: list[str] = Field(default_factory=list)
    memory_access: MemoryAccess = Field(default_factory=MemoryAccess)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    failure_modes: list[dict[str, Any]] = Field(default_factory=list)
    approval_requirements: ApprovalRequirements = Field(default_factory=ApprovalRequirements)
    deprecated: bool = False
    provenance: SkillProvenance | None = None

    @field_validator("skill_id")
    @classmethod
    def validate_skill_id(cls, v: str) -> str:
        if not _SKILL_ID_RE.match(v):
            msg = "skill_id must match ^[a-z][a-z0-9_]*$"
            raise ValueError(msg)
        return v

    @field_validator("version")
    @classmethod
    def validate_semver(cls, v: str) -> str:
        try:
            Version(v)
        except InvalidVersion as e:
            msg = f"version must be valid semver: {v}"
            raise ValueError(msg) from e
        return v

    @model_validator(mode="after")
    def validate_tool_policy(self) -> SkillManifest:
        if self.tool_policy == ToolPolicy.DENY_ALL and self.allowed_tools:
            msg = "tool_policy=deny_all requires allowed_tools to be empty"
            raise ValueError(msg)
        return self
