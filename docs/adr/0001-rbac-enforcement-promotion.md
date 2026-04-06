# ADR 0001: RBAC enforcement vs shadow mode

## Status Update — 2026-03-27

`rbac_enforcement_enabled` defaults to **`True`** in `syndicateclaw/config.py` as of the v1.1.0 completeness audit. The RBAC route registry has been extended to cover agent, message, and organization routes (FastAPI path templates such as `{agent_id}` / `{org_id}`).

**Outstanding before RBAC is fully validated in production:**

- Principal provisioning path must be implemented for every actor that should pass enforcement (see options in the original ADR body).
- Principals must be seeded for all existing actors.
- Shadow evaluator should show fewer than 5% `ROUTE_UNREGISTERED` disagreements and 0% `PRINCIPAL_NOT_FOUND` before treating enforcement as validated in a given environment.

The enforcement flag defaults to `True` in code; integration tests set `SYNDICATECLAW_RBAC_ENFORCEMENT_ENABLED=false` via fixtures. That is intentional — tests opt out of pre-handler enforcement unless explicitly testing it.

---

## Status

Deferred

## Context

Phase 1 ran `ShadowRBACMiddleware` after each request to compare RBAC decisions
with legacy HTTP-based authorization without blocking traffic.

## Decision

- **Original intent (Phase 1):** default **shadow mode** (`SYNDICATECLAW_RBAC_ENFORCEMENT_ENABLED=false`) so traffic was not blocked while shadow metrics were collected.
- **Code default (2026-03-27):** `Settings.rbac_enforcement_enabled` defaults to **`True`** in `config.py` — see **Status Update — 2026-03-27** above. Operators who need shadow-only behavior must set `SYNDICATECLAW_RBAC_ENFORCEMENT_ENABLED=false` explicitly.
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
Deferred for **operational promotion** (principals not ready; disagreement rate high). The application **defaults** `rbac_enforcement_enabled` to **`True`** in code; use `SYNDICATECLAW_RBAC_ENFORCEMENT_ENABLED=false` for shadow-only until ready — see Status Update at top of this ADR.

### Rationale
- `shadow_evaluations` contains traffic (`42` total records), so there is enough
  data to evaluate promotion readiness.
- Disagreement rate is `100%` (`42/42`), exceeding the <5% threshold.
- All disagreements are `PRINCIPAL_NOT_FOUND`, with legacy `ALLOW` and RBAC
  `DENY` on critical routes (`/api/v1/workflows/`, `/api/v1/tools/`,
  `/api/v1/memory/`, `/api/v1/audit/`).
- Promoting enforcement now would block existing traffic where principals are not
  yet provisioned in RBAC identity tables.
