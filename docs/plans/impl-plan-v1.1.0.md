# Implementation Plan — v1.1.0: Hardened Foundations

**Sprint Duration:** 3 weeks  
**Branch:** `release/v1.1.0`  
**Spec Reference:** `v1_1_0-hardened-foundations-revised.md`

---

## Overview

This plan translates the revised v1.1.0 spec into a sequenced set of engineering tasks. Work is organized into three parallel lanes during Week 1 (quality debt), then two sequential milestones for Weeks 2–3 (RBAC + scopes, then integration tests + canary rollout).

---

## Prerequisites

Before any sprint work begins, the following must be confirmed:

- [ ] `SYNDICATECLAW_RBAC_ENFORCEMENT_ENABLED` is currently set to `false` in all environments
- [ ] Shadow mode logs (`rbac.shadow_decision`) are being emitted and queryable in staging
- [ ] CI pipeline has access to a vault/secret manager for Postgres credentials (no hardcoded passwords)
- [ ] A test PostgreSQL 16 instance is available for the CI service container
- [ ] Code owners have agreed on the permission vocabulary: singular resource form (`workflow:read`, not `workflows:read`)

---

## Week 1 — Quality Debt Elimination

### Track A: Ruff Lane

**Owner:** 1 engineer  
**Goal:** `ruff check src tests` exits 0

**Tasks:**

1. Run `ruff check src tests --output-format=json > ruff_errors.json` to inventory all violations.
2. Run `ruff check src tests --fix` to auto-fix safe violations (unused imports, formatting, etc.).
3. Manually fix remaining violations that ruff cannot auto-fix (type annotations in wrong position, f-string misuse, etc.).
4. Commit as a single atomic commit: `chore: ruff clean pass`.
5. Add the `quality_gate` CI job to `.gitlab-ci.yml` (or equivalent):
   ```yaml
   quality_gate:
     stage: test
     script:
       - ruff check src tests
       - mypy src
   ```
6. Verify the CI job passes on the ruff-clean commit before proceeding to mypy lane.

**Exit gate:** `ruff check src tests` exits 0; CI `quality_gate` job passes.

---

### Track B: Mypy Lane

**Owner:** 1–2 engineers  
**Goal:** `mypy src` exits 0  
**Dependency:** Start after Track A completes (ruff clean reduces noise).

**Fix order (type-stable):**

1. **Generic return types** — functions returning untyped collections (`list`, `dict` without type params). Fix: add explicit type params.
2. **Return type annotations** — functions missing `-> T` annotations. Fix: add return types; use `-> None` for void functions.
3. **Union narrowing** — `x: str | None` used without None check. Fix: add `if x is not None` guards or use `assert`.
4. **`Any` / `no-return` cleanup** — explicit `Any` usages, missing `NoReturn` on fatal functions. Fix: narrow types or document intentional `Any` with `# type: ignore[misc]` + comment.

**Per-fix discipline:** Run `pytest tests/ -q --tb=line` after each batch of fixes. Fail fast on any regression before merging.

**Commit:** `chore: mypy clean pass`

**Exit gate:** `mypy src` exits 0; full pytest suite exits 0.

---

### Track C: Test Infrastructure Setup

**Owner:** 1 engineer  
**Goal:** Shared integration test fixtures ready before Week 2 RBAC work begins  
**Dependency:** Can start Day 1 in parallel with Tracks A and B.

**Tasks:**

1. Create `tests/conftest.py` with all shared fixtures defined in spec §6.3:
   ```python
   @pytest.fixture(scope="session")
   async def db_engine():
       engine = create_async_engine(settings.database_url, ...)
       yield engine
       await engine.dispose()

   @pytest.fixture
   async def db_session(db_engine):
       async with db_engine.begin() as conn:
           yield conn
           await conn.rollback()  # rolls back after each test

   @pytest.fixture
   def test_actor() -> str:
       return "test-actor-operator"

   @pytest.fixture
   def admin_actor() -> str:
       return "test-actor-admin"

   @pytest.fixture(autouse=False)
   def rbac_disabled(monkeypatch):
       monkeypatch.setenv("SYNDICATECLAW_RBAC_ENFORCEMENT_ENABLED", "false")
   ```

