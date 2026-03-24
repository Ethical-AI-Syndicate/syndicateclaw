"""Inference domain errors — structured for routing, policy, and audit."""

from __future__ import annotations

from syndicateclaw.inference.types import ErrorCategory, RoutingFailureReason


class InferenceError(Exception):
    """Base for inference errors."""

    def __init__(
        self,
        message: str,
        *,
        category: ErrorCategory = ErrorCategory.UNKNOWN,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.retryable = retryable


class InferenceValidationError(InferenceError):
    def __init__(self, message: str) -> None:
        super().__init__(message, category=ErrorCategory.VALIDATION, retryable=False)


class IdempotencyConflictError(InferenceError):
    def __init__(self, message: str) -> None:
        super().__init__(message, category=ErrorCategory.VALIDATION, retryable=False)


class InferenceDeniedError(InferenceError):
    def __init__(self, message: str) -> None:
        super().__init__(message, category=ErrorCategory.POLICY, retryable=False)


class InferenceRoutingError(InferenceError):
    def __init__(
        self,
        message: str,
        *,
        failure_reason: RoutingFailureReason,
    ) -> None:
        super().__init__(message, category=ErrorCategory.VALIDATION, retryable=False)
        self.failure_reason = failure_reason


class InferenceExecutionError(InferenceError):
    """Execution failed after routing (includes exhausted fallbacks)."""

    def __init__(
        self,
        message: str,
        *,
        category: ErrorCategory = ErrorCategory.UNKNOWN,
        retryable: bool = False,
    ) -> None:
        super().__init__(message, category=category, retryable=retryable)
