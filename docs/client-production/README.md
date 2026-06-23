# Client Production Readiness Bundle

**Status: CLIENT PRODUCTION READINESS BUNDLE: DRAFT**
**Platform classification: NOT SHIPPABLE**

This bundle is the operational artifact structure a client will eventually use to
install and operate the AI Syndicate governed-execution platform in a production
environment. It is **not** a shippability claim and is incomplete until install
from versioned artifacts and production-shape dependencies (ControlPlane, Vault/KMS,
tenant isolation, TLS/mTLS, durable evidence) are proven end-to-end.

It is staged in the `syndicateclaw` repo because the workspace root and
`integration/` are not version-controlled; a dedicated platform-install repo is
the eventual home (see [[SDD-PLATFORM-CLIENT-PRODUCTION-INSTALL-001]]).

## Documents

| Doc | Purpose |
|---|---|
| [environment-contract.md](environment-contract.md) | Components, versioned artifacts, topology, external dependencies |
| [network-boundaries.md](network-boundaries.md) | Required network edges and their transport security |
| [secrets-and-certificates.md](secrets-and-certificates.md) | Keys, certs, custody requirements |
| [install-smoke-test.md](install-smoke-test.md) | Clean-environment install + startup readiness checks |
| [rollback-and-recovery.md](rollback-and-recovery.md) | Upgrade, rollback, post-install verification |
| [readiness-checklist.md](readiness-checklist.md) | The shippability gate; open NOT-SHIPPABLE items |

## Governed execution chain (what the client operates)

```
Code / client host → IntentGate (scope) → ControlPlane Enterprise (AUTHORITY)
  → Gate (model/API mediation) → Claw (execution; no self-auth)
  → Sentinel (advisory) → durable evidence/audit verification
```

ControlPlane Enterprise is the **sole** authority. Code/IntentGate/Gate/Claw do not
self-authorize; Sentinel is advisory-only; missing/invalid/stale/revoked/expired/
consumed authority fails closed before any side effect.

## Open shippability gates (NOT SHIPPABLE until all proven)

- Full Code→ControlPlane→Gate→Claw→Sentinel golden path passes
  `scripts/validate-golden-path-evidence.sh` (Claw durable real-executor contract
  **not yet closed** — see [[SDD-CLAW-DURABLE-EXECUTOR-BOUNDARY-002]] §7).
- Client install from **versioned, signed artifacts** (not source trees) — not proven.
- Vault/KMS production-shape credential custody — not proven.
- Tenant/project/workspace isolation across the whole chain at production scale — not proven.
- Production deployment + rollback + post-install verification — not proven.
- Full signed-release closure (authorized annotated signed release tag) — not proven.
