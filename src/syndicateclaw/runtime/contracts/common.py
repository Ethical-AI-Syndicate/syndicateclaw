"""Shared enums and primitives for runtime contracts."""

from __future__ import annotations

from enum import StrEnum


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class DeterminismTarget(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RoutingStatus(StrEnum):
    SELECTED = "selected"
    UNCERTAIN = "uncertain"
    BLOCKED = "blocked"


class ResultStatus(StrEnum):
    SUCCESS = "success"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    FAILED = "failed"


class ExecutionMode(StrEnum):
    SINGLE_STEP = "single_step"
    PLANNED_STEP = "planned_step"


class ToolInvocationStatus(StrEnum):
    SUCCESS = "success"
    RETRYABLE_FAILURE = "retryable_failure"
    TERMINAL_FAILURE = "terminal_failure"


class RequesterType(StrEnum):
    USER = "user"
    SYSTEM = "system"
    SERVICE = "service"


class ApprovalMode(StrEnum):
    AUTO = "auto"
    HUMAN_REQUIRED = "human_required"
    POLICY_DRIVEN = "policy_driven"


class TriggerType(StrEnum):
    INTENT = "intent"


class ToolPolicy(StrEnum):
    """How tool authorization is interpreted for audit and enforcement."""

    EXPLICIT_ALLOWLIST = "explicit_allowlist"
    DENY_ALL = "deny_all"
