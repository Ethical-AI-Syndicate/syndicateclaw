# Network Boundaries — DRAFT

**Status: DRAFT. Platform NOT SHIPPABLE.**

## Required network edges

| Edge | Transport | Auth | Fail-closed behavior |
|---|---|---|---|
| Code → ControlPlane | mTLS (TCP 7443) | mutual TLS + signed permit | unreachable / bad cert ⇒ deny (proven: mTLS no-cert + wrong-CA denied) |
| Claw → ControlPlane (live re-validation mode) | mTLS / https | mutual TLS | unreachable ⇒ `CONTROLPLANE_UNAVAILABLE` deny |
| Claw (golden-path mode) | consumes verified upstream permit artifact | n/a (no direct call) | invalid/missing artifact ⇒ deny |
| Gate → model/API providers | TLS | provider credentials (scoped per tenant) | provider failure ⇒ bounded fail |
| Sentinel ← evidence | read-only ingest | n/a | advisory only; no authority egress |
| all → Vault/KMS | TLS | Vault/KMS auth | unreachable ⇒ fail closed `<TBD>` |

## Constraints

- No execution host may have a local-fallback authority path in production.
- Sentinel must have **no** authority egress — advisory only.
- ControlPlane is the only component that issues authority.

## Not proven

- Production network segmentation, ingress/egress policy, and mutual-TLS rotation
  at production scale are `<TBD>`.
