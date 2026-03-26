# ADR 0001: RBAC enforcement vs shadow mode

## Status

Deferred

## Context

Phase 1 ran `ShadowRBACMiddleware` after each request to compare RBAC decisions
with legacy HTTP-based authorization without blocking traffic.

## Decision

- Default remains **shadow mode** (`SYNDICATECLAW_RBAC_ENFORCEMENT_ENABLED=false`).
- Setting **`rbac_enforcement_enabled=True`** runs RBAC before the route handler
  and returns **403** when RBAC denies, principal resolution fails, scope
  resolution fails, or team context validation fails (same cases we classify in
  shadow metrics).

## Consequences

- Operators can enable enforcement per environment once shadow logs show zero
  disagreements on critical routes.
- Pre-handler enforcement duplicates RBAC work with shadow logging when both run;
  typical production uses either shadow-only or enforcement, not both for long.

## Promotion Review

### Review Date
2026-03-26

### Outcome
Deferred. RBAC remains in shadow mode by default
(`SYNDICATECLAW_RBAC_ENFORCEMENT_ENABLED=false`).

### Rationale
- `shadow_evaluations` contains traffic (`42` total records), so there is enough
  data to evaluate promotion readiness.
- Disagreement rate is `100%` (`42/42`), exceeding the <5% threshold.
- All disagreements are `PRINCIPAL_NOT_FOUND`, with legacy `ALLOW` and RBAC
  `DENY` on critical routes (`/api/v1/workflows/`, `/api/v1/tools/`,
  `/api/v1/memory/`, `/api/v1/audit/`).
- Promoting enforcement now would block existing traffic where principals are not
  yet provisioned in RBAC identity tables.
