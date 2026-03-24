# Phase 1: Shadow Evaluator — Staging Verification Packet

**Date:** 2026-03-24
**Environment:** staging (`syndicateclaw_staging`, Redis DB 2, port 8002)
**Status:** Shadow mode deployed, comprehensive traffic exercised, disagreements analyzed

---

## 1. Migration

Migration `004_shadow` applied cleanly on top of `003_audit`:

```
INFO  [alembic.runtime.migration] Running upgrade 003_audit -> 004_shadow,
      create shadow_evaluations table for Phase 1 shadow mode
```

Table verified with expected columns, types, and indexes.

---

## 2. Bugs Found and Fixed During Verification

### Bug 1: Structlog key collision (silent record loss)

The structured log dict contained an `"event"` key that conflicted with structlog's
positional `event` argument. All evaluations were dropped until fixed. The
completeness metric (`expected=6, persisted=0, dropped=6`) exposed this
immediately — exactly the operational proof the metric was designed for.

**Fix:** Removed the `"event"` key from the log data dict.

### Bug 2: Missing `run:*` permissions in role seed

The `viewer` role was missing `run:read` and the `operator` role was missing
`run:create`, `run:control`, `run:replay`. The RBAC design spec explicitly lists
these permissions, but the Phase 0 seed script omitted them. This caused 6
`LEGACY_ALLOW_RBAC_DENY` disagreements on all run operations.

**Fix:** Updated seed script and live role permissions in staging. Flushed Redis
permission cache.

### Bug 3: Legacy decision misclassifying 404 as authorization denial

The `_evaluate_legacy` method treated any `status_code >= 400` (including 404 for
nonexistent resources, 422 for validation errors) as DENY. This conflated "resource
not found" with "access denied" and produced 12 false `LEGACY_DENY_RBAC_ALLOW`
disagreements.

**Fix:** Legacy classifier now only treats 403 and ownership-guarded 404
(`owner_field is not None`) as DENY. Other 4xx codes are classified as ALLOW since
the legacy system did not deny on authorization grounds.

### Bug 4: Route template resolution ambiguity

`/api/v1/workflows/runs` was matching as `/api/v1/workflows/{workflow_id}` (with
`workflow_id=runs`) because the middleware iterated `app.routes` and the
parameterized route appeared first. This produced incorrect route attribution for
the list-runs endpoint.

**Fix:** `_resolve_route_template` now collects all `FULL` matches and prefers
the one with fewest path parameters (most static segments).

### Bug 5: Handler 500 errors skipping shadow evaluation

When a handler raised an exception, Starlette's `BaseHTTPMiddleware` propagated
the error through `call_next`, causing the shadow evaluation code to never
execute. 11 of 59 requests (all returning 500 from pre-existing bugs) were
invisible to the shadow evaluator.

**Fix:** Wrapped `call_next` in a try/except. On handler error, performs shadow
evaluation with a synthetic 500 response before re-raising.

---

## 3. Comprehensive Traffic Results

64 authenticated requests across 4 principals (`user:alice`, `user:bob`,
`admin:ops`, `system:engine`), exercising allow paths, deny paths, ownership
boundaries, admin/non-admin divergence, cross-actor access, and cache behavior.

### Completeness

| Metric | Value |
|---|---|
| `rbac.shadow.expected` | **64** |
| `rbac.shadow.persisted` | **64** |
| `rbac.shadow.dropped` | **0** |
| `missing` | **0** |
| **Completeness** | **100%** |

### Route Coverage

**35 distinct route/method pairs evaluated, covering all 33 protected routes
in the registry.** Zero `ROUTE_UNREGISTERED` disagreements.

### Latency

| Metric | Value |
|---|---|
| Total evaluations | 64 |
| Average | 2,867 µs |
| p50 | 2,543 µs |
| p99 | **7,696 µs** |
| Max | 9,678 µs |

p99 = **7.7 ms**, well under the 10 ms gate.

### Cache Behavior

| Cache | Count |
|---|---|
| Hit | 58 |
| Miss | 6 |
| Hit Rate | **90.6%** |

6 cold-start misses (first evaluation for each of the 4 principals, plus 2
role-permission expansion misses). All subsequent evaluations for the same
principal hit cache.

---

## 4. Disagreement Analysis

### Summary

| Agreement | Disagreement Type | Count |
|---|---|---|
| true | (none) | **51** |
| false | `LEGACY_DENY_RBAC_ALLOW` | 7 |
| false | `LEGACY_ALLOW_RBAC_DENY` | 6 |
| **Total** | | **64** |

### `LEGACY_ALLOW_RBAC_DENY` (6) — RBAC is correctly stricter

These are cases where the legacy system permits an action but RBAC correctly
denies it because the `operator` role does not include the required permission.
All are **correct RBAC behavior per the design spec**.

