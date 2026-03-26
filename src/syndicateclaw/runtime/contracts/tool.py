"""Tool request/response contracts (§12.5, §12.6)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from syndicateclaw.runtime.contracts.common import ToolInvocationStatus


class ToolValidation(BaseModel):
    model_config = {"extra": "forbid"}

    schema_valid: bool = False
    safety_valid: bool = False


class ToolRequest(BaseModel):
    model_config = {"extra": "forbid"}

    execution_id: str
    skill_id: str
    tool_name: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)
    requested_scope: str | None = None
    idempotency_key: str | None = None
    side_effect_expected: bool = False


class ToolResponse(BaseModel):
    model_config = {"extra": "forbid"}

    tool_name: str
    status: ToolInvocationStatus
    normalized_output: dict[str, Any] = Field(default_factory=dict)
    raw_reference: str | None = None
    validation: ToolValidation = Field(default_factory=ToolValidation)
    errors: list[str] = Field(default_factory=list)
