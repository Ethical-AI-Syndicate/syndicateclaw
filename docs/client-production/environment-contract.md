# Environment Contract — DRAFT

**Status: DRAFT. Platform NOT SHIPPABLE.** Values marked `<TBD>` are not yet
proven from versioned artifacts.

## Required components

| Component | Role / authority | Install artifact (target) | Status |
|---|---|---|---|
| ControlPlane Enterprise | **Sole execution authority**; signed durable permits, approval binding, audit chain | container image + Helm chart `charts/controlplane-enterprise` | artifact not yet published/versioned — `<TBD>` |
| Syndicate Code (client host) | requests remote authority; fails closed | `cmd/syndicate` binary | `<TBD>` |
| IntentGate | policy hook; propagates trusted tenant/project/workspace scope | Python package/image | `<TBD>` |
| Syndicate Gate (Enterprise) | model/API mediation; bounded authority | binary + Helm/compose | `<TBD>` |
| Syndicate Claw | execution runtime; **no self-auth**; durable audit | Python package/image | runtime boundary on main; durable audit implemented; full golden-path route `<TBD>` |
| Sentinel | advisory-only evidence review | Python package | `<TBD>` |

## Minimum deployment topology

- ControlPlane Enterprise as a network service (mTLS, port 7443). Embedded/UDS mode
  is **not** acceptable for the client-production topology.
- Each execution host (Code, Claw, Gate) configured with the **remote** ControlPlane
  endpoint + trust anchor. No local-fallback authority.
- Vault/KMS reachable for credential custody. No local/ambient/dummy provider.
- Per-tenant/project/workspace isolation enforced at every layer.

## Required external dependencies

| Dependency | Used by | Version contract |
|---|---|---|
| PostgreSQL | Claw, Gate | `<TBD>` (documented per repo; not assembled) |
| Redis | Claw | `<TBD>` |
| SQLite (WAL, single writer) | ControlPlane | bundled |
| Vault / KMS | credential custody | `<TBD>` |

## Required configuration (env)

| Variable | Component | Meaning |
|---|---|---|
| `SYNDICATE_CP_ENDPOINT` | Code/Claw/Gate | remote ControlPlane URL (https/mTLS) |
| `SYNDICATE_CP_TRUST_ANCHOR` | Code/Claw/Gate | permit-signature trust anchor |
| `SYNDICATECLAW_DATABASE_URL` | Claw | Postgres DSN |
| `SYNDICATECLAW_REDIS_URL` | Claw | Redis URL |
| tenant/project/workspace scope | all | per-deployment scope identifiers |

## ControlPlane endpoint requirements

mTLS-authenticated; issues signed, approval-bound, durable, scoped per-tool permits;
enforces actor/tenant/project/workspace/tool/action/approval binding; emits audit.
Unreachable ControlPlane ⇒ execution hosts fail closed.

## Evidence ledger storage

Claw boundary audit is a durable fsync append-hash-chain
(`runtime_boundary/durable_audit.py`); production must mount durable storage for
the ledger path and back it up. Cross-chain durable evidence at production scale is
`<TBD>`.
