"""Map inference domain exceptions to HTTP responses (buffered chat/embedding + stream preflight).

Idempotency replay applies only to buffered ``infer_chat`` / ``infer_embedding``; streaming
intentionally has no idempotency in Phase 1 — do not add it without a first-class streaming
session model.
"""

from __future__ import annotations

from fastapi import HTTPException
from pydantic import ValidationError

from syndicateclaw.inference.errors import (
    IdempotencyConflictError,
    IdempotencyInProgressError,
    IdempotencyTerminalKeyError,
    InferenceApprovalRequiredError,
    InferenceDeniedError,
    InferenceError,
    InferenceExecutionError,
    InferenceRoutingError,
    InferenceValidationError,
)
from syndicateclaw.inference.types import ErrorCategory, RoutingFailureReason


def inference_error_to_http(exc: BaseException) -> HTTPException:
    """Return an ``HTTPException`` for a raised inference error (never raises)."""
    if isinstance(exc, ValidationError):
        return HTTPException(status_code=422, detail=exc.errors())

    if not isinstance(exc, InferenceError):
        return HTTPException(status_code=502, detail=str(exc))

    if isinstance(
        exc,
        IdempotencyConflictError | IdempotencyInProgressError | IdempotencyTerminalKeyError,
    ):
        return HTTPException(status_code=409, detail=str(exc))

    if isinstance(exc, InferenceApprovalRequiredError):
        return HTTPException(status_code=409, detail=str(exc))

    if isinstance(exc, InferenceDeniedError):
        return HTTPException(status_code=403, detail=str(exc))

    if isinstance(exc, InferenceValidationError):
        return HTTPException(status_code=422, detail=str(exc))

    if isinstance(exc, InferenceRoutingError):
        return _routing_to_http(exc)

    if isinstance(exc, InferenceExecutionError):
        return _execution_to_http(exc)

    cat = exc.category
    if cat == ErrorCategory.VALIDATION:
        return HTTPException(status_code=422, detail=str(exc))
    if cat == ErrorCategory.POLICY:
        return HTTPException(status_code=403, detail=str(exc))
    if cat in (
        ErrorCategory.TIMEOUT,
        ErrorCategory.PROVIDER,
        ErrorCategory.TRANSPORT,
    ):
        return HTTPException(status_code=503, detail=str(exc))
    return HTTPException(status_code=502, detail=str(exc))


def _routing_to_http(exc: InferenceRoutingError) -> HTTPException:
    fr = exc.failure_reason
    if fr == RoutingFailureReason.POLICY_DENIED:
        return HTTPException(status_code=403, detail=str(exc))
    if fr == RoutingFailureReason.SENSITIVITY_BLOCKED:
        return HTTPException(status_code=403, detail=str(exc))
    if fr == RoutingFailureReason.PIN_MISMATCH:
        return HTTPException(status_code=400, detail=str(exc))
    if fr in (
        RoutingFailureReason.NO_CANDIDATES,
        RoutingFailureReason.NO_MODELS,
        RoutingFailureReason.NO_PROVIDER_MATCH,
        RoutingFailureReason.CIRCUIT_OPEN,
        RoutingFailureReason.HEALTH_UNAVAILABLE,
    ):
        return HTTPException(status_code=503, detail=str(exc))
    return HTTPException(status_code=503, detail=str(exc))


def _execution_to_http(exc: InferenceExecutionError) -> HTTPException:
    cat = exc.category
    if cat == ErrorCategory.VALIDATION:
        return HTTPException(status_code=422, detail=str(exc))
    if cat == ErrorCategory.POLICY:
        return HTTPException(status_code=403, detail=str(exc))
    if cat == ErrorCategory.TIMEOUT:
        return HTTPException(status_code=503, detail=str(exc))
    if cat in (ErrorCategory.PROVIDER, ErrorCategory.TRANSPORT):
        return HTTPException(status_code=503, detail=str(exc))
    return HTTPException(status_code=503, detail=str(exc))
