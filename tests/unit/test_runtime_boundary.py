"""Claw runtime authority boundary tests (SDD-CLAW-RUNTIME-BOUNDARY-001).

Encodes desired production behavior: every tool side effect must be gated on a
re-validated upstream ControlPlane authority decision, and the boundary fails
closed for missing/invalid/mismatched/stale/revoked/expired/consumed authority,
an unavailable ControlPlane (production mode), missing required Gate evidence, and
audit-append failure. Sentinel is advisory-only and cannot authorize.
"""

from __future__ import annotations

import dataclasses

from syndicateclaw.runtime_boundary import (
    AuthorityBinding,
    AuthorityContext,
    ClawRuntimeBoundary,
    ExpectedBinding,
    InMemoryControlPlaneValidator,
    ValidationStatus,
    sentinel_handoff,
)
from syndicateclaw.runtime_boundary.boundary import _AppendOnlyAuditChain
from syndicateclaw.runtime_boundary.reason_codes import BoundaryReason

CORR = "corr-001"


def _expected(**over) -> ExpectedBinding:
    base = dict(
        actor="operator-1",
        tenant_id="t1",
        project_id="p1",
        workspace_id="w1",
        tool_identity="fs.write_file",
        action="filesystem.write",
        resource_scope="/ws/p1/README.md",
        approval_id="dec-1",
        require_approval=False,
    )
    base.update(over)
    return ExpectedBinding(**base)


def _ctx(expected: ExpectedBinding, **over) -> AuthorityContext:
    data = dict(
        authority_reference="perm-1",
        actor=expected.actor,
        tenant_id=expected.tenant_id,
        project_id=expected.project_id,
        workspace_id=expected.workspace_id,
        tool_identity=expected.tool_identity,
        action=expected.action,
        resource_scope=expected.resource_scope,
        approval_id=expected.approval_id,
        correlation_id=CORR,
    )
    data.update(over)
    return AuthorityContext.from_mapping(data)


