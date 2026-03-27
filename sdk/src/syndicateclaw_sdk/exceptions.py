"""SDK exception types."""

from __future__ import annotations


class SyndicateClawError(Exception):
    """Base class for SDK errors."""


class WorkflowNotFoundError(SyndicateClawError):
    pass


class ToolDeniedError(SyndicateClawError):
    pass


class ApprovalRequiredError(SyndicateClawError):
    pass


class RateLimitError(SyndicateClawError):
    pass


class AuthenticationError(SyndicateClawError):
    pass


class QuotaExceededError(SyndicateClawError):
    pass


class IncompatibleServerError(SyndicateClawError):
    def __init__(self, *, required: str, actual: str) -> None:
        super().__init__(f"Server {actual!r} is older than required {required!r}")
        self.required = required
        self.actual = actual


class BuildValidationError(SyndicateClawError):
    pass