2. Verify `pytest-asyncio` is installed with `asyncio_mode = "auto"` in `pyproject.toml`.
3. Verify `factory-boy` is in dev dependencies.
4. Verify `httpx[asyncio]` is available for `AsyncClient` tests.
5. Create a `tests/factories.py` module with `factory_boy` factories for: `WorkflowDefinition`, `WorkflowRun`, `PolicyRule`, `AuditEvent`, `ApprovalRequest`, `ApiKey`.
6. Add the integration test CI job to the pipeline (credentials via vault secret):
   ```yaml
   integration_tests:
     stage: test
     services:
       - postgres:16
     variables:
       POSTGRES_USER: syndicateclaw
       POSTGRES_DB: syndicateclaw_test
       SYNDICATECLAW_DATABASE_URL: postgresql+asyncpg://syndicateclaw:${POSTGRES_PASSWORD}@postgres:5432/syndicateclaw_test
       SYNDICATECLAW_RBAC_ENFORCEMENT_ENABLED: "false"
     secrets:
       POSTGRES_PASSWORD:
         vault: ci/syndicateclaw/postgres_password@secret
     script:
       - pytest tests/ -m integration -q --tb=line
   ```

**Exit gate:** `pytest tests/ -m integration -q` passes (even if no integration tests yet; fixture setup must not error).

---

## Week 2 — RBAC Enforcement + API Key Scopes

### Milestone 2.1: Permission Vocabulary Alignment

**Owner:** 1 engineer  
**Time estimate:** 0.5 days

**Tasks:**

1. Create `syndicateclaw/authz/permissions.py` — define the canonical permission vocabulary as a `frozenset[str]`:
   ```python
   PERMISSION_VOCABULARY: frozenset[str] = frozenset({
       "workflow:read", "workflow:create", "workflow:manage",
       "run:read", "run:create", "run:control", "run:replay",
       "approval:read", "approval:decide", "approval:manage",
       "policy:read", "policy:evaluate", "policy:manage",
       "tool:read", "tool:execute", "tool:manage",
       "memory:read", "memory:write", "memory:update", "memory:delete", "memory:manage",
       "audit:read", "audit:export",
       "admin:*",
   })
   ```
2. Search codebase for any use of plural permission strings (`workflows:read`, `runs:create`) and update them to the singular form.
3. Update all test fixtures and hardcoded permission strings.

---

### Milestone 2.2: Route Registry

**Owner:** 1 engineer  
**Time estimate:** 1 day  
**File:** `syndicateclaw/authz/route_registry.py`

**Tasks:**

1. Implement `RouteRegistry` as a dict mapping `(method: str, path_pattern: str)` → `str | None` (permission or `None` for exempt routes):
   ```python
   ROUTE_REGISTRY: dict[tuple[str, str], str | None] = {
       ("GET",  "/api/v1/workflows"):              "workflow:read",
       ("POST", "/api/v1/workflows"):              "workflow:create",
       ("GET",  "/api/v1/workflows/{id}"):         "workflow:read",
       ("PUT",  "/api/v1/workflows/{id}"):         "workflow:manage",
       ("DELETE", "/api/v1/workflows/{id}"):       "workflow:manage",
       # ... all 36 routes from spec §4.2.3 ...
       ("GET",  "/healthz"):                       None,  # exempt
       ("GET",  "/readyz"):                        None,  # exempt
   }

   def get_required_permission(method: str, path: str) -> str | None | Literal["DENY"]:
       """Returns permission string, None (exempt), or DENY (unregistered)."""
       key = (method.upper(), _normalize_path(path))
       if key in ROUTE_REGISTRY:
           return ROUTE_REGISTRY[key]
       return "DENY"  # default for unregistered routes
   ```

2. Implement `_normalize_path(path: str) -> str` to convert concrete paths like `/api/v1/workflows/01ABC` to pattern `/api/v1/workflows/{id}` by replacing ULID-shaped path segments with `{id}`.

3. Write `test_all_registered_routes_have_permissions`: introspect the FastAPI app's route list and assert every non-exempt route has an entry in `ROUTE_REGISTRY`.

4. Write `test_route_registry_permission_strings_valid`: assert every non-None, non-DENY value in `ROUTE_REGISTRY` is a member of `PERMISSION_VOCABULARY`.

---

### Milestone 2.3: RBAC Middleware

**Owner:** 1 engineer  
**Time estimate:** 2 days  
**File:** `syndicateclaw/middleware/rbac.py`

**Tasks:**