| Route | Actor | Permission | Why RBAC denies |
|---|---|---|---|
| `POST /approvals/{id}/approve` | user:alice | `approval:decide` | Only `admin` role has this |
| `POST /approvals/{id}/reject` | user:alice | `approval:decide` | Only `admin` role has this |
| `POST /policies/evaluate` | user:alice | `policy:evaluate` | Only `admin`/`policy_manager` has this |
| `PUT /memory/{id}` | user:alice | `memory:update` | Not in `operator` or `viewer` |
| `PUT /memory/{id}` | user:bob | `memory:update` | Not in `operator` or `viewer` |
| `DELETE /memory/{id}` | user:alice | `memory:delete` | Only `admin` role has this |

**Assessment:** These expose real legacy authorization gaps where the legacy system
does not gate by role. They will close automatically at Phase 3 cutover. No action
needed for Phase 1.

### `LEGACY_DENY_RBAC_ALLOW` (7) — Transitional scaffolding is over-broad

These are cases where the legacy system denies access (via ownership checks
returning 404) but RBAC allows because the platform-scope `operator` role
grants broad read/control permissions.

| Route | Actor | Permission | Why legacy denies |
|---|---|---|---|
| `GET /workflows/{id}` | user:bob | `workflow:read` | bob != owner (alice) |
| `GET /workflows/{id}` | user:alice | `workflow:read` | nonexistent workflow |
| `GET /workflows/runs` | user:alice | `run:read` | list endpoint returns 404 (pre-existing bug) |
| `GET /workflows/runs` | user:bob | `run:read` | list endpoint returns 404 (pre-existing bug) |
| `GET /workflows/runs/{id}` | user:bob | `run:read` | bob != initiated_by (alice) |
| `POST /workflows/runs/{id}/pause` | user:bob | `run:control` | bob != initiated_by (alice) |
| `POST /workflows/runs/{id}/replay` | user:bob | `run:replay` | bob != initiated_by (alice) |

**Assessment:** The RBAC evaluator grants platform-scope access because the broad
transitional `operator` assignments do not enforce ownership. This is **expected
behavior under the current scaffolding**. These disagreements will resolve when:
1. Transitional scaffolding is narrowed (Phase 4)
2. RBAC scope resolution becomes resource-owner-aware (Phase 2 namespace boundaries)

### Missing Permission: `memory:update`

The RBAC design spec defines `memory:write` in the `operator` role, but the route
registry uses `memory:update` for `PUT /memory/{record_id}`. The permission
`memory:update` is not in any role. This needs resolution: either the registry
should use `memory:write` for updates, or `memory:update` should be added to
`operator`.

---

## 5. Explanation Detail

Every shadow record includes full RBAC explanation fields:

- **`rbac_matched_assignments`**: JSONB array with `role_name`, `scope_type`,
  `scope_id`, `source` for each matching grant
- **`rbac_deny_reason`**: populated as `"no_matching_grant"` on DENY
- **`rbac_permission_source`**: human-readable (e.g., `"operator @ PLATFORM:platform"`)
- **`principal_id`**: resolved for every actor (100% principal resolution)
- **`resolved_scope_type` / `resolved_scope_id`**: correctly populated

---

## 6. Phase 0 Carry-Forward Invariants

### Transitional scaffolding count: 4

user:alice, user:bob, anonymous, dev-agent — all non-service user principals with
platform-scope `operator`. This is the burn-down baseline for Phase 4 gating.

### Audit denormalization

New audit events continue to populate `actor_principal_id` correctly.

---

## 7. Unit Tests

All 354 unit tests pass after all fixes:

```
354 passed in 3.17s
```

---

## 8. Cleanup Round: Handler Bug Fixes

After the initial traffic analysis, a second round fixed handler-level defects
that were contaminating the disagreement set:

| Fix | Root Cause | Effect |
|---|---|---|
| Route ordering | `GET /workflows/runs` matched as `{workflow_id}=runs` | 2 false `LEGACY_DENY_RBAC_ALLOW` disagreements removed |
| `WorkflowResponse` fields | `description: str` (non-nullable), `nodes`/`edges` rejected dicts | Workflow GET/list 500s eliminated |
| `memory:update` → `memory:write` | Route registry used permission not in any role | 2 false `LEGACY_ALLOW_RBAC_DENY` disagreements removed |
| ORM enum defaults | `status="pending"`, `deletion_status="active"` (lowercase) | Memory/run response validation 500s eliminated |
| Policy evaluate args | Missing `action` parameter in call to `PolicyEngine.evaluate()` | Policy evaluate 500 eliminated |
| Pre-seeded data | `nodes={}`, `effect='deny'`, `memory_type='ephemeral'` (wrong types/cases) | Response validation 500s eliminated |
| Traffic script idempotency | Hardcoded names caused duplicate-key errors on re-run | Repeatable traffic generation |

