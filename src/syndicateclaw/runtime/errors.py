"""Runtime control plane errors — fail-closed semantics."""

from __future__ import annotations


class RuntimeControlError(Exception):
    """Base class for runtime control plane failures."""


class ManifestValidationError(RuntimeControlError):
    """Skill manifest failed schema or semantic validation."""


class RegistryLoadError(RuntimeControlError):
    """Registry could not load manifests from disk."""


class UnknownSkillError(RuntimeControlError):
    """Requested skill id/version is not registered."""


class RoutingUncertainError(RuntimeControlError):
    """Router could not pick a single skill deterministically."""


class RoutingBlockedError(RuntimeControlError):
    """Router excluded all candidates (non-triggers, policy, etc.)."""


class AuditSinkError(RuntimeControlError):
    """Audit record could not be persisted (fail closed)."""


class ExecutionValidationError(RuntimeControlError):
    """Input or output failed validation against the skill contract."""


class ToolNotAuthorizedError(RuntimeControlError):
    """Tool call not allowed for this skill (deny-by-default)."""


class SkillHandlerMissingError(RuntimeControlError):
    """No handler registered for the resolved skill implementation."""