def _binding_from(expected: ExpectedBinding, ctx: AuthorityContext) -> AuthorityBinding:
    return AuthorityBinding(
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


def _registered_boundary(*, single_use=False, status=ValidationStatus.ALLOW, production=True):
    expected = _expected()
    ctx = _ctx(expected)
    validator = InMemoryControlPlaneValidator()
    validator.register("perm-1", _binding_from(expected, ctx), status=status, single_use=single_use)
    boundary = ClawRuntimeBoundary(validator, production_mode=production)
    return boundary, validator, expected, ctx


# --- Allow path -----------------------------------------------------------


def test_allow_path_executes_and_audits_before_side_effect():
    boundary, validator, expected, ctx = _registered_boundary()
    decision = boundary.authorize(ctx, expected)
    assert decision.allowed is True
    assert decision.reason is BoundaryReason.ALLOWED
    assert decision.audit_sequence == 0  # appended BEFORE side effect
    assert decision.audit_hash
    assert decision.correlation_id == CORR
    assert decision.authority_reference == "perm-1"
    assert validator.calls, "ControlPlane must be re-validated"
    assert boundary.audit.verify() is True


# --- Deny paths -----------------------------------------------------------


def test_missing_authority_denies():
    boundary, _, expected, _ = _registered_boundary()
    decision = boundary.authorize(None, expected)
    assert not decision.allowed
    assert decision.reason is BoundaryReason.AUTHORITY_MISSING


def test_missing_authority_reference_denies():
    boundary, _, expected, ctx = _registered_boundary()
    bad = dataclasses.replace(ctx, authority_reference=None)
    decision = boundary.authorize(bad, expected)
    assert decision.reason is BoundaryReason.AUTHORITY_MISSING


def test_controlplane_unavailable_denies_in_production():
    boundary, validator, expected, ctx = _registered_boundary()
    validator.set_unavailable(True)
    decision = boundary.authorize(ctx, expected)
    assert not decision.allowed
    assert decision.reason is BoundaryReason.CONTROLPLANE_UNAVAILABLE


def test_controlplane_deny_denies():
    boundary, validator, expected, ctx = _registered_boundary(status=ValidationStatus.DENIED)
    decision = boundary.authorize(ctx, expected)
    assert decision.reason is BoundaryReason.CONTROLPLANE_DENIED


def test_tenant_mismatch_denies():
    boundary, _, expected, ctx = _registered_boundary()
    decision = boundary.authorize(dataclasses.replace(ctx, tenant_id="other"), expected)
    assert decision.reason is BoundaryReason.TENANT_MISMATCH


def test_project_mismatch_denies():
    boundary, _, expected, ctx = _registered_boundary()
    decision = boundary.authorize(dataclasses.replace(ctx, project_id="other"), expected)
    assert decision.reason is BoundaryReason.PROJECT_MISMATCH


def test_workspace_mismatch_denies():
    boundary, _, expected, ctx = _registered_boundary()
    decision = boundary.authorize(dataclasses.replace(ctx, workspace_id="other"), expected)
    assert decision.reason is BoundaryReason.WORKSPACE_MISMATCH


def test_actor_mismatch_denies():
    boundary, _, expected, ctx = _registered_boundary()
    decision = boundary.authorize(dataclasses.replace(ctx, actor="intruder"), expected)
    assert decision.reason is BoundaryReason.ACTOR_MISMATCH


def test_tool_action_mismatch_denies():
    boundary, _, expected, ctx = _registered_boundary()
    decision = boundary.authorize(dataclasses.replace(ctx, action="filesystem.delete"), expected)
    assert decision.reason is BoundaryReason.TOOL_ACTION_MISMATCH


def test_approval_mismatch_denies():
    boundary, validator, _, _ = _registered_boundary()
    expected = _expected(require_approval=True, approval_id="dec-1")
    ctx = _ctx(expected, approval_id="dec-WRONG")
    decision = boundary.authorize(ctx, expected)
    assert decision.reason is BoundaryReason.APPROVAL_MISMATCH


def test_expired_permit_denies():
    boundary, _, expected, ctx = _registered_boundary(status=ValidationStatus.EXPIRED)
    assert boundary.authorize(ctx, expected).reason is BoundaryReason.PERMIT_EXPIRED


def test_revoked_permit_denies():
    boundary, _, expected, ctx = _registered_boundary(status=ValidationStatus.REVOKED)
    assert boundary.authorize(ctx, expected).reason is BoundaryReason.PERMIT_REVOKED


def test_consumed_permit_replay_denies():
    boundary, validator, expected, ctx = _registered_boundary(single_use=True)
    first = boundary.authorize(ctx, expected)
    assert first.allowed  # first use consumes
    second = boundary.authorize(ctx, expected)  # replay
    assert not second.allowed
    assert second.reason is BoundaryReason.PERMIT_CONSUMED


def test_missing_gate_evidence_denies():
    boundary, validator, expected, _ = _registered_boundary()
    ctx = _ctx(expected, requires_gate_evidence=True, gate_evidence_reference=None)
    decision = boundary.authorize(ctx, expected)
    assert decision.reason is BoundaryReason.GATE_EVIDENCE_MISSING


def test_audit_append_failure_denies_before_side_effect():
    boundary, _, expected, ctx = _registered_boundary()
    boundary.audit.set_fail(True)
    decision = boundary.authorize(ctx, expected)
    assert not decision.allowed
    assert decision.reason is BoundaryReason.AUDIT_APPEND_FAILED
    assert decision.audit_sequence is None


def test_sentinel_advisory_cannot_authorize_without_controlplane():
    # No authority present -> denied; Sentinel says "safe" -> still denied.
    boundary, _, expected, _ = _registered_boundary()
    decision = boundary.authorize(None, expected)
    assert not decision.allowed
    handoff = sentinel_handoff(decision, sentinel_advisory="safe")
    assert handoff["authority_unchanged_by_sentinel"] is True
    assert handoff["note"] == str(BoundaryReason.SENTINEL_NOT_AUTHORITY)
    assert handoff["claw_decision"]["allowed"] is False


# --- Audit chain ----------------------------------------------------------


def test_audit_chain_replay_verifies_and_links():
    boundary, _, expected, ctx = _registered_boundary()
    boundary.authorize(dataclasses.replace(ctx, tenant_id="x"), expected)  # deny
    boundary.authorize(ctx, expected)  # allow
    assert boundary.audit.verify() is True
    recs = boundary.audit.records
    assert recs[0]["previous_hash"] == _AppendOnlyAuditChain.GENESIS
    assert recs[1]["previous_hash"] == recs[0]["event_hash"]
    assert all(r["correlation_id"] == CORR for r in recs)


def test_audit_chain_tamper_detected():
    boundary, _, expected, ctx = _registered_boundary()
    boundary.authorize(ctx, expected)
    assert boundary.audit.records  # a record exists to tamper with
    boundary.audit._records[0]["reason"] = "TAMPERED"  # noqa: SLF001 - test tamper
    assert boundary.audit.verify() is False
