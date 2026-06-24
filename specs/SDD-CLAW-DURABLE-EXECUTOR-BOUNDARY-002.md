# SDD-CLAW-DURABLE-EXECUTOR-BOUNDARY-002 — Claw Durable Real-Executor Boundary

**Spec ID:** SDD-CLAW-DURABLE-EXECUTOR-BOUNDARY-002
**Status:** IN PROGRESS (durable audit keystone implemented + proven; real-executor
golden-path route NOT yet closed — see §7)
**Repo:** syndicateclaw
**Parent:** [[SDD-CLAW-RUNTIME-BOUNDARY-001]], [[SDD-PLATFORM-CLIENT-PRODUCTION-INSTALL-001]]
**Authoritative validator:** `scripts/validate-golden-path-evidence.sh` (SDD-INT-GOLDENPATH-002)

## 1. Purpose

Bring the Claw runtime boundary up to the client-production contract the
cross-product golden-path evidence validator enforces: a **real `ToolExecutor`**
invocation gated on a **verified upstream Code→ControlPlane authority artifact**,
guarded by a **durable, fsync'd, append-only hash-chain audit** that is
restart-replay-verified, concurrent-append-safe, and corrupt-tail fail-closed.

## 2. Real executor requirement

The golden-path allow path MUST invoke the production `ToolExecutor.execute()` and
the real bounded tool handler (`executor_invoked=true`, `tool_handler_invoked=true`).
Policy engine and decision ledger are injectable seams, but the executor and the
tool handler are the real code path — not a static fixture. `side_effect_performed`
is true ONLY after a boundary allow AND a successful durable audit append.

## 3. Authority model

Golden-path mode: Claw consumes a **verified upstream Code→ControlPlane authority
artifact** (`code_permit_response.json` from the upstream boundary stage) and does
**not** make a direct ControlPlane call (`claw_controlplane_direct_call=false`,
`claw_authority_source=verified_upstream_code_controlplane_artifact`). Claw verifies
the artifact's correlation id, actor, tenant/project/workspace, tool/action/scope,
approval binding, permit status, and Gate-evidence reference where required.

Production live-revalidation mode (separate, [[SDD-CLAW-RUNTIME-BOUNDARY-001]]):
Claw re-validates against a running ControlPlane (`HttpControlPlaneValidator`).
Neither mode makes Claw an authority — it consumes or re-validates upstream
authority and fails closed; it never issues a permit.

## 4. Durable audit requirement — IMPLEMENTED

`src/syndicateclaw/runtime_boundary/durable_audit.py` (`DurableAuditChain`):
file-backed JSONL, SHA-256 chain (genesis = 64 zeros), `os.fsync` of file + parent
dir on every append, `fcntl.flock`-serialized appends, previous_hash read from the
durable tail under lock, replay verifier, restart replay (`reopen().verify()`),
corrupt/tampered/torn tail ⇒ `valid=false, corrupt_tail=true` (fail-closed),
append-before-side-effect (boundary appends before allow returns; append failure ⇒
`AUDIT_APPEND_FAILED` deny). **Proven by `tests/unit/test_durable_audit.py`** (6
tests: durability+linkage, restart replay, corrupt tail, tamper, 8×10 concurrent
append with contiguous sequences, append-failure-blocks).

## 5. Required artifacts (validator contract)

`claw_verification.json`, `claw_context.json`, `claw_decision_record.json`,
`claw_tool_result.json`, `claw_audit_event.json`, `claw_negative_cases.json`,
`claw_audit_chain.jsonl`, `claw_audit_chain_verification.json`.

`claw_tool_result.json` must carry: run_id, correlation_id, trace_id, actor_id,
tenant_id, proposal_id, approval_id, approval_fingerprint, permit_id,
action_fingerprint, policy_version, tool_identity, side_effect_class,
gateway_request_id. `claw_decision_record.json`: `.effect=="allow"`,
`.inputs.context.approval_fingerprint` set. `claw_audit_event.json`:
`.event.details.approval_fingerprint`, `event_hash`, `previous_hash`.

## 6. Required negative cases (11, validator-named)

`missing_authority_artifact`, `permit_action_fingerprint_mismatch`,
`approval_binding_mismatch`, `actor_mismatch`, `tenant_mismatch`,
`policy_engine_unavailable`, `audit_evidence_writer_unavailable`,
`unscoped_namespace_access`, `prompt_scope_injection`, `tampered_claw_evidence`,
`missing_correlation_action_fingerprint`. Each must deny **before** any side effect
and leave `side_effect_performed=false`.

## 7. What is proven / NOT proven (this spec, current state)

**Proven (implemented + tested):**
- Durable fsync append-chain audit: durability, restart replay, concurrent-append
  safety, corrupt-tail fail-closed, tamper detection, append-before-side-effect.
- Boundary integrates the durable chain (allow appends durably; append failure ⇒
  `AUDIT_APPEND_FAILED` deny).

**NOT proven (remaining for golden-path validator closure):**
- Real `ToolExecutor` golden-path route emitting `executor_invoked`/
  `tool_handler_invoked`/`side_effect_performed`.
- `verified_upstream_code_controlplane_artifact` verification of the upstream
  `code_permit_response.json`.
- `claw_decision_record.json` + `claw_tool_result.json` (14-field) emission.
- All 11 validator-named negative cases driven through the real executor path.
- `scripts/validate-golden-path-evidence.sh` passing for the Claw boundary.

These remaining items will NOT be marked true in any verdict until implemented and
tested. Where evidence is absent it is reported "not proven".

## 8. Closure criteria

Golden-path Claw closure requires `scripts/validate-golden-path-evidence.sh` to
pass for the Claw boundary with all fields backed by real behavior, the full
`integration/run-enterprise-golden-path.sh` green, and no tags/deploys/secrets.
This spec does not claim platform shippability.
