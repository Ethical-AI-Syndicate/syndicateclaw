"""Shared enums and primitives for runtime contracts."""

from __future__ import annotations

from enum import Enum


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class DeterminismTarget(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RoutingStatus(str, Enum):
    SELECTED = "selected"
    UNCERTAIN = "uncertain"
    BLOCKED = "blocked"


class ResultStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    FAILED = "failed"


class ExecutionMode(str, Enum):
    SINGLE_STEP = "single_step"
    PLANNED_STEP = "planned_step"


class ToolInvocationStatus(str, Enum):
    SUCCESS = "success"
    RETRYABLE_FAILURE = "retryable_failure"
    TERMINAL_FAILURE = "terminal_failure"


class RequesterType(str, Enum):
    USER = "user"
    SYSTEM = "system"
    SERVICE = "service"


class ApprovalMode(str, Enum):
    AUTO = "auto"
    HUMAN_REQUIRED = "human_required"
    POLICY_DRIVEN = "policy_driven"


class TriggerType(str, Enum):
    INTENT = "intent"


class ToolPolicy(str, Enum):
    """How tool authorization is interpreted for audit and enforcement."""

    EXPLICIT_ALLOWLIST = "explicit_allowlist"
    DENY_ALL = "deny_all"
