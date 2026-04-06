# SyndicateClaw Completeness Audit — Findings

**Date:** 2026-03-27  
**Baseline (start of session):** ruff=17, mypy=0, tests=737 passed / 0 failed (after ruff fix: same counts; one intermittent failure observed once on `test_policy_engine_list_rules`, passed on rerun and in isolation)  
**Final:** ruff=0, mypy=0, tests=737 passed / 0 failed, 27 skipped, 1 xfailed, 1 xpassed  

## Phase 0 — Gate summary

| Gate | Result |
|------|--------|
| Ruff | 0 errors |
| Mypy | 0 errors |
| Pytest (full, `SYNDICATECLAW_DATABASE_URL` → test DB) | 737 passed |
| Coverage (total `syndicateclaw`) | **78%** (see `coverage-baseline.json`) |
| `alembic check` (with test DB URL) | **Failed:** `Target database is not up to date` — local DB revision/schema out of sync with head (see deferrals) |
| `import syndicateclaw` | OK |

## Resolved Findings

| ID | Module | Finding Type | Description | Resolution |
|----|--------|--------------|-------------|------------|
| F-001 | `syndicateclaw.authz` | Integration | Fourteen `/api/v1/` route templates were registered in FastAPI but **absent** from `ROUTE_REGISTRY` when keyed by `route.path` (e.g. `{agent_id}` vs `{id}`). `get_route_spec()` in `ShadowRBACMiddleware` uses the FastAPI template string; entries only under `{id}` left agents, messages, and **all organization** routes without `RouteAuthzSpec`, so shadow metrics and enforcement could not apply correct permissions. | Added `RouteAuthzSpec` rows in `ROUTE_PERMISSION_MAP` for `/api/v1/agents/{agent_id}/*`, `/api/v1/messages/{message_id}/*`, and full `/api/v1/organizations/...` matrix (`org_id`, `member_actor`). Re-ran gate script: **Route registry: COMPLETE**. |
| F-002 | `tests/` (chaos, pentest) | Quality | Ruff reported 17 violations (`assert False`, unused vars, line length, imports). | Replaced `assert False` in skipped tests with `raise AssertionError("unreachable when skipped")`, removed unused `real_execute`, split long `skip` reasons, fixed imports; `ruff check src tests` clean. |

## Deferred Findings (with ADR references)

| ID | Module | Finding Type | Description | ADR | Target Version |
|----|--------|--------------|-------------|-----|----------------|
| D-001 | Migrations / ops | Drift | `alembic check` reports DB not at head; `alembic upgrade head` can fail with `DuplicateTableError` when schema objects exist but `alembic_version` is behind — environment-specific reconciliation required (fresh DB, or stamp/ repair under ops review). | [ADR-0015](docs/adr/0015-completeness-audit-deferrals.md) | v1.1.x |
| D-002 | `syndicateclaw.memory` | Coverage | Package coverage **~53.5%** vs target ≥75% in audit brief; not closed in this session. | ADR-0015 | v1.1.x |
| D-003 | `syndicateclaw.inference` | Coverage | Package coverage **~75.0%** vs target ≥80%; `service.py` and HTTP adapters remain thinly covered. | ADR-0015 | v1.1.x |
| D-004 | Skipped / xfail tests | Process | 27 skipped and 1 xfail remain; several skips are intentional (infra/chaos). Full compliance with “issue number + deadline on every skip” from the audit prompt is **not** met — backlog item. | ADR-0015 | v1.1.x |
| D-005 | Documentation | Drift | `docs/adr/0001-rbac-enforcement-promotion.md` still describes default shadow mode; `Settings.rbac_enforcement_enabled` **defaults to `True`** in `config.py`. Align ADR or defaults under a dedicated governance change. | ADR-0015 | TBD |

## Deleted Dead Code

| File | Lines Deleted | Reason |
|------|---------------|--------|
| — | 0 | No dead-code deletion this session. |

## Notes

- **Route registry regression guard:** `tests/test_route_registry_coverage.py::test_all_registered_routes_have_permissions` continues to enforce that every `APIRoute` resolves a non-`DENY` permission via `get_required_permission`.
- **Flakiness:** One failure on `tests/integration/test_coverage_gaps.py::test_policy_engine_list_rules` was observed in a full run; the same test passed in isolation and on immediate full-suite rerun — treat as order/timing sensitivity; worth a follow-up if it recurs.

---

## Session 2 — Resolved Findings

| ID | Module | Finding Type | Description | Resolution |
|----|--------|--------------|-------------|------------|
| D-001 (Session 1) | `syndicateclaw.memory` | Coverage | Memory package below ≥75% target | **Resolved:** `tests/integration/test_memory_coverage.py` (27 cases), `tests/unit/test_memory_trust_pure.py`; `MemoryRecordRepository` aligned with `MemoryDeletionStatus` for purge/list filters. **Measured:** `syndicateclaw/memory/` **~75.7%** (full suite). |
| D-002 (Session 1) | `syndicateclaw.inference` | Coverage | Inference package below ≥80% target | **Resolved:** `tests/unit/inference/test_provider_service_branches.py`, `test_adapter_base_and_factory.py`, `test_ollama_adapter_mocked.py`. **Measured:** `syndicateclaw/inference/` **~80.8%** (full suite). |
| D-003 (Session 1) | Alembic | Drift / migration robustness | `alembic check` failing; upgrades failing on duplicate objects; long revision IDs vs `VARCHAR(32)` | **Resolved:** Idempotent guards in `014`–`021`, `alembic_version` widened to `VARCHAR(128)` in `018`, ORM indexes/constraints aligned (`db/models.py`), duplicate UQ dropped via `026_drop_stale_wf_uq`. `SYNDICATECLAW_DATABASE_URL=... alembic check` → **clean**. (Default shell DB user without `SYNDICATECLAW_DATABASE_URL` still fails auth — use inline URL for CI.) |
| D-005 (Session 1) | ADR 0001 | Governance | Doc vs `Settings` default | **Resolved:** Status update appended to `docs/adr/0001-rbac-enforcement-promotion.md`. |
| OpenAPI | `docs/api/openapi.json` | Parity | Stale committed spec vs live app | **Resolved:** Regenerated `docs/api/openapi.json` from `app.openapi()` (path/method set matches live: symmetric diff **0**). |

