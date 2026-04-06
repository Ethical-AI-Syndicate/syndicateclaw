# ADR 0015: Completeness audit — deferred items (2026-03-27)

## Status Update — 2026-03-28

Items 1, 2, 3, and 5 below have been **resolved**. Item 4 remains open as optional process debt.

| Item | Description | Status |
|------|-------------|--------|
| 1 | Alembic migration drift | **Resolved** — idempotent guards added to migrations 014–021; `alembic_version` widened; `026_drop_stale_wf_uq` added. |
| 2 | Memory coverage below ≥75% | **Resolved** — `syndicateclaw.memory/` now at 75.7% (PASS). |
| 3 | Inference coverage below ≥80% | **Resolved** — `syndicateclaw.inference/` now at 80.8% (PASS). |
| 4 | Skipped tests governance | **Resolved** — all non-pentest/chaos skips and xfails updated with explicit `Unskip: vX.Y` version targets. Pentest/chaos skips remain intentionally conditional. |
| 5 | ADR 0001 vs `Settings` RBAC default | **Resolved** — ADR 0001 updated with status note (2026-03-27). |

All per-module coverage targets now pass. See `COVERAGE_DELTA.md` for current numbers.

---

## Status

Accepted deferral (original 2026-03-27; see update above)

## Context

A full v1.0.0 → v1.1.0 completeness and integration audit was executed. Several items could not be closed in a single session without risking rushed tests or unsafe database operations.

## Deferred items

1. **Alembic / database state:** `alembic check` may fail when the target database is not at revision head, or when manual schema and migration history diverge (e.g. duplicate tables on `upgrade`). Resolution requires operator-controlled DB repair or a clean migration path — not a pure code change.

2. **Memory module coverage:** Measured package coverage is below the ≥75% target. Closing the gap needs additional integration tests around read/write paths, cache policy, and guardrails.

3. **Inference module coverage:** Measured package coverage is below the ≥80% target. Priority files include `inference/service.py` and provider HTTP adapters.

4. **Skipped tests governance:** Not every `@pytest.mark.skip` / `xfail` carries a tracked ticket ID and explicit unskip deadline per audit policy. Pentest and chaos suites remain intentionally conditional.

5. **ADR vs `Settings` default for RBAC:** Code uses `rbac_enforcement_enabled: bool = Field(default=True, ...)`. ADR 0001 narrative references historical shadow-default behavior. Product/security should reconcile documentation and defaults explicitly.

## Decision

Defer the above to subsequent v1.1.x work with tracked issues; do not block shipping registry and static-analysis fixes completed in the audit session.

## Consequences

All five deferred items are now resolved as of 2026-03-28. No open deferred work remains from this audit.
