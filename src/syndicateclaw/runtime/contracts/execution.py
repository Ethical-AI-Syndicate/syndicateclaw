"""Execution request and record contracts (§12.4, §12.7)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from syndicateclaw.runtime.contracts.common import ExecutionMode, ResultStatus


class SkillRef(BaseModel):
    model_config = {"extra": "forbid"}

    skill_id: str
    version: str


class PlanContext(BaseModel):
    model_config = {"extra": "forbid"}

    plan_id: str | None = None
    step_id: str | None = None
    step_number: int | None = Field(default=None, ge=0)


class ExecutionLimits(BaseModel):
    model_config = {"extra": "forbid"}

    max_tool_calls: int = Field(default=5, ge=0)
    max_runtime_ms: int = Field(default=20_000, ge=1)
    max_memory_writes: int = Field(default=2, ge=0)


class ExecutionRequest(BaseModel):
    model_config = {"extra": "forbid"}

    execution_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    skill: SkillRef
    input_payload: dict[str, Any] = Field(default_factory=dict)
    execution_mode: ExecutionMode = ExecutionMode.SINGLE_STEP
    plan_context: PlanContext = Field(default_factory=PlanContext)
    limits: ExecutionLimits = Field(default_factory=ExecutionLimits)


class PolicyDecisionRef(BaseModel):
    model_config = {"extra": "forbid"}

    decision_type: str
    detail: str | None = None


class ExecutionRecord(BaseModel):
    """Structured audit record emitted for every execution attempt."""

    model_config = {"extra": "forbid"}

    execution_id: str
    task_id: str
    skill_id: str
    version: str
    manifest_tool_policy: str | None = None
    trigger_reason: str
    inputs_used: list[Any] = Field(default_factory=list)
    memory_reads: list[str] = Field(default_factory=list)
    memory_writes: list[str] = Field(default_factory=list)
    tools_invoked: list[dict[str, Any]] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    failures_detected: list[str] = Field(default_factory=list)
    policy_decisions: list[PolicyDecisionRef] = Field(default_factory=list)
    result_status: ResultStatus
    output: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    start_time: str
    end_time: str
