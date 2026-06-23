"""Structured reason codes for the Claw runtime authority boundary.

SDD-CLAW-RUNTIME-BOUNDARY-001. Every boundary decision carries exactly one of
these codes. ``ALLOWED`` is the only non-deny code; all others deny the side
effect (fail-closed).
"""

from __future__ import annotations

import enum


class BoundaryReason(enum.StrEnum):
    # Allow path.
    ALLOWED = "ALLOWED"

    # Fail-closed deny codes (no side effect may occur).
    AUTHORITY_MISSING = "AUTHORITY_MISSING"
    CONTROLPLANE_UNAVAILABLE = "CONTROLPLANE_UNAVAILABLE"
    CONTROLPLANE_DENIED = "CONTROLPLANE_DENIED"
    TENANT_MISMATCH = "TENANT_MISMATCH"
    PROJECT_MISMATCH = "PROJECT_MISMATCH"
    WORKSPACE_MISMATCH = "WORKSPACE_MISMATCH"
    ACTOR_MISMATCH = "ACTOR_MISMATCH"
    TOOL_ACTION_MISMATCH = "TOOL_ACTION_MISMATCH"
    APPROVAL_MISMATCH = "APPROVAL_MISMATCH"
    PERMIT_EXPIRED = "PERMIT_EXPIRED"
    PERMIT_REVOKED = "PERMIT_REVOKED"
    PERMIT_CONSUMED = "PERMIT_CONSUMED"
    GATE_EVIDENCE_MISSING = "GATE_EVIDENCE_MISSING"
    AUDIT_APPEND_FAILED = "AUDIT_APPEND_FAILED"
    SENTINEL_NOT_AUTHORITY = "SENTINEL_NOT_AUTHORITY"


#: The only reason that permits a side effect. Everything else fails closed.
ALLOW_REASON = BoundaryReason.ALLOWED


def is_allow(reason: BoundaryReason) -> bool:
    return reason is BoundaryReason.ALLOWED
