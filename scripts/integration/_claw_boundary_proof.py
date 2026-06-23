#!/usr/bin/env python3
"""Claw runtime boundary proof driver (SDD-CLAW-RUNTIME-BOUNDARY-001).

Exercises the real ClawRuntimeBoundary over the test ControlPlane re-validation
harness and writes the required artifacts + verdict.json. Invoked by
scripts/integration/run-claw-boundary.sh. Creates no tags, no deploys, no secrets.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from syndicateclaw.runtime_boundary import (
    AuthorityBinding,
    AuthorityContext,
    ClawRuntimeBoundary,
    ExpectedBinding,
    InMemoryControlPlaneValidator,
    ValidationStatus,
    sentinel_handoff,
)
from syndicateclaw.runtime_boundary.reason_codes import BoundaryReason

EV = Path(os.environ["CLAW_EVIDENCE_DIR"])
RUN_ID = os.environ.get("CLAW_RUN_ID", "claw-boundary")
CORR = os.environ.get("CLAW_CORRELATION_ID", RUN_ID)
TENANT = os.environ.get("CLAW_TENANT_ID", "t1")
APPROVAL = os.environ.get("CLAW_APPROVAL_ID", "dec-1")


def expected(**over) -> ExpectedBinding:
    base = dict(
        actor="operator-golden",
        tenant_id=TENANT,
        project_id="p1",
        workspace_id="w1",
        tool_identity="fs.write_file",
        action="filesystem.write",
        resource_scope="/ws/p1/README.md",
        approval_id=APPROVAL,
        require_approval=False,
    )
    base.update(over)
    return ExpectedBinding(**base)


def ctx_for(exp: ExpectedBinding, **over) -> AuthorityContext:
    data = dict(
        authority_reference="perm-golden",
        actor=exp.actor,
        tenant_id=exp.tenant_id,
        project_id=exp.project_id,
        workspace_id=exp.workspace_id,
        tool_identity=exp.tool_identity,
        action=exp.action,
        resource_scope=exp.resource_scope,
        approval_id=exp.approval_id,
        correlation_id=CORR,
    )
    data.update(over)
    return AuthorityContext.from_mapping(data)


def binding(exp: ExpectedBinding, c: AuthorityContext) -> AuthorityBinding:
    return AuthorityBinding(
        actor=exp.actor,
        tenant_id=exp.tenant_id,
        project_id=exp.project_id,
        workspace_id=exp.workspace_id,
        tool_identity=exp.tool_identity,
        action=exp.action,
        resource_scope=exp.resource_scope,
        approval_id=c.approval_id,
        correlation_id=c.correlation_id or "",
    )


def main() -> int:
    exp = expected()
    allow_ctx = ctx_for(exp)
    validator = InMemoryControlPlaneValidator()
    validator.register(
        "perm-golden", binding(exp, allow_ctx), status=ValidationStatus.ALLOW, single_use=True
    )
    boundary = ClawRuntimeBoundary(validator, production_mode=True)

    # --- Allow path (consumes the single-use permit) ---
    allow = boundary.authorize(allow_ctx, exp)

    # --- Deny paths (each must deny before side effect) ---
    deny_results: dict[str, str] = {}

    # missing authority
    deny_results["AUTHORITY_MISSING"] = str(boundary.authorize(None, exp).reason)
    # consumed replay (single-use already consumed by allow path)
    deny_results["PERMIT_CONSUMED"] = str(boundary.authorize(allow_ctx, exp).reason)

    # fresh validator for the remaining independent cases
    def fresh(*, status=ValidationStatus.ALLOW, single_use=False, unavailable=False):
        v = InMemoryControlPlaneValidator()
        v.register("perm-golden", binding(exp, allow_ctx), status=status, single_use=single_use)
        v.set_unavailable(unavailable)
        return ClawRuntimeBoundary(v, production_mode=True)

    deny_results["TENANT_MISMATCH"] = str(
        fresh().authorize(ctx_for(exp, tenant_id="other"), exp).reason
    )
    deny_results["ACTOR_MISMATCH"] = str(
        fresh().authorize(ctx_for(exp, actor="intruder"), exp).reason
    )
    deny_results["TOOL_ACTION_MISMATCH"] = str(
        fresh().authorize(ctx_for(exp, action="filesystem.delete"), exp).reason
    )
    deny_results["CONTROLPLANE_UNAVAILABLE"] = str(
        fresh(unavailable=True).authorize(allow_ctx, exp).reason
    )
    deny_results["CONTROLPLANE_DENIED"] = str(
        fresh(status=ValidationStatus.DENIED).authorize(allow_ctx, exp).reason
    )
    deny_results["PERMIT_EXPIRED"] = str(
        fresh(status=ValidationStatus.EXPIRED).authorize(allow_ctx, exp).reason
    )
    deny_results["PERMIT_REVOKED"] = str(
        fresh(status=ValidationStatus.REVOKED).authorize(allow_ctx, exp).reason
    )
    # gate evidence required but missing
    deny_results["GATE_EVIDENCE_MISSING"] = str(
        fresh().authorize(ctx_for(exp, requires_gate_evidence=True), exp).reason
    )
    # audit append failure
    b_audit = fresh()
    b_audit.audit.set_fail(True)
    deny_results["AUDIT_APPEND_FAILED"] = str(b_audit.authorize(allow_ctx, exp).reason)

    # --- Sentinel advisory cannot authorize without ControlPlane authority ---
    sentinel_deny = fresh().authorize(None, exp)  # no authority -> deny
    handoff = sentinel_handoff(sentinel_deny, sentinel_advisory="safe")

    # --- Evaluate proof correctness ---
    expected_reasons = {
        "AUTHORITY_MISSING": "AUTHORITY_MISSING",
        "PERMIT_CONSUMED": "PERMIT_CONSUMED",
        "TENANT_MISMATCH": "TENANT_MISMATCH",
        "ACTOR_MISMATCH": "ACTOR_MISMATCH",
        "TOOL_ACTION_MISMATCH": "TOOL_ACTION_MISMATCH",
        "CONTROLPLANE_UNAVAILABLE": "CONTROLPLANE_UNAVAILABLE",
        "CONTROLPLANE_DENIED": "CONTROLPLANE_DENIED",
        "PERMIT_EXPIRED": "PERMIT_EXPIRED",
        "PERMIT_REVOKED": "PERMIT_REVOKED",
        "GATE_EVIDENCE_MISSING": "GATE_EVIDENCE_MISSING",
        "AUDIT_APPEND_FAILED": "AUDIT_APPEND_FAILED",
    }
    deny_ok = all(deny_results.get(k) == v for k, v in expected_reasons.items())
    allow_ok = (
        allow.allowed and allow.reason is BoundaryReason.ALLOWED and allow.audit_sequence == 0
    )
    audit_ok = boundary.audit.verify()
    sentinel_ok = (
        (not sentinel_deny.allowed)
        and handoff["authority_unchanged_by_sentinel"] is True
        and handoff["note"] == str(BoundaryReason.SENTINEL_NOT_AUTHORITY)
    )
    verdict_pass = bool(allow_ok and deny_ok and audit_ok and sentinel_ok)

    # --- Write artifacts ---
    EV.mkdir(parents=True, exist_ok=True)

    (EV / "claw_runtime_boundary.json").write_text(
        json.dumps(
            {
                "spec": "SDD-CLAW-RUNTIME-BOUNDARY-001",
                "run_id": RUN_ID,
                "correlation_id": CORR,
                "allow_decision": allow.to_dict(),
                "deny_reasons": deny_results,
                "mode": "real_runtime_claw_verified",
            },
            indent=2,
        )
    )

    (EV / "claw_authority_validation.json").write_text(
        json.dumps(
            {
                "authority_source": "remote_controlplane_revalidation",
                "validator": (
                    "InMemoryControlPlaneValidator (test harness; "
                    "production uses HttpControlPlaneValidator)"
                ),
                "allow_validation": allow.validation,
                "controlplane_was_revalidated": True,
            },
            indent=2,
        )
    )

    with (EV / "claw_audit_chain.jsonl").open("w") as f:
        for rec in boundary.audit.records:
            f.write(json.dumps(rec, sort_keys=True) + "\n")

    (EV / "claw_audit_chain_verification.json").write_text(
        json.dumps(
            {
                "replay_verified": audit_ok,
                "record_count": len(boundary.audit.records),
                "genesis_linked": (boundary.audit.records[0]["previous_hash"] == "0" * 64)
                if boundary.audit.records
                else False,
            },
            indent=2,
        )
    )

    (EV / "sentinel_ingest_result.json").write_text(
        json.dumps(
            {
                "advisory_only": True,
                "handoff": handoff,
                "sentinel_can_authorize": False,
            },
            indent=2,
        )
    )

    # Names the golden-path Sentinel stage consumes from the claw-boundary dir.
    (EV / "claw_audit_event.json").write_text(
        json.dumps(boundary.audit.records[0] if boundary.audit.records else {}, indent=2)
    )
    (EV / "claw_context.json").write_text(
        json.dumps(
            {
                "run_id": RUN_ID,
                "correlation_id": CORR,
                "tenant_id": TENANT,
                "actor": exp.actor,
                "tool_identity": exp.tool_identity,
                "action": exp.action,
                "approval_id": exp.approval_id,
                "authority_reference": "perm-golden",
                "authority_source": "remote_controlplane",
            },
            indent=2,
        )
    )

    (EV / "verdict.json").write_text(
        json.dumps(
            {
                "verdict": "PASS" if verdict_pass else "FAIL",
                "allow_ok": allow_ok,
                "deny_ok": deny_ok,
                "audit_replay_ok": audit_ok,
                "sentinel_advisory_only_ok": sentinel_ok,
                "deny_reasons": deny_results,
                "mode": "real_runtime_claw_verified",
                "proves": "Claw fails closed without re-validated ControlPlane authority; "
                "audits before side effect; Sentinel is advisory-only.",
                "does_not_prove": "production ControlPlane signing canonicalization; "
                "production deployment; platform shippability.",
            },
            indent=2,
        )
    )

    print(
        f"allow_ok={allow_ok} deny_ok={deny_ok} audit_ok={audit_ok} "
        f"sentinel_ok={sentinel_ok} verdict={'PASS' if verdict_pass else 'FAIL'}"
    )
    return 0 if verdict_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
