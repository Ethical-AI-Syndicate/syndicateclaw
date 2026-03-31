"""Unit tests for api/inference_http.py and runtime/registry/registry.py."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

# ---------------------------------------------------------------------------
# api/inference_http.py — inference_error_to_http
# ---------------------------------------------------------------------------


def test_inference_error_to_http_validation_error() -> None:
    from syndicateclaw.api.inference_http import inference_error_to_http

    # Trigger a real ValidationError via pydantic
    try:
        from pydantic import BaseModel

        class M(BaseModel):
            x: int

        M(x="not-an-int")  # type: ignore[arg-type]
    except ValidationError as e:
        result = inference_error_to_http(e)
    assert result.status_code == 422


def test_inference_error_to_http_non_inference_error() -> None:
    from syndicateclaw.api.inference_http import inference_error_to_http

    result = inference_error_to_http(RuntimeError("boom"))
    assert result.status_code == 502


def test_inference_error_to_http_idempotency_conflict() -> None:
    from syndicateclaw.api.inference_http import inference_error_to_http
    from syndicateclaw.inference.errors import IdempotencyConflictError

    result = inference_error_to_http(IdempotencyConflictError("conflict"))
    assert result.status_code == 409


def test_inference_error_to_http_idempotency_in_progress() -> None:
    from syndicateclaw.api.inference_http import inference_error_to_http
    from syndicateclaw.inference.errors import IdempotencyInProgressError

    result = inference_error_to_http(IdempotencyInProgressError("in progress"))
    assert result.status_code == 409


def test_inference_error_to_http_approval_required() -> None:
    from syndicateclaw.api.inference_http import inference_error_to_http
    from syndicateclaw.inference.errors import InferenceApprovalRequiredError

    result = inference_error_to_http(InferenceApprovalRequiredError("approval"))
    assert result.status_code == 409


def test_inference_error_to_http_denied() -> None:
    from syndicateclaw.api.inference_http import inference_error_to_http
    from syndicateclaw.inference.errors import InferenceDeniedError

    result = inference_error_to_http(InferenceDeniedError("denied"))
    assert result.status_code == 403


def test_inference_error_to_http_validation_inference() -> None:
    from syndicateclaw.api.inference_http import inference_error_to_http
    from syndicateclaw.inference.errors import InferenceValidationError

    result = inference_error_to_http(InferenceValidationError("bad input"))
    assert result.status_code == 422


def test_inference_error_to_http_routing_error() -> None:
    from syndicateclaw.api.inference_http import inference_error_to_http
    from syndicateclaw.inference.errors import InferenceRoutingError
    from syndicateclaw.inference.types import RoutingFailureReason

    exc = InferenceRoutingError("no models", failure_reason=RoutingFailureReason.NO_MODELS)
    result = inference_error_to_http(exc)
    assert result.status_code == 503


def test_inference_error_to_http_execution_error() -> None:
    from syndicateclaw.api.inference_http import inference_error_to_http
    from syndicateclaw.inference.errors import InferenceExecutionError
    from syndicateclaw.inference.types import ErrorCategory

    exc = InferenceExecutionError("exec", category=ErrorCategory.PROVIDER)
    result = inference_error_to_http(exc)
    assert result.status_code == 503


def test_inference_error_to_http_generic_timeout_category() -> None:
    from syndicateclaw.api.inference_http import inference_error_to_http
    from syndicateclaw.inference.errors import InferenceError
    from syndicateclaw.inference.types import ErrorCategory

    exc = InferenceError("timeout", category=ErrorCategory.TIMEOUT)
    result = inference_error_to_http(exc)
    assert result.status_code == 503


def test_inference_error_to_http_generic_policy_category() -> None:
    from syndicateclaw.api.inference_http import inference_error_to_http
    from syndicateclaw.inference.errors import InferenceError
    from syndicateclaw.inference.types import ErrorCategory

    exc = InferenceError("policy", category=ErrorCategory.POLICY)
    result = inference_error_to_http(exc)
    assert result.status_code == 403


def test_inference_error_to_http_generic_validation_category() -> None:
    from syndicateclaw.api.inference_http import inference_error_to_http
    from syndicateclaw.inference.errors import InferenceError
    from syndicateclaw.inference.types import ErrorCategory

    exc = InferenceError("val", category=ErrorCategory.VALIDATION)
    result = inference_error_to_http(exc)
    assert result.status_code == 422


def test_inference_error_to_http_generic_fallback() -> None:
    from syndicateclaw.api.inference_http import inference_error_to_http
    from syndicateclaw.inference.errors import InferenceError
    from syndicateclaw.inference.types import ErrorCategory

    exc = InferenceError("unknown", category=ErrorCategory.UNKNOWN)
    result = inference_error_to_http(exc)
    assert result.status_code == 502


# ---------------------------------------------------------------------------
# _routing_to_http — branches
# ---------------------------------------------------------------------------


def test_routing_policy_denied() -> None:
    from syndicateclaw.api.inference_http import _routing_to_http
    from syndicateclaw.inference.errors import InferenceRoutingError
    from syndicateclaw.inference.types import RoutingFailureReason

    exc = InferenceRoutingError("pol", failure_reason=RoutingFailureReason.POLICY_DENIED)
    assert _routing_to_http(exc).status_code == 403


def test_routing_sensitivity_blocked() -> None:
    from syndicateclaw.api.inference_http import _routing_to_http
    from syndicateclaw.inference.errors import InferenceRoutingError
    from syndicateclaw.inference.types import RoutingFailureReason

    exc = InferenceRoutingError("sens", failure_reason=RoutingFailureReason.SENSITIVITY_BLOCKED)
    assert _routing_to_http(exc).status_code == 403


def test_routing_pin_mismatch() -> None:
    from syndicateclaw.api.inference_http import _routing_to_http
    from syndicateclaw.inference.errors import InferenceRoutingError
    from syndicateclaw.inference.types import RoutingFailureReason

    exc = InferenceRoutingError("pin", failure_reason=RoutingFailureReason.PIN_MISMATCH)
    assert _routing_to_http(exc).status_code == 400


# ---------------------------------------------------------------------------
# _execution_to_http — branches
# ---------------------------------------------------------------------------


def test_execution_validation_category() -> None:
    from syndicateclaw.api.inference_http import _execution_to_http
    from syndicateclaw.inference.errors import InferenceExecutionError
    from syndicateclaw.inference.types import ErrorCategory

    exc = InferenceExecutionError("val", category=ErrorCategory.VALIDATION)
    assert _execution_to_http(exc).status_code == 422


def test_execution_policy_category() -> None:
    from syndicateclaw.api.inference_http import _execution_to_http
    from syndicateclaw.inference.errors import InferenceExecutionError
    from syndicateclaw.inference.types import ErrorCategory

    exc = InferenceExecutionError("pol", category=ErrorCategory.POLICY)
    assert _execution_to_http(exc).status_code == 403


def test_execution_timeout_category() -> None:
    from syndicateclaw.api.inference_http import _execution_to_http
    from syndicateclaw.inference.errors import InferenceExecutionError
    from syndicateclaw.inference.types import ErrorCategory

    exc = InferenceExecutionError("tmo", category=ErrorCategory.TIMEOUT)
    assert _execution_to_http(exc).status_code == 503


# ---------------------------------------------------------------------------
# runtime/registry/registry.py — SkillRegistry
# ---------------------------------------------------------------------------


def _make_manifest(skill_id: str, version: str, *, deprecated: bool = False):
    from syndicateclaw.runtime.contracts.skill_manifest import IntentTrigger, SkillManifest

    return SkillManifest(
        skill_id=skill_id,
        version=version,
        description="test",
        triggers=[IntentTrigger(type="intent", match=["do something"])],
        deprecated=deprecated,
    )


def test_skill_registry_get_specific_version() -> None:
    from syndicateclaw.runtime.registry.registry import SkillRegistry

    m = _make_manifest("greet", "1.0.0")
    reg = SkillRegistry([m])
    found = reg.get("greet", "1.0.0")
    assert found is m


def test_skill_registry_get_specific_version_not_found_raises() -> None:
    from syndicateclaw.runtime.errors import UnknownSkillError
    from syndicateclaw.runtime.registry.registry import SkillRegistry

    m = _make_manifest("greet", "1.0.0")
    reg = SkillRegistry([m])
    with pytest.raises(UnknownSkillError):
        reg.get("greet", "2.0.0")


def test_skill_registry_list_versions_sorted() -> None:
    from syndicateclaw.runtime.registry.registry import SkillRegistry

    reg = SkillRegistry([
        _make_manifest("greet", "2.0.0"),
        _make_manifest("greet", "1.0.0"),
        _make_manifest("greet", "1.5.0"),
    ])
    versions = reg.list_versions("greet")
    assert versions == ["1.0.0", "1.5.0", "2.0.0"]


def test_skill_registry_list_versions_empty_returns_empty() -> None:
    from syndicateclaw.runtime.registry.registry import SkillRegistry

    reg = SkillRegistry([_make_manifest("greet", "1.0.0")])
    # unknown skill_id → empty list
    versions = reg.list_versions("unknown")
    assert versions == []