**Result: zero 500s in the clean run. All 67 requests return valid HTTP statuses.**

---

## 9. Clean Baseline (post-cleanup)

### Completeness

| Metric | Value |
|---|---|
| `rbac.shadow.expected` | **67** |
| `rbac.shadow.persisted` | **67** |
| `rbac.shadow.dropped` | **0** |
| `missing` | **0** |
| **Completeness** | **100%** |

### Route Coverage

**35 distinct route/method pairs covering all 33 protected routes in the registry.**

### Latency

| Metric | Value |
|---|---|
| p99 | **9,088 µs (9.1 ms)** |
| Average | 3,024 µs |
| Total evaluations | 67 |

### Agreement

| Category | Count | % |
|---|---|---|
| Agreement | **57** | 85.1% |
| `LEGACY_ALLOW_RBAC_DENY` (B1: RBAC stricter) | 5 | 7.5% |
| `LEGACY_DENY_RBAC_ALLOW` (B2: scaffolding overbreadth) | 4 | 6.0% |
| `LEGACY_DENY_RBAC_ALLOW` (B2b: not-found semantics) | 1 | 1.5% |

---

## 10. Classified Disagreement Baseline

### Bucket 1: RBAC correctly stricter (5 — expected, will close at cutover)

| Route | Actor | Permission | Why RBAC denies |
|---|---|---|---|
| `POST /approvals/{id}/approve` | user:alice | `approval:decide` | Only `admin` role |
| `POST /approvals/{id}/reject` | user:alice | `approval:decide` | Only `admin` role |
| `DELETE /memory/{id}` | user:alice | `memory:delete` | Only `admin` role |
| `DELETE /memory/{id}` | user:bob | `memory:delete` | Only `admin` role |
| `POST /policies/evaluate` | user:alice | `policy:evaluate` | Only `admin`/`policy_manager` role |

These are real legacy authorization gaps. RBAC correctly restricts operations the
legacy system does not gate by role.

### Bucket 2: Transitional scaffolding overbreadth (4 — expected, will narrow at Phase 4)

| Route | Actor | Permission | Why legacy denies |
|---|---|---|---|
| `GET /workflows/{id}` | user:bob | `workflow:read` | bob ≠ owner |
| `GET /workflows/runs/{id}` | user:bob | `run:read` | bob ≠ initiated_by |
| `POST /workflows/runs/{id}/pause` | user:bob | `run:control` | bob ≠ initiated_by |
| `POST /workflows/runs/{id}/replay` | user:bob | `run:replay` | bob ≠ initiated_by |

RBAC allows because platform-scope `operator` grants broad read/control. Legacy
denies via ownership checks. These will resolve when transitional scaffolding is
narrowed to team-scoped assignments.

### Bucket 2b: Not-found semantics (1 — not an authorization disagreement)

| Route | Actor | Permission | Why legacy denies |
|---|---|---|---|
| `GET /workflows/{id}` | user:alice | `workflow:read` | nonexistent workflow (404) |

Legacy returns 404 because the resource does not exist. RBAC evaluates the
abstract permission and allows. This is a resource-absence vs access-control
distinction, not a true overbreadth case. Excluded from the authorization
disagreement baseline.

### Bucket 3: Non-auth defects contaminating signal

**Zero.** All handler 500s have been fixed. No disagreements are caused by route
bugs, response validation failures, or data quality issues.

---

## 11. Observation Window

Per the Phase 1 spec, completion requires 7 consecutive days of:

- `persisted / expected >= 99.9%`
- Zero unresolved `ROUTE_UNREGISTERED` disagreements
- p99 added latency < 10 ms

| Day | Expected | Persisted | Dropped | Missing | Agree | B1 (stricter) | B2 (overbreadth) | B2b (not-found) | B3 (noise) | p99 (µs) | Routes | Scaffolding |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-03-24 | 67 | 67 | 0 | 0 | 57 | 5 | 4 | 1 | 0 | 9,088 | 35/33 | 4 |

---

## 12. Verdict

**Phase 1 shadow mode is operational with a clean disagreement baseline.**

The verification produced two rounds of fixes:

**Round 1 (shadow infrastructure):** 5 bugs in the shadow evaluator itself —
structlog collision, missing permissions, legacy classifier, route resolution,
handler-error blind spot.

**Round 2 (handler cleanup):** 7 fixes to pre-existing handler defects that were
contaminating legacy decision data — route ordering, response model validation,
ORM defaults, policy evaluate args, pre-seeded data quality.

The result is a clean signal: 10 disagreements split evenly into two
well-understood buckets, zero noise from handler bugs, 100% completeness, and
p99 under the 10 ms gate.

The 7-day observation window begins on a clean foundation.