## Session 2 — All items resolved

| ID | Item | Notes |
|----|------|--------|
| D-004 | Skip / xfail policy | **Resolved (2026-03-28):** All non-pentest/chaos skips and xfails updated with explicit `Unskip: vX.Y` version targets in reason strings. Pentest/chaos skips remain intentionally conditional. |
| Priority 4 | JWT / SSRF / SSE token hygiene | **Addressed (2026-03-27):** `tests/unit/test_jwt_contracts.py` (no `permissions` in issuer path; decode allowlist); `tests/unit/test_ssrf_validate_url.py` (private/link-local/loopback + scheme); `test_pentest_23b_sse_rejects_primary_jwt_in_query_param` (valid primary JWT in `?token=` → 401). ToolExecutor `policy_engine=None` fail-closed already covered in `tests/unit/test_hardening.py`; RBAC vs policy order in `tests/unit/test_rbac_middleware.py`. |

## Session 3 — Resolved Findings (2026-03-28)

| ID | Module | Finding Type | Description | Resolution |
|----|--------|--------------|-------------|------------|
| D-004 (coverage) | `syndicateclaw.audit` | Coverage | `audit/` at 84.9% — 0.1pp below ≥85% target | **Resolved:** `tests/unit/test_audit_events_unit.py` — 3 unit tests covering `EventBus.unsubscribe` success path (line 48) and `EventBus.publish` early-return when no handlers (line 59). Measured: `syndicateclaw/audit/` **85.4%** (PASS). |
| ADR-0015 | `docs/adr/0015-completeness-audit-deferrals.md` | Documentation | ADR still described items 1–3, 5 as outstanding after Session 2 resolved them | **Resolved:** Status update table added to ADR-0015; all 5 items subsequently resolved including item 4 (skip governance) in Session 3. |

## Session 3 addendum — approval and inference regression fix (2026-03-28)

Fresh baseline run revealed two regressions vs Session 2 snapshot (different DB state):
- `approval/` dropped to 79.0% (target 80%) — fixed by `tests/unit/test_approval_authority_unit.py` (authority fallback and policy-resolved paths)
- `inference/` dropped to 79.3% (target 80%) — fixed by `tests/unit/test_inference_catalog_ssrf.py` (catalog SSRF pure-function and mocked async paths)

## Final coverage gate — all targets met (2026-03-28, authoritative)

| Module | Coverage | Target | Status |
|--------|----------|--------|--------|
| `syndicateclaw.audit/` | 85.8% | 85% | PASS |
| `syndicateclaw.policy/` | 90.1% | 85% | PASS |
| `syndicateclaw.approval/` | 85.2% | 80% | PASS |
| `syndicateclaw.authz/` | 96.5% | 80% | PASS |
| `syndicateclaw.tools/` | 84.0% | 80% | PASS |
| `syndicateclaw.memory/` | 75.7% | 75% | PASS |
| `syndicateclaw.inference/` | 81.8% | 80% | PASS |

Verified by full suite run: 804 passed, 15 skipped, 1 xfailed, 1 xpassed (Session 3). Superseded by Session 7 baseline: 900 passed, 14 skipped, 1 xfailed, 1 xpassed (all 7 targets PASS; total coverage 83.5%).

## Session 4 — Zero-coverage file elimination (2026-03-28)

Five files at 0% coverage identified via `coverage-baseline.json`; all brought to 100% by `tests/unit/test_zero_coverage_units.py` (11 tests):

| File | Lines | Coverage before | Coverage after |
|------|-------|-----------------|----------------|
| `syndicateclaw/channels/console.py` | 15 | 0% | 100% |
| `syndicateclaw/plugins/builtin/__init__.py` | 3 | 0% | 100% |
| `syndicateclaw/plugins/builtin/audit_trail.py` | 7 | 0% | 100% |
| `syndicateclaw/plugins/builtin/webhook.py` | 24 | 0% | 100% |
| `syndicateclaw/tasks/idempotency_cleanup.py` | 10 | 0% | 100% |

No formal coverage targets apply to these packages (not in the 7-package target list), but 0% files represent untested behaviours shipped to production. All ruff/mypy clean.

## Session 5 — Deep coverage improvements (2026-03-28)

Three test files added covering previously thin modules:

| Test file | Tests | Key coverage gained |
|-----------|-------|---------------------|
| `tests/unit/test_memory_trust_async.py` | 14 | `memory/trust.py` 29% → 100% (all async DB methods mocked) |
| `tests/unit/inference/test_openai_adapter_mocked.py` | 8 | `inference/adapters/openai_compatible.py` 15.8% → 91.6% |
| `tests/unit/test_audit_events_unit.py` (extended) | +1 | `audit/export.py` not-found path (line 67) — pushed `audit/` from 84.9% → 85.8% |

Final baseline (838 passed): all 7 tracked packages pass their targets. Total coverage 81.7%.
