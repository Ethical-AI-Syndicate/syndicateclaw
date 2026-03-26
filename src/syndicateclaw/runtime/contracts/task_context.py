"""Task context contract (§12.1)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from syndicateclaw.runtime.contracts.common import ApprovalMode, RequesterType


class Requester(BaseModel):
    model_config = {"extra": "forbid"}

    type: RequesterType
    id: str = Field(min_length=1)


class TaskConstraints(BaseModel):
    model_config = {"extra": "forbid"}

    time_limit_ms: int | None = Field(default=None, ge=1)
    cost_limit: float | None = None
    allowed_data_scopes: list[str] = Field(default_factory=list)
    approval_mode: ApprovalMode = ApprovalMode.AUTO


class TaskContextPayload(BaseModel):
    model_config = {"extra": "forbid"}

    session_id: str | None = None
    case_id: str | None = None
    tenant_id: str | None = None
    prior_execution_ids: list[str] = Field(default_factory=list)


class TaskContext(BaseModel):
    """Normalized task envelope passed to the router and planner."""

    model_config = {"extra": "forbid"}

    task_id: str = Field(min_length=1)
    requester: Requester
    goal: str = Field(min_length=1)
    inputs: dict[str, Any] = Field(default_factory=dict)
    constraints: TaskConstraints = Field(default_factory=TaskConstraints)
    context: TaskContextPayload = Field(default_factory=TaskContextPayload)
    requested_capabilities: list[str] = Field(default_factory=list)
    timestamp: str = Field(
        ...,
        description="RFC3339 timestamp when the task was recorded",
    )