1. Implement `RBACMiddleware(BaseHTTPMiddleware)`:
   - Read `SYNDICATECLAW_RBAC_ENFORCEMENT_ENABLED` from settings.
   - If `false`: emit `WARN` log per request (`rbac.enforcement_disabled`); check if env is non-dev/test and emit `ERROR` if so. Call `call_next` directly.
   - If `true`:
     1. Extract actor from request (via `get_current_actor` dependency or re-implementing the same logic for middleware context).
     2. Call `get_required_permission(request.method, request.url.path)`.
     3. If `DENY` (unregistered route): return `JSONResponse({"detail": "Forbidden"}, status_code=403)`.
     4. If `None` (exempt): call `call_next`.
     5. If permission string: call `rbac_evaluator.evaluate(actor, permission)`.
     6. If `DENY`: return `JSONResponse({"detail": "Forbidden"}, status_code=403)` — **do not call policy engine**.
     7. If `ALLOW`: call `call_next` (policy engine check happens inside route handlers).

2. Implement RBAC + policy engine interaction contract (documented in spec §4.2.2):
   - The RBAC middleware blocks at step 6 before `call_next` — the policy engine inside `ToolExecutor` is only reached if RBAC passes.
   - Add a unit test verifying `policy_engine.evaluate` is not called when RBAC denies (via `unittest.mock.patch`).

3. Register `RBACMiddleware` in `syndicateclaw/api/main.py` **after** `RequestIDMiddleware` and **before** `AuditMiddleware`.

4. Write all RBAC enforcement tests from spec §10.1.

---

### Milestone 2.4: API Key Scopes

**Owner:** 1 engineer  
**Time estimate:** 2 days

**Sub-tasks:**

**2.4.1 Migration**

File: `migrations/versions/006_api_key_scopes.py`

```python
def upgrade():
    op.add_column(
        "api_keys",
        sa.Column(
            "scopes",
            postgresql.ARRAY(sa.TEXT()),
            server_default="{}",
            nullable=False,
            comment="Empty array intentionally grants full access for v1.0 backward compatibility. See §4.3.2 of v1.1.0 spec."
        )
    )

def downgrade():
    op.drop_column("api_keys", "scopes")
```

**2.4.2 ApiKeyService Updates**

File: `syndicateclaw/services/api_key_service.py`

