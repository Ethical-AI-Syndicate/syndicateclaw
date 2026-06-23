"""Claw runtime authority boundary — fail-closed gate before any tool side effect.

SDD-CLAW-RUNTIME-BOUNDARY-001. The boundary:
  1. requires upstream authority context (else AUTHORITY_MISSING);
  2. checks the binding tuple locally (tenant/project/workspace/actor/tool/action/
     approval) for fast, explicit mismatch reasons;
  3. re-validates the authority reference + binding with ControlPlane (the sole
     authority); ControlPlane unavailable ⇒ fail-closed in production mode;
  4. requires Gate evidence when the action used model/API mediation;
  5. appends a boundary decision event to the audit chain BEFORE the side effect
     — if audit append fails, the decision is denied (AUDIT_APPEND_FAILED);
  6. never lets a Sentinel advisory verdict turn a deny into an allow.

Claw never issues authority here: a permit reference is re-validated upstream, not
minted locally.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from .controlplane_client import (
    AuthorityBinding,
    ControlPlaneAuthorityValidator,
    ValidationStatus,
)
from .reason_codes import BoundaryReason


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclasses.dataclass(frozen=True)
class AuthorityContext:
    """Upstream authority evidence presented to Claw for a tool execution."""

    authority_reference: str | None
    actor: str | None
    tenant_id: str | None
    project_id: str | None
    workspace_id: str | None
    tool_identity: str | None
    action: str | None
    resource_scope: str | None
    approval_id: str | None
    correlation_id: str | None
    gate_evidence_reference: str | None = None
    requires_gate_evidence: bool = False

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> AuthorityContext | None:
        if not data:
            return None
        return cls(
            authority_reference=data.get("authority_reference"),
            actor=data.get("actor"),
            tenant_id=data.get("tenant_id"),
            project_id=data.get("project_id"),
            workspace_id=data.get("workspace_id"),
            tool_identity=data.get("tool_identity"),
            action=data.get("action"),
            resource_scope=data.get("resource_scope"),
            approval_id=data.get("approval_id"),
            correlation_id=data.get("correlation_id"),
            gate_evidence_reference=data.get("gate_evidence_reference"),
            requires_gate_evidence=bool(data.get("requires_gate_evidence", False)),
        )


@dataclasses.dataclass(frozen=True)
class ExpectedBinding:
    """What Claw expects the authority to be bound to for THIS execution.

    Derived from the tool/runtime actually being invoked, independent of the
    caller-supplied AuthorityContext, so a mismatch between what was authorized
    and what is being executed is caught.
    """

    actor: str
    tenant_id: str
    project_id: str
    workspace_id: str
    tool_identity: str
    action: str
    resource_scope: str
    approval_id: str | None = None
    require_approval: bool = False


@dataclasses.dataclass
class BoundaryDecision:
    allowed: bool
    reason: BoundaryReason
    authority_reference: str | None
    correlation_id: str | None
    validation: dict[str, Any] | None
    audit_sequence: int | None
    audit_hash: str | None
    detail: str
    evaluated_at: str = dataclasses.field(default_factory=_utcnow_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": str(self.reason),
            "authority_reference": self.authority_reference,
            "correlation_id": self.correlation_id,
            "controlplane_validation": self.validation,
            "audit_sequence": self.audit_sequence,
            "audit_hash": self.audit_hash,
            "detail": self.detail,
            "evaluated_at": self.evaluated_at,
        }


class BoundaryDeniedError(Exception):
    """Raised when the runtime boundary denies a side effect (fail-closed)."""

    def __init__(self, decision: BoundaryDecision):
        self.decision = decision
        super().__init__(f"Claw runtime boundary denied: {decision.reason} ({decision.detail})")


class _AppendOnlyAuditChain:
    """Minimal append-only hash chain for boundary evidence.

    Genesis previous-hash is 64 zeros (matches the platform convention). Each
    record links to the prior record's hash. ``append`` can be made to fail
    (audit-store outage) to prove audit-before-side-effect fail-closed.
    """

    GENESIS = "0" * 64

    def __init__(self) -> None:
        self._records: list[dict[str, Any]] = []
        self._fail = False

    def set_fail(self, value: bool) -> None:
        self._fail = value

    @property
    def records(self) -> list[dict[str, Any]]:
        return list(self._records)

    def append(self, event: dict[str, Any]) -> tuple[int, str]:
        if self._fail:
            raise RuntimeError("audit store unavailable")
        seq = len(self._records)
        prev = self._records[-1]["event_hash"] if self._records else self.GENESIS
        body = dict(event)
        body["sequence"] = seq
        body["previous_hash"] = prev
        canonical = json.dumps(body, sort_keys=True).encode("utf-8")
        event_hash = hashlib.sha256(prev.encode() + canonical).hexdigest()
        body["event_hash"] = event_hash
        self._records.append(body)
        return seq, event_hash

    def verify(self) -> bool:
        prev = self.GENESIS
        for rec in self._records:
            body = {k: v for k, v in rec.items() if k != "event_hash"}
            body["previous_hash"] = prev
            canonical = json.dumps(body, sort_keys=True).encode("utf-8")
            expected = hashlib.sha256(prev.encode() + canonical).hexdigest()
            if expected != rec["event_hash"] or rec["previous_hash"] != prev:
                return False
            prev = rec["event_hash"]
        return True


class ClawRuntimeBoundary:
    """Fail-closed runtime authority gate. Construct with a ControlPlane validator
    and an audit chain; call ``authorize`` before any side effect.
    """

    def __init__(
        self,
        validator: ControlPlaneAuthorityValidator,
        *,
        production_mode: bool = True,
        audit_chain: _AppendOnlyAuditChain | None = None,
    ) -> None:
        self._validator = validator
        self._production = production_mode
        self.audit = audit_chain or _AppendOnlyAuditChain()

    def _emit(
        self,
        reason: BoundaryReason,
        ctx: AuthorityContext | None,
        expected: ExpectedBinding,
        validation: dict[str, Any] | None,
    ) -> BoundaryDecision:
        allowed = reason is BoundaryReason.ALLOWED
        event = {
            "event_type": "CLAW_RUNTIME_BOUNDARY_DECISION",
            "decision": "allow" if allowed else "deny",
            "reason": str(reason),
            "authority_reference": ctx.authority_reference if ctx else None,
            "actor": expected.actor,
            "tenant_id": expected.tenant_id,
            "project_id": expected.project_id,
            "workspace_id": expected.workspace_id,
            "tool_identity": expected.tool_identity,
            "action": expected.action,
            "approval_id": expected.approval_id,
            "correlation_id": ctx.correlation_id if ctx else None,
            "controlplane_validation": validation,
            "emitted_at": _utcnow_iso(),
        }
        # Audit-before-side-effect: append must succeed or we deny fail-closed.
        try:
            seq, evt_hash = self.audit.append(event)
        except Exception:
            # Append failed: this decision cannot be allowed regardless of reason.
            return BoundaryDecision(
                allowed=False,
                reason=BoundaryReason.AUDIT_APPEND_FAILED,
                authority_reference=ctx.authority_reference if ctx else None,
                correlation_id=ctx.correlation_id if ctx else None,
                validation=validation,
                audit_sequence=None,
                audit_hash=None,
                detail="audit append failed before side effect",
            )
        return BoundaryDecision(
            allowed=allowed,
            reason=reason,
            authority_reference=ctx.authority_reference if ctx else None,
            correlation_id=ctx.correlation_id if ctx else None,
            validation=validation,
            audit_sequence=seq,
            audit_hash=evt_hash,
            detail=str(reason),
        )

    def authorize(
        self, ctx: AuthorityContext | None, expected: ExpectedBinding
    ) -> BoundaryDecision:
        """Evaluate the boundary. Returns a BoundaryDecision; ``allowed`` is True
        only when ControlPlane re-validation allows AND every binding matches AND
        audit append succeeded."""

        # 1. Authority must be present.
        if ctx is None or not ctx.authority_reference:
            return self._emit(BoundaryReason.AUTHORITY_MISSING, ctx, expected, None)

        # 2. Local binding checks (explicit, fast, fail-closed reasons).
        if (ctx.tenant_id or "") != expected.tenant_id:
            return self._emit(BoundaryReason.TENANT_MISMATCH, ctx, expected, None)
        if (ctx.project_id or "") != expected.project_id:
            return self._emit(BoundaryReason.PROJECT_MISMATCH, ctx, expected, None)
        if (ctx.workspace_id or "") != expected.workspace_id:
            return self._emit(BoundaryReason.WORKSPACE_MISMATCH, ctx, expected, None)
        if (ctx.actor or "") != expected.actor:
            return self._emit(BoundaryReason.ACTOR_MISMATCH, ctx, expected, None)
        if (ctx.tool_identity or "") != expected.tool_identity or (
            ctx.action or ""
        ) != expected.action:
            return self._emit(BoundaryReason.TOOL_ACTION_MISMATCH, ctx, expected, None)
        if expected.require_approval and (ctx.approval_id or "") != (expected.approval_id or ""):
            return self._emit(BoundaryReason.APPROVAL_MISMATCH, ctx, expected, None)

        # 3. Gate evidence required but missing.
        if ctx.requires_gate_evidence and not ctx.gate_evidence_reference:
            return self._emit(BoundaryReason.GATE_EVIDENCE_MISSING, ctx, expected, None)

        # 4. Re-validate with ControlPlane (the sole authority).
        binding = AuthorityBinding(
            actor=expected.actor,
            tenant_id=expected.tenant_id,
            project_id=expected.project_id,
            workspace_id=expected.workspace_id,
            tool_identity=expected.tool_identity,
            action=expected.action,
            resource_scope=expected.resource_scope,
            approval_id=ctx.approval_id,
            correlation_id=ctx.correlation_id or "",
        )
        result = self._validator.validate(ctx.authority_reference, binding)
        validation = result.to_dict()

        if result.status is ValidationStatus.UNAVAILABLE:
            if self._production:
                return self._emit(
                    BoundaryReason.CONTROLPLANE_UNAVAILABLE, ctx, expected, validation
                )
            # Non-production test mode may proceed only if explicitly configured;
            # default production_mode=True means this branch is opt-in and never
            # the production path.
            return self._emit(BoundaryReason.CONTROLPLANE_UNAVAILABLE, ctx, expected, validation)
        if result.status is ValidationStatus.EXPIRED:
            return self._emit(BoundaryReason.PERMIT_EXPIRED, ctx, expected, validation)
        if result.status is ValidationStatus.REVOKED:
            return self._emit(BoundaryReason.PERMIT_REVOKED, ctx, expected, validation)
        if result.status is ValidationStatus.CONSUMED:
            return self._emit(BoundaryReason.PERMIT_CONSUMED, ctx, expected, validation)
        if result.status is not ValidationStatus.ALLOW:
            return self._emit(BoundaryReason.CONTROLPLANE_DENIED, ctx, expected, validation)

        # 5. Allowed — append ALLOWED event before side effect.
        return self._emit(BoundaryReason.ALLOWED, ctx, expected, validation)


def sentinel_handoff(
    decision: BoundaryDecision, sentinel_advisory: str | None = None
) -> dict[str, Any]:
    """Build the Sentinel handoff artifact. Sentinel is advisory only: its verdict
    is recorded but CANNOT change the authority decision. If a Sentinel advisory
    'allow/safe' arrives without a Claw allow, the handoff records that Sentinel is
    not authority (SENTINEL_NOT_AUTHORITY) — the decision stays denied.
    """
    note = None
    if not decision.allowed and sentinel_advisory in {"allow", "safe", "approve"}:
        note = str(BoundaryReason.SENTINEL_NOT_AUTHORITY)
    return {
        "claw_decision": decision.to_dict(),
        "sentinel_advisory": sentinel_advisory,
        "authority_unchanged_by_sentinel": True,
        "note": note,
        "handoff_at": _utcnow_iso(),
    }
