# SDD-CLAW-RUNTIME-BOUNDARY-001 — Syndicate Claw Runtime Authority Boundary

**Spec ID:** SDD-CLAW-RUNTIME-BOUNDARY-001
**Status:** IN PROGRESS
**Repo:** syndicateclaw
**Created:** 2026-06-23
**Parent:** [[SDD-PLATFORM-CLIENT-PRODUCTION-INSTALL-001]]

## 1. Purpose

Prove Syndicate Claw participates in the governed runtime chain **without becoming
authority**. Claw is an execution runtime guarded by **upstream ControlPlane
Enterprise authority**. The boundary gates every tool side effect on a verified
upstream authority decision and **fails closed** when that authority is absent,
invalid, mismatched, stale, revoked, expired, consumed, or unverifiable.

## 2. Authority model

- ControlPlane Enterprise is the **sole** execution authority.
- Claw **does not** issue permits, **does not** override ControlPlane decisions,
  and **does not** treat Sentinel output as authority.
- Claw **must not** execute a side effect if authority evidence is missing,
  invalid, stale, mismatched, revoked, expired, or consumed.

## 3. Preferred verification model (design rule)

Claw **re-validates** runtime authority against a running ControlPlane endpoint
before any side effect. Claw sends the authority reference + binding tuple
(actor, tenant/project/workspace, tool/action/scope, approval binding,
correlation id); ControlPlane returns `allow` / `deny`. **ControlPlane
unavailable ⇒ deny/fail-closed** unless explicitly configured for a non-production
test mode. Claw does **not** reimplement ControlPlane signing canonicalization by
guesswork; local cryptographic verification is permitted only against a
ControlPlane-owned shared verifier or canonical test vectors (not in scope here).

## 4. Required upstream evidence

`authority_reference` (permit id / decision ref), `actor`, tenant/project/
workspace tuple, tool/action/scope binding, approval binding (where required),
caller/Code-origin context (where applicable), Gate evidence reference (where
model/API mediation was used), and a correlation id linking the chain.

## 5. Claw verification behavior (before side effect)

Re-validate / verify: tenant+project+workspace match; actor match;
tool/action/scope match; approval binding match; permit status with ControlPlane;
expiry/revocation/consume status with ControlPlane; correlation-id continuity;
and that **audit append succeeds before the side effect**.

## 6. Fail-closed behavior

Deny **before** side effect when: authority missing; ControlPlane re-validation
denies; ControlPlane unavailable in production mode; tenant/project/workspace
mismatch; actor mismatch; tool/action mismatch; approval mismatch; permit
expired/revoked/consumed (replay); Gate evidence required but missing; audit
append fails; or Sentinel says "safe" while ControlPlane authority is absent.

## 7. Evidence emitted by Claw

allow/deny decision event; upstream authority reference; ControlPlane validation
result reference; tenant/project/workspace tuple; actor/tool/action binding;
approval binding; Gate evidence reference (where applicable); audit-chain
hash/sequence reference; fail-closed reason code; Sentinel handoff artifact.

## 8. Sentinel handoff

Sentinel receives Claw evidence as **advisory input only**. Sentinel may
verify/replay evidence and produce an advisory verdict; it **cannot** change a
Claw deny into an allow, and cannot supply authority.

## 9. Required artifacts (boundary proof)

`claw_runtime_boundary.json`, `claw_authority_validation.json`,
`claw_audit_chain.jsonl`, `claw_audit_chain_verification.json`,
`sentinel_ingest_result.json`, `verdict.json`.

## 10. Reason codes

`AUTHORITY_MISSING`, `CONTROLPLANE_UNAVAILABLE`, `CONTROLPLANE_DENIED`,
`TENANT_MISMATCH`, `PROJECT_MISMATCH`, `WORKSPACE_MISMATCH`, `ACTOR_MISMATCH`,
`TOOL_ACTION_MISMATCH`, `APPROVAL_MISMATCH`, `PERMIT_EXPIRED`, `PERMIT_REVOKED`,
`PERMIT_CONSUMED`, `GATE_EVIDENCE_MISSING`, `AUDIT_APPEND_FAILED`,
`SENTINEL_NOT_AUTHORITY` (+ `ALLOWED` for the allow path).

## 11. Design / integration points (from code inspection)

- Side effect = `tool_def.handler()` in `ToolExecutor.execute()` step 5
  (`src/syndicateclaw/tools/executor.py`). The boundary gate runs **before** it.
- Today there is **no** upstream authority check — Claw authorizes via its local
  PolicyEngine only (effectively self-authorizing). This SDD adds the upstream
  gate; the local policy/sandbox/decision-ledger checks are **retained** (not
  weakened).
- Authority context is carried on `ExecutionContext.config["authority"]`.
- New package `src/syndicateclaw/runtime_boundary/`:
  `reason_codes.py`, `boundary.py`, `controlplane_client.py`.
- The executor gate is **active when a boundary is configured** on the executor;
  when active and authority is required, missing/invalid authority denies
  fail-closed before the side effect. Existing executor flows without a configured
  boundary are unchanged (no regression), per rule 8.

## 12. BDD examples

- **Given** a valid, ControlPlane-revalidated permit matching the binding tuple,
  **when** Claw executes the tool, **then** the side effect runs and an
  `ALLOWED` boundary event is appended before execution.
- **Given** ControlPlane is unavailable in production mode, **when** Claw
  evaluates the boundary, **then** it denies with `CONTROLPLANE_UNAVAILABLE`
  before any side effect.
- **Given** a consumed permit is replayed, **when** Claw re-validates, **then**
  ControlPlane reports consumed and Claw denies with `PERMIT_CONSUMED`.
- **Given** Sentinel returns advisory "safe" but no ControlPlane authority is
  present, **when** Claw evaluates, **then** Claw denies with `AUTHORITY_MISSING`
  / `SENTINEL_NOT_AUTHORITY` (Sentinel cannot authorize).

## 13. Closure criteria

SDD committed; focused boundary tests + negative tests; integration script
`scripts/integration/run-claw-boundary.sh`; CI job `claw_runtime_boundary`; Claw
default-branch CI green after merge; no tags/deploys/secrets; existing
tenant/RBAC + durable audit-chain tests still green; **no claim of platform
shippability**.

## 14. What this proves / does not prove

**Proves:** the Claw runtime boundary fails closed without upstream ControlPlane
authority, audits before side effect, and treats Sentinel as advisory-only —
exercised against a test ControlPlane re-validation harness implementing the
allow/deny contract. **Does not prove:** the production ControlPlane signing
canonicalization (re-validation contract only); production deployment;
client-production-installable platform shippability; full signed-release closure.