1. Update `create_api_key(actor, scopes: list[str] | None = None)`:
   - If `scopes` is provided: validate max 50 items; reject any scope containing `*`, `?`, `[`, `]`; validate all scopes are in `PERMISSION_VOCABULARY`; enforce privilege ceiling (actor cannot grant scopes they don't have).
   - Store `scopes` on the `api_keys` row.

2. Update `verify_api_key(key)`:
   - Load `scopes` from the `api_keys` row.
   - If `scopes` is empty (`[]`): emit `WARN` log `api_key.unscoped key_id=<> actor=<>`; set `request.state.unscoped_key = True`.
   - If `scopes` is set: attach to request context for downstream scope-checking.

3. Update internal scope matching: use `fnmatch.fnmatch(requested_permission, scope)` to match `admin:*` against specific permissions. This is platform-internal only; clients cannot submit globs.

**2.4.3 `GET /api/v1/api-keys/scopes` endpoint**

File: `syndicateclaw/api/routes/api_keys.py`

```python
@router.get("/api/v1/api-keys/scopes")
async def list_scopes(actor: str = Depends(get_current_actor)):
    # Requires any authenticated principal (no specific scope)
    # Returns PERMISSION_VOCABULARY as sorted list
    return {"scopes": sorted(PERMISSION_VOCABULARY)}
```

Register in route registry with `None` permission (requires auth but no specific scope).

**2.4.4 Tests**

Write all API key scope tests from spec §10.2.

---

### Milestone 2.5: Deprecation Machinery

**Owner:** 1 engineer  
**Time estimate:** 0.5 days

1. Add `SYNDICATECLAW_ALLOW_UNSCOPED_KEYS` to `Settings` (default `true`).
2. In `verify_api_key`: if `ALLOW_UNSCOPED_KEYS=false` and key has empty scopes, return 401 with body `{"detail": "unscoped_key_not_permitted", "upgrade_guide": "..."}`.
3. Add this env var to `GET /api/v1/api-keys/scopes` response for documentation: `"unscoped_keys_allowed": settings.allow_unscoped_keys`.

---

## Week 3 — Integration Tests + Canary Rollout

### Milestone 3.1: Integration Test Suite

**Owner:** 2 engineers  
**Time estimate:** 3 days  
**Dependency:** CI integration test job from Track C must be running.

**Parallel assignments:**

**Engineer A — Policy, Audit, Approval modules:**

Files: `tests/integration/test_policy_engine.py`, `tests/integration/test_audit_service.py`, `tests/integration/test_approval_service.py`

Write integration tests to achieve ≥85% coverage on policy and audit modules, ≥80% on approval module. Focus areas per spec §6.2:

- Policy: rule matching (ALLOW/DENY/REQUIRE_APPROVAL), condition evaluation, fail-closed behavior (no rules → DENY), CRUD with audit trail
- Audit: append-only constraint (no `UPDATE`/`DELETE` SQL ever executed on `audit_events`), HMAC signing on `details`, DLQ behavior on write failure, query filters (actor, resource_type, date range)
- Approval: lifecycle transitions (PENDING → APPROVED/REJECTED/EXPIRED), assignee enforcement, self-approval prevention (`approver == requested_by` → 403), expiration via `expire_stale()`

**Engineer B — RBAC/Authz, Tool Executor, Memory modules:**

Files: `tests/integration/test_authz.py`, `tests/integration/test_tool_executor.py`, `tests/integration/test_memory_service.py`

Write integration tests to achieve ≥80% coverage on each module. Focus areas:

- RBAC/Authz: principal resolution, permission evaluation against route registry, RBAC DENY + policy engine not called, `admin:*` wildcard coverage
- Tool Executor: policy gate (DENY/ALLOW/REQUIRE_APPROVAL), RBAC gate (check `system:engine` service account permissions), sandbox enforcement, timeout, decision ledger requirement (ledger unavailable → deny)
- Memory: CRUD operations, provenance tracking, access policy enforcement (`owner_only`, `system_only`, `restricted`), namespace isolation, Redis cache hit/miss, TTL/retention

**Shared:** All integration tests must use the `rbac_disabled` fixture from `conftest.py` to prevent RBAC from interfering with service-level tests.

---

### Milestone 3.2: Route Registry Coverage Test

**Owner:** 1 engineer  
**Time estimate:** 0.5 days

Write `tests/test_route_registry_coverage.py`:

```python
def test_all_registered_routes_have_permissions(app: FastAPI):
    """Every route in the FastAPI app must have an entry in ROUTE_REGISTRY."""
    from syndicateclaw.authz.route_registry import ROUTE_REGISTRY
    app_routes = {
        (r.methods.pop(), r.path)
        for r in app.routes
        if hasattr(r, "methods") and r.path not in ("/healthz", "/readyz", "/docs", "/redoc", "/openapi.json")
    }
    missing = app_routes - set(ROUTE_REGISTRY.keys())
    assert not missing, f"Routes missing from registry: {missing}"
```

This test gates the entire release — it must pass before staging deployment.

---

### Milestone 3.3: Shadow Log Parity Analysis (Staging)

**Owner:** Platform engineer + release manager  
**Time estimate:** 2 days (48-hour observation window)

**Steps:**

1. Deploy v1.1.0 candidate to staging with `SYNDICATECLAW_RBAC_ENFORCEMENT_ENABLED=false`.
2. Generate representative traffic against staging (replay recent production request patterns or use a synthetic load test).
3. Query shadow decision logs: `SELECT * FROM audit_events WHERE event_type = 'rbac.shadow_decision' AND details->>'enforcement_would_have' = 'DENY' AND created_at > NOW() - INTERVAL '48 hours'`.
4. If any shadow DENY is unexpected: investigate, fix the route registry or permission assignment, re-deploy, restart observation window.
5. If zero unexpected DENYs over 48 hours: proceed to canary.

**Exit gate:** Zero shadow-vs-enforcement disagreements over 48 hours. Document results in a release sign-off artifact.

---

### Milestone 3.4: Canary Rollout

**Owner:** Platform engineer  
**Time estimate:** 7 days post-release

**Steps:**

1. Deploy v1.1.0 to production with `SYNDICATECLAW_RBAC_ENFORCEMENT_ENABLED=false` initially.
2. Enable enforcement for 10% of traffic via feature flag (load balancer routing or header-based canary):
   - If using a feature flag service: set `rbac_enforcement = true` for 10% of actors.
   - If not: deploy a second instance with enforcement on and route 10% there.
3. Monitor for 7 days:
   - Watch for unexpected 403s in access logs.
   - Watch for `rbac.enforcement_disabled` WARN logs (should only appear on the 90% cohort).
   - Watch for any `rbac.shadow_decision` disagreements.
4. If zero issues: promote to 100%.
5. Canary rollback: flip the feature flag or traffic weight back to 0% enforcement instantly.

---

### Milestone 3.5: Shadow Log Deletion (Post-v1.2.0, Gated)

**This is NOT part of the v1.1.0 sprint — it is a separate action after v1.2.0 pre-release.**

Steps when the gate is reached:
1. Confirm enforcement has been at 100% for ≥7 days with zero incidents.
2. Get explicit security review sign-off.
3. Run: `DELETE FROM audit_events WHERE event_type = 'rbac.shadow_decision'` in a transaction with a row count check before committing.
4. Remove shadow-mode logging code from `syndicateclaw/authz/evaluator.py`.

---

## File Map

| File | Action | Description |
|------|--------|-------------|
| `syndicateclaw/authz/permissions.py` | **Create** | Canonical `PERMISSION_VOCABULARY` frozenset |
| `syndicateclaw/authz/route_registry.py` | **Create** | `ROUTE_REGISTRY` dict + `get_required_permission()` |
| `syndicateclaw/middleware/rbac.py` | **Create** | `RBACMiddleware` with enforcement toggle |
| `syndicateclaw/api/main.py` | **Modify** | Register `RBACMiddleware` in stack |
| `syndicateclaw/config.py` | **Modify** | Add `rbac_enforcement_enabled`, `allow_unscoped_keys` settings |
| `syndicateclaw/services/api_key_service.py` | **Modify** | Add scope validation, privilege ceiling, unscoped WARN |
| `syndicateclaw/api/routes/api_keys.py` | **Modify** | Add `GET /api/v1/api-keys/scopes` endpoint |
| `migrations/versions/006_api_key_scopes.py` | **Create** | Add `scopes TEXT[]` column with intentional full-access default |
| `tests/conftest.py` | **Create** | Shared integration test fixtures |
| `tests/factories.py` | **Create** | factory-boy factories for all models |
| `tests/integration/test_policy_engine.py` | **Create** | Policy integration tests (≥85% coverage) |
| `tests/integration/test_audit_service.py` | **Create** | Audit integration tests (≥85% coverage) |
| `tests/integration/test_approval_service.py` | **Create** | Approval integration tests (≥80% coverage) |
| `tests/integration/test_authz.py` | **Create** | RBAC/authz integration tests (≥80% coverage) |
| `tests/integration/test_tool_executor.py` | **Create** | Tool executor integration tests (≥80% coverage) |
| `tests/integration/test_memory_service.py` | **Create** | Memory service integration tests (≥75% coverage) |
| `tests/test_route_registry_coverage.py` | **Create** | Programmatic route coverage check |
| `.gitlab-ci.yml` | **Modify** | Add `quality_gate` job; add `integration_tests` job with vault secrets |

---

## Definition of Done

- [ ] `ruff check src tests` exits 0 in CI
- [ ] `mypy src` exits 0 in CI
- [ ] `pytest tests/ -q` exits 0 (no regressions)
- [ ] `SYNDICATECLAW_RBAC_ENFORCEMENT_ENABLED=true` is the new default in `Settings`
- [ ] All 36 routes in the registry; `test_all_registered_routes_have_permissions` passes
- [ ] Permission vocabulary is singular throughout; `test_route_registry_permission_strings_valid` passes
- [ ] RBAC DENY wins; policy engine not consulted on RBAC deny (mock test passes)
- [ ] Unscoped API keys emit WARN log on use
- [ ] `GET /api/v1/api-keys/scopes` returns sorted permission list; requires authentication
- [ ] API key scope validation: max 50, no globs, privilege ceiling enforced
- [ ] Integration test coverage ≥80% for all six modules (coverage.py report attached to release)
- [ ] CI `quality_gate` job fails on any lint/type debt
- [ ] CI `integration_tests` job uses vault-injected credentials (no hardcoded passwords)
- [ ] Shadow parity analysis: zero disagreements over 48h staging run
- [ ] Canary 10%→100% rollout plan documented and confirmed before deployment
- [ ] Upgrade guide written and merged before release tag
