"""Claw runtime authority boundary (SDD-CLAW-RUNTIME-BOUNDARY-001).

ControlPlane Enterprise is the sole execution authority. This package gates every
tool side effect on a re-validated upstream authority decision and fails closed
when authority is absent/invalid/mismatched/stale/revoked/expired/consumed or
ControlPlane is unavailable in production mode. Claw never issues authority;
Sentinel is advisory-only.
"""

from __future__ import annotations

from .boundary import (
    AuthorityContext,
    BoundaryDecision,
    BoundaryDeniedError,
    ClawRuntimeBoundary,
    ExpectedBinding,
    sentinel_handoff,
)
from .controlplane_client import (
    AuthorityBinding,
    ControlPlaneAuthorityValidator,
    HttpControlPlaneValidator,
    InMemoryControlPlaneValidator,
    ValidationResult,
    ValidationStatus,
)
from .reason_codes import ALLOW_REASON, BoundaryReason, is_allow

__all__ = [
    "ALLOW_REASON",
    "AuthorityBinding",
    "AuthorityContext",
    "BoundaryDecision",
    "BoundaryDeniedError",
    "BoundaryReason",
    "ClawRuntimeBoundary",
    "ControlPlaneAuthorityValidator",
    "ExpectedBinding",
    "HttpControlPlaneValidator",
    "InMemoryControlPlaneValidator",
    "ValidationResult",
    "ValidationStatus",
    "is_allow",
    "sentinel_handoff",
]
