# Install Smoke Test — DRAFT

**Status: DRAFT. Platform NOT SHIPPABLE.** Commands are placeholders until
versioned install artifacts exist (install-from-source is not a client-install proof).

## 1. Provision dependencies
- PostgreSQL, Redis, Vault/KMS reachable; tenant/project/workspace scope chosen.

## 2. Install components (from versioned artifacts — `<TBD>`)
```
# helm install controlplane-enterprise <chart-version> ...        # <TBD>
# deploy gate, claw, sentinel from pinned images                  # <TBD>
# configure SYNDICATE_CP_ENDPOINT + trust anchor on each host
```

## 3. Startup readiness checks
- ControlPlane reachable + healthy (`/healthz`), mTLS handshake succeeds.
- Vault/KMS reachable + scoped credential lookup works `<TBD>`.
- Claw refuses to start in any mode that would self-authorize.
- Durable audit ledger path is writable + fsync-capable.
- Each host rejects execution when ControlPlane is unreachable (fail-closed probe).

## 4. Golden-path verification command
```
# from the integration workspace:
bash integration/run-enterprise-golden-path.sh
bash scripts/validate-golden-path-evidence.sh "<bundle-dir>"
```
Current result: chain executes through all five boundaries; the **Claw durable
real-executor contract is not yet closed** (see readiness-checklist.md). NOT a pass.

## 5. Negative fail-closed smoke
- Revoke/expire a permit → execution denied before side effect.
- Stop ControlPlane → execution denied.
- Tenant/actor mismatch → denied.

## Not proven
Clean-environment install from versioned artifacts and a green
`validate-golden-path-evidence.sh` are `<TBD>`.
