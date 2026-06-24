# Client Production Readiness Checklist — DRAFT

**Status: CLIENT PRODUCTION READINESS BUNDLE: DRAFT. Platform NOT SHIPPABLE.**

A platform is shippable only when a client can install it in a production
environment from documented **versioned artifacts** and operate the governed
execution chain with verified fail-closed behavior. Each gate below must be PROVEN
(not asserted). Where evidence is absent it is marked "not proven".

## Authority / runtime gates

- [x] ControlPlane RBAC derives authority only from verified identity (merged + proven)
- [x] Durable per-tool permits actor/tenant/project/workspace/tool/action/approval-bound (merged + proven)
- [x] Syndicate Code uses remote ControlPlane permit path; no prod local-fallback (merged + proven)
- [x] Gate boundary bounded; emits linked evidence (merged + proven)
- [x] Claw runtime boundary fails closed without upstream authority (merged + proven)
- [x] Claw durable fsync audit chain: restart-replay, concurrent, corrupt-tail fail-closed (implemented + tested)
- [ ] Claw **real-executor golden-path route** (`executor_invoked`/`tool_handler_invoked`) — **not proven**
- [ ] Claw `verified_upstream_code_controlplane_artifact` verification — **not proven**
- [ ] Claw `claw_decision_record.json` + `claw_tool_result.json` (14-field) artifacts — **not proven**
- [ ] All 11 validator-named negative cases through the real executor — **not proven**
- [x] Sentinel advisory-only (merged + proven)

## Golden path

- [ ] `integration/run-enterprise-golden-path.sh` green end-to-end — chain executes; **not a pass** (Claw bundle contract open)
- [ ] `scripts/validate-golden-path-evidence.sh` passes for Claw boundary — **not proven**

## Client install / dependencies

- [ ] Install from **versioned, signed artifacts** (not source trees) — **not proven**
- [ ] Vault/KMS production-shape custody (scoped lookup, mismatch deny, rotation) — **not proven**
- [ ] Tenant/project/workspace isolation across the full chain at production scale — **not proven**
- [ ] TLS/mTLS trust-anchor + cert rotation tested — **not proven**
- [ ] Durable evidence ledger storage provisioned + backed up — **not proven**

## Operations

- [ ] Startup readiness checks pass in a clean environment — **not proven**
- [ ] Tested rollback + post-install verification — **not proven**
- [ ] Production deployment executed + verified — **not proven**

## Release

- [x] No ordinary main push can auto-release or auto-deploy (proven across 7 repos)
- [ ] Authorized annotated **signed release tag** created + verified (`--require-signed`) — **not proven** (out of scope)

## Verdict

**NOT SHIPPABLE.** First open runtime gate: Claw real-executor golden-path route +
the validator-required durable real-executor artifacts. The durable audit keystone
is implemented and tested; the remaining gates above are not proven.
