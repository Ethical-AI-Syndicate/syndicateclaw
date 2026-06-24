# Rollback & Recovery — DRAFT

**Status: DRAFT. Platform NOT SHIPPABLE.**

## Upgrade
- Pin component versions; upgrade ControlPlane first (authority), then Gate, Claw,
  Sentinel. Verify each `/healthz` + a golden-path negative probe between steps.

## Rollback
- Roll back to the previous pinned artifact versions in reverse order
  (Sentinel → Claw → Gate → ControlPlane). `<TBD>` tested procedure.
- The Claw durable audit chain is append-only; rollback must NOT rewrite or
  truncate it. Corrupt/torn tail is fail-closed by design (verify on restart).

## Recovery
- ControlPlane audit chain integrity: run `audit-verify` (exit 0 = intact).
- Claw boundary chain: `DurableAuditChain.verify()` replays from disk; an invalid
  result is fail-closed (deny further side effects until reconciled).

## Post-install / post-upgrade verification
- Re-run startup readiness checks.
- Re-run the golden-path verification command and the negative fail-closed smoke.
- Confirm no release tag was created and no unintended deploy occurred.

## Not proven
Tested rollback, restore-from-backup, and post-install verification at production
scale are `<TBD>`.
