# RBAC Implementation Plan

Derived from `docs/rbac-design.md`. This document defines the schema changes, implementation phases, shadow-mode metrics, and rollback criteria for Gate 2 RBAC.

All section references (e.g., "Decision 2", "Rule A") refer to the RBAC design spec.

---

## Phase 0: Data Model and Migrations

**Goal**: All new tables exist, owning-scope columns are populated, no behavioral change.

### 0.1 New tables

Create an Alembic migration adding:

```
principals
├── id               ULID PK
├── principal_type   TEXT NOT NULL  ('USER', 'SERVICE_ACCOUNT', 'TEAM')
├── name             TEXT NOT NULL UNIQUE (within type)
├── tenant_id        TEXT  (nullable; required for Gate 3)
├── enabled          BOOLEAN DEFAULT true
├── created_at       TIMESTAMPTZ
└── updated_at       TIMESTAMPTZ

team_memberships
├── id               ULID PK
├── principal_id     FK → principals
├── team_id          FK → principals (WHERE principal_type = 'TEAM')
├── granted_at       TIMESTAMPTZ
├── granted_by       TEXT NOT NULL
├── created_at       TIMESTAMPTZ
└── updated_at       TIMESTAMPTZ
    UNIQUE (principal_id, team_id)

roles
├── id               ULID PK
├── name             TEXT NOT NULL
├── description      TEXT
├── built_in         BOOLEAN DEFAULT false
├── permissions      JSONB NOT NULL DEFAULT '[]'   -- explicit permission list
├── inherits_from    TEXT  (nullable; only for built-in hierarchy)
├── display_base     TEXT  (nullable; UI hint per Decision 3)
├── scope_type       TEXT NOT NULL  ('PLATFORM', 'TENANT', 'TEAM')
├── created_by       TEXT NOT NULL
├── created_at       TIMESTAMPTZ
└── updated_at       TIMESTAMPTZ
    UNIQUE (name, scope_type)

role_assignments
├── id               ULID PK
├── principal_id     FK → principals
├── role_id          FK → roles
├── scope_type       TEXT NOT NULL  ('PLATFORM', 'TENANT', 'TEAM', 'NAMESPACE')
├── scope_id         TEXT NOT NULL
├── granted_by       TEXT NOT NULL
├── granted_at       TIMESTAMPTZ
├── expires_at       TIMESTAMPTZ  (nullable)
├── revoked          BOOLEAN DEFAULT false
├── revoked_at       TIMESTAMPTZ  (nullable)
├── revoked_by       TEXT  (nullable)
├── created_at       TIMESTAMPTZ
└── updated_at       TIMESTAMPTZ
    INDEX (principal_id, scope_type, scope_id)
    INDEX (role_id)

deny_assignments
├── id               ULID PK
├── principal_id     FK → principals
├── permission       TEXT NOT NULL
├── scope_type       TEXT NOT NULL
├── scope_id         TEXT NOT NULL
├── reason           TEXT NOT NULL
├── granted_by       TEXT NOT NULL
├── expires_at       TIMESTAMPTZ  (nullable)
├── created_at       TIMESTAMPTZ
└── updated_at       TIMESTAMPTZ
    INDEX (principal_id, permission)

namespace_bindings
├── id               ULID PK
├── namespace_pattern TEXT NOT NULL
├── team_id          FK → principals
├── access_level     TEXT NOT NULL  ('OWNER', 'READ_WRITE', 'READ_ONLY')
├── granted_by       TEXT NOT NULL
├── created_at       TIMESTAMPTZ
└── updated_at       TIMESTAMPTZ
    INDEX (team_id)
    INDEX (namespace_pattern)

impersonation_sessions
├── id                      ULID PK
├── real_principal_id       FK → principals
├── effective_principal_id  FK → principals
├── reason                  TEXT NOT NULL
├── approval_reference      TEXT  (nullable)
├── started_at              TIMESTAMPTZ NOT NULL
├── ended_at                TIMESTAMPTZ  (nullable)
├── max_duration_seconds    INTEGER DEFAULT 3600
├── permissions_restricted  JSONB  (nullable)
├── created_at              TIMESTAMPTZ
└── updated_at              TIMESTAMPTZ
    INDEX (real_principal_id)
    INDEX (effective_principal_id)
```

Total: 7 new tables, 21 new tables overall (14 existing + 7 new).

### 0.2 Owning scope columns (Rule A)

Add to existing tables via a second migration:

```sql
ALTER TABLE workflow_definitions ADD COLUMN owning_scope_type TEXT;
ALTER TABLE workflow_definitions ADD COLUMN owning_scope_id TEXT;
ALTER TABLE workflow_runs ADD COLUMN owning_scope_type TEXT;
ALTER TABLE workflow_runs ADD COLUMN owning_scope_id TEXT;
ALTER TABLE memory_records ADD COLUMN owning_scope_type TEXT;
ALTER TABLE memory_records ADD COLUMN owning_scope_id TEXT;
ALTER TABLE approval_requests ADD COLUMN owning_scope_type TEXT;
ALTER TABLE approval_requests ADD COLUMN owning_scope_id TEXT;
ALTER TABLE policy_rules ADD COLUMN owning_scope_type TEXT;
ALTER TABLE policy_rules ADD COLUMN owning_scope_id TEXT;
```

These columns are nullable during transition. Phase 2 populates them.

### 0.3 Audit event extensions

Add to `audit_events`:

```sql
ALTER TABLE audit_events ADD COLUMN real_actor TEXT;
ALTER TABLE audit_events ADD COLUMN impersonation_session_id TEXT;
ALTER TABLE audit_events ADD COLUMN resource_scope_type TEXT;
ALTER TABLE audit_events ADD COLUMN resource_scope_id TEXT;
```

`resource_scope_type` and `resource_scope_id` are denormalized from the target resource at write time. This avoids expensive polymorphic resource lookups during audit queries (which would otherwise require joining against every resource table to resolve scope). Audit visibility filtering (Rule C, Phase 3) queries these columns directly instead of resolving through the resource.

If `resource_scope_type`/`resource_scope_id` are NULL (resource not resolvable, e.g., system-level events), the event is only visible to the generating actor and `platform_admin`.

### 0.4 Principal ID columns (parallel to existing string columns)

Add FK-ready columns alongside existing string columns. Do **not** remove the string columns yet.

```sql
ALTER TABLE workflow_definitions ADD COLUMN owner_principal_id TEXT;
ALTER TABLE workflow_runs ADD COLUMN initiated_by_principal_id TEXT;
ALTER TABLE memory_records ADD COLUMN actor_principal_id TEXT;
ALTER TABLE audit_events ADD COLUMN actor_principal_id TEXT;
ALTER TABLE api_keys ADD COLUMN actor_principal_id TEXT;
```

### 0.5 Seed data

A data migration script that runs after the schema migration:

1. Create a `principals` row for every distinct actor string in: `workflow_definitions.owner`, `workflow_runs.initiated_by`, `memory_records.actor`, `api_keys.actor`, `audit_events.actor`.
2. Infer `principal_type`:
   - Strings starting with `system:` → `SERVICE_ACCOUNT`
   - All others → `USER`
3. Create built-in roles with explicit permission sets (from design spec section 3).
4. Create role assignments that mirror current prefix conventions:
   - `admin:*` actors → `admin` role at platform scope.
   - `policy:*` actors → custom role `policy_manager` with `{policy:read, policy:evaluate, policy:manage}` at platform scope.
   - `system:*` actors → role assignments per Decision 2 table.
   - All other actors → `operator` role at platform scope. **This is transitional scaffolding**, not a real access model. It preserves current open-access behavior during shadow mode so that the RBAC evaluator produces zero disagreements against legacy for the existing population. These broad grants must be narrowed to team-scoped assignments before Phase 4 cutover. A pre-cutover audit step (Phase 4.1) explicitly verifies that no platform-scope `operator` assignments remain for non-service principals.
5. Populate `owner_principal_id` / `initiated_by_principal_id` / `actor_principal_id` from the string-to-principal mapping.
6. Populate `owning_scope_type` and `owning_scope_id`:
   - All existing resources get `owning_scope_type = 'PLATFORM'`, `owning_scope_id = 'platform'` (since Gate 1 is single-domain).
   - This is correct for current state and will be narrowed when teams are created.

### 0.6 Verification

- [ ] All new tables created with correct columns and indexes.
- [ ] All existing tables have new nullable columns.
- [ ] Every distinct actor string has a corresponding `principals` row.
- [ ] Built-in roles exist with correct permission sets.
- [ ] Role assignments exist for all current actors.
- [ ] No existing tests broken (new columns are nullable, no behavioral change).

**Rollback**: Drop new tables and columns. Restore from pre-migration backup. Zero application impact since no code references the new tables yet.

---

## Phase 1: Shadow-Mode Evaluator

**Goal**: RBAC evaluation runs on every request, logs its decision, but does not enforce. Disagreements between old and new systems are captured.

### 1.1 Permission resolver

New module: `syndicateclaw/rbac/resolver.py`

```
class PermissionResolver:
    async def resolve_effective_permissions(
        principal_id: str,
    ) -> dict[str, set[str]]:
        """Returns {scope_id: {permission, ...}} for all scopes."""

    async def check_permission(
        principal_id: str,
        permission: str,
        resource_scope_type: str,
        resource_scope_id: str,
    ) -> AuthzDecision:
        """Returns ALLOW or DENY with full trace."""
```

`AuthzDecision` is a structured result:

```
@dataclass
class AuthzDecision:
    effect: Literal["ALLOW", "DENY"]
    reason: str
    principal_id: str
    permission: str
    scope_type: str
    scope_id: str
    matching_role: str | None      # role that granted, if ALLOW
    matching_deny: str | None      # deny assignment ID, if DENY
    evaluated_at: datetime
    cached: bool                   # whether resolved from cache
```

### 1.2 Deny resolver

New module: `syndicateclaw/rbac/deny.py`

Always reads from database (Decision 4, rule 7). Never cached.

```
class DenyResolver:
    async def check_denies(
        principal_id: str,
        permission: str,
        scope_chain: list[tuple[str, str]],  # [(scope_type, scope_id), ...]
    ) -> DenyAssignment | None:
        """Returns the first matching deny, or None."""
```

The scope chain includes all containing scopes (namespace → team → tenant → platform). Any matching deny at any level returns DENY immediately.

### 1.3 Cache layer

New module: `syndicateclaw/rbac/cache.py`

```
class PermissionCache:
    async def get(principal_id: str) -> dict[str, set[str]] | None
    async def set(principal_id: str, permissions: dict[str, set[str]]) -> None
    async def invalidate(principal_id: str) -> None
    async def invalidate_role(role_id: str) -> None     # bumps version for all holders
    async def invalidate_team(team_id: str) -> None     # bumps version for all members
```

Redis keys:
- `rbac:version:{principal_id}` → monotonic integer
- `rbac:perms:{principal_id}:{version}` → JSON, TTL 60s

### 1.4 Shadow-mode middleware

New middleware: `syndicateclaw/rbac/shadow.py`

Runs after authentication, before route handlers. On every request:

1. Resolve the principal from `actor` string.
2. Determine the required permission and resource scope from a **static route registry** (see below).
3. Call `PermissionResolver.check_permission()`.
4. Determine the old system's decision (would the current prefix-based / ownership checks allow this?).

#### Static route registry

Scope resolution must not be ad-hoc. Every route is mapped in a single registry:

```python
ROUTE_PERMISSION_MAP: dict[str, RouteAuthzSpec] = {
    "create_workflow":   RouteAuthzSpec(permission="workflow:create",  scope_resolver=scope_from_body_or_header),
    "get_workflow":      RouteAuthzSpec(permission="workflow:read",    scope_resolver=scope_from_workflow_id),
    "list_workflows":    RouteAuthzSpec(permission="workflow:read",    scope_resolver=scope_from_actor_teams),
    "start_run":         RouteAuthzSpec(permission="workflow:execute", scope_resolver=scope_from_workflow_id),
    "get_run":           RouteAuthzSpec(permission="workflow:read",    scope_resolver=scope_from_run_id),
    "write_memory":      RouteAuthzSpec(permission="memory:write",    scope_resolver=scope_from_namespace),
    "read_memory":       RouteAuthzSpec(permission="memory:read",     scope_resolver=scope_from_namespace),
    "manage_policy":     RouteAuthzSpec(permission="policy:manage",   scope_resolver=scope_platform),
    "list_audit_events": RouteAuthzSpec(permission="audit:read",      scope_resolver=scope_from_actor_teams),
    # ... all routes ...
}
```

Each `RouteAuthzSpec` includes:
- `permission`: the required permission string.
- `scope_resolver`: a callable `(Request) -> ResourceScope` that extracts scope from path params, query params, or request body. Never from response data (which is not yet available).
- `fallback`: behavior when the scope resolver cannot determine scope. Default: `DENY`. The only acceptable alternative is `PLATFORM` for routes that are inherently unscoped (e.g., `/healthz`).

Routes not in the registry are denied by default in shadow mode (logged as `rbac.shadow_unregistered_route`). This makes missing entries visible immediately.
6. Log both decisions with structured fields:

```json
{
  "event": "rbac.shadow_evaluation",
  "actor": "dev-agent",
  "principal_id": "01ABC...",
  "permission": "workflow:read",
  "scope": "platform",
  "rbac_decision": "ALLOW",
  "legacy_decision": "ALLOW",
  "agreement": true,
  "rbac_reason": "role:operator grants workflow:read at platform scope",
  "legacy_reason": "ownership check passed"
}
```

7. If decisions disagree, emit a **warning-level** log with full context and increment a counter:

```json
{
  "event": "rbac.shadow_disagreement",
  "level": "warning",
  ...
}
```

8. **Do not enforce the RBAC decision.** The legacy system remains authoritative.

### 1.5 Shadow-mode metrics

Track in Redis (or application metrics):

| Metric | Key | Description |
|---|---|---|
| Total evaluations | `rbac:metrics:total` | Every shadow evaluation |
| Agreements | `rbac:metrics:agree` | Both systems returned same decision |
| Disagreements | `rbac:metrics:disagree` | Systems returned different decisions |
| RBAC stricter | `rbac:metrics:rbac_stricter` | RBAC denied, legacy allowed |
| Legacy stricter | `rbac:metrics:legacy_stricter` | Legacy denied, RBAC allowed |
| Cache hits | `rbac:metrics:cache_hit` | Permission resolved from cache |
| Cache misses | `rbac:metrics:cache_miss` | Permission resolved from DB |
| Deny checks | `rbac:metrics:deny_checks` | Total deny assignment evaluations |
| Deny hits | `rbac:metrics:deny_hits` | Requests blocked by deny assignments |

**Target before cutover**: Zero disagreements for at least one full release cycle (minimum 7 days of production traffic). Any disagreement must be investigated, root-caused, and resolved before proceeding.

### 1.6 Verification

- [ ] Shadow evaluator runs on every authenticated request.
- [ ] Structured logs emitted for every evaluation.
- [ ] Disagreement counter is zero after 7+ days.
- [ ] Cache hit rate > 80% under normal traffic.
- [ ] Deny assignments correctly block in shadow mode (logged but not enforced).
- [ ] No measurable latency regression (p99 < 10ms added).

**Rollback**: Disable shadow middleware. No enforcement impact.

---

## Phase 2: Namespace Binding Enforcement

**Goal**: Memory access is mediated by namespace bindings, not convention.

### 2.1 Binding management API

New endpoints under `/api/v1/namespaces/`:

| Endpoint | Method | Permission | Description |
|---|---|---|---|
| `/api/v1/namespaces/bindings` | POST | `namespace:bind` | Create a namespace binding |
| `/api/v1/namespaces/bindings` | GET | `namespace:read` | List bindings for actor's teams |
| `/api/v1/namespaces/bindings/{id}` | DELETE | `namespace:bind` | Remove a binding |

### 2.2 Write-time conflict resolution (Rule B)

On binding creation:

1. Query all existing bindings that overlap the new pattern.
2. Apply conflict rules: exact beats glob, longer beats shorter, equal-specificity cross-team rejected (409).
3. If valid, persist and invalidate permission cache for all members of the affected team.

### 2.3 Read-time resolution

New module: `syndicateclaw/rbac/namespace.py`

```
class NamespaceResolver:
    async def resolve_access(
        principal_id: str,
        namespace: str,
        required_level: str,  # 'READ_ONLY', 'READ_WRITE', 'OWNER'
    ) -> bool:
        """Check if principal has required access to namespace."""
```

Resolution:
1. Get principal's team IDs.
2. Get all namespace bindings for those teams.
3. Match namespace against binding patterns (most specific wins).
4. Check `access_level` against required level.

### 2.4 Memory path integration

Modify `MemoryService` and memory API routes:

- `write()`: Requires `READ_WRITE` or `OWNER` on namespace. Calls `NamespaceResolver.resolve_access()`.
- `read()` / `search()`: Requires `READ_ONLY` or higher. Replaces the current `_check_access_policy()` for team-scoped access. Individual record `access_policy` is still checked as a secondary layer.
- `update()`: Requires `READ_WRITE` or `OWNER`.
- `delete()`: Requires `OWNER`.

**Migration**: Until teams/bindings are created, the resolver falls back to the current behavior (all authenticated actors have platform-scope access). This ensures backward compatibility.

### 2.5 Verification

- [ ] Namespace binding CRUD works with conflict detection.
- [ ] Memory operations are gated by binding access levels.
- [ ] Cross-team memory isolation: team A cannot read team B's namespace without a binding.
- [ ] Fallback to platform-scope access when no bindings exist (backward compat).

**Rollback**: Disable namespace resolver. Memory routes fall back to current `_check_access_policy()` behavior.

---

## Phase 3: Endpoint Enforcement

**Goal**: Every API endpoint enforces permissions via `require_permission`. Prefix-based checks still run in parallel (belt-and-suspenders).

### 3.1 Authorization dependency

New FastAPI dependency: `syndicateclaw/rbac/dependencies.py`

```python
def require_permission(permission: str):
    """Returns a FastAPI dependency that enforces RBAC."""
    async def _check(
        request: Request,
        actor: str = Depends(get_current_actor),
    ) -> None:
        principal_id = resolve_principal_id(actor)
        scope = resolve_resource_scope(request)
        decision = await resolver.check_permission(
            principal_id, permission, scope.type, scope.id
        )
        if decision.effect == "DENY":
            raise HTTPException(status_code=403, detail=decision.reason)
    return Depends(_check)
```

### 3.2 Endpoint wiring

Add `require_permission` to every route handler as an additional dependency. Keep existing ownership/prefix checks intact during this phase.

Example:

```python
@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(
    workflow_id: str,
    actor: str = Depends(get_current_actor),
    _auth: None = require_permission("workflow:read"),
    db=Depends(get_db_session),
):
    # Existing ownership check remains during dual enforcement
    ...
```

### 3.3 Audit query scoping (Rule C)

Modify audit query endpoints to filter by visibility rules using the denormalized scope columns added in Phase 0.3:

1. Resolve the principal's effective scopes (team IDs, tenant ID).
2. Filter `audit_events` by:
   - `actor_principal_id = principal_id` (self-generated), OR
   - `resource_scope_type` / `resource_scope_id` is in the principal's accessible scopes (direct query on audit rows, no resource join).
   - Events with NULL `resource_scope_type` are visible only to the generating actor and `platform_admin`.
3. `tenant_admin` sees all events where `resource_scope_id` is within their tenant. `platform_admin` sees all.

This query pattern is a single indexed scan on `audit_events`, not a polymorphic join.

### 3.4 Intersection enforcement

During Phase 3, authorization is enforced as the **intersection** of legacy and RBAC decisions. A request must pass both systems. This is not "both evaluated, legacy still authoritative" — it is a deliberate behavioral tightening that narrows the authorization boundary before cutover.

| Scenario | Behavior |
|---|---|
| Both ALLOW | Proceed |
| RBAC ALLOW, legacy DENY | **Deny** (legacy blocks) + log disagreement |
| RBAC DENY, legacy ALLOW | **Deny** (RBAC blocks) + log disagreement |
| Both DENY | Deny |

This means Phase 3 can surface access regressions in production. Any disagreement must be root-caused before continuing observation. Cutover does not proceed until both systems agree for 7+ consecutive days, proving they are decision-equivalent.

### 3.5 Verification

- [ ] Every endpoint has a `require_permission` dependency.
- [ ] Intersection enforcement passes both systems on every request.
- [ ] Zero disagreements for 7+ days under production traffic.
- [ ] Audit queries respect Rule C visibility using denormalized scope columns.
- [ ] `platform_admin` can still see all events.
- [ ] **Performance gate**: p99 latency overhead from RBAC evaluation < 10ms under production traffic. This is an explicit go/no-go criterion — if enforcement adds more than 10ms p99, optimization (cache tuning, query indexing) must be completed before cutover.

**Rollback**: Remove `require_permission` dependencies. Legacy checks remain.

---

## Phase 4: Cutover and Cleanup

**Goal**: Remove legacy authorization. RBAC is the sole enforcement system.

### 4.1 Prerequisites (all must be true)

- [ ] Phase 1 shadow mode: zero disagreements for 7+ days.
- [ ] Phase 3 intersection enforcement: zero disagreements for 7+ days.
- [ ] Phase 3 performance gate: p99 latency overhead < 10ms.
- [ ] All built-in roles have correct permission sets (manually verified).
- [ ] All service accounts have explicit role assignments.
- [ ] **No platform-scope `operator` assignments remain for non-service principals** (transitional scaffolding narrowed to team-scoped assignments).
- [ ] At least one deny assignment has been tested end-to-end in production.
- [ ] Impersonation session creation and audit logging verified.
- [ ] Namespace binding conflict rejection verified.
- [ ] Audit query scoping verified for viewer, admin, tenant_admin roles.

### 4.2 Cutover steps

1. **Remove prefix-based checks**:
   - Delete `POLICY_ADMIN_PREFIXES` constant and `_require_policy_admin()` function from `policy.py`.
   - Delete all `actor.startswith("admin:")` / `startswith("system:")` checks.
   - Delete all direct `wf.owner == actor` and `run.initiated_by == actor` ownership comparisons in route handlers. These are now redundant with RBAC scope checks.

2. **Remove shadow-mode middleware**. The `require_permission` dependency is now the sole gate.

3. **Remove dual enforcement monitoring**. Only RBAC decisions are logged.

4. **Drop legacy string columns** (final migration, can be deferred):
   - Rename `owner` → `owner_legacy` on `workflow_definitions`.
   - Rename `initiated_by` → `initiated_by_legacy` on `workflow_runs`.
   - Rename `actor` → `actor_legacy` on `memory_records`, `audit_events`, `api_keys`.
   - Keep legacy columns for one more release cycle, then drop.

### 4.3 Post-cutover verification

- [ ] No prefix-based authorization code remains in `src/`.
- [ ] Every request is authorized by `require_permission`.
- [ ] A principal without any role assignment gets 403 on all endpoints.
- [ ] A principal with `viewer` at team scope can read team resources but not modify them.
- [ ] A principal with `operator` at team scope can execute workflows and write memory within team.
- [ ] A principal with `admin` at team scope can manage policies and tools within team.
- [ ] Cross-team access is denied unless namespace binding exists.
- [ ] Deny assignment blocks access regardless of role grants.
- [ ] Impersonation constrains to effective principal permissions.
- [ ] All 16 success criteria from the design spec are met.

### 4.4 Rollback

**Rollback from cutover is a deployment rollback**, not a code change. The previous release (with dual enforcement) is redeployed. The RBAC tables and data remain in place. The legacy checks resume operation alongside the dormant RBAC evaluator.

This is why dual enforcement runs for 7+ days before cutover: it proves the RBAC system produces identical decisions to legacy, so rollback to dual-enforcement mode is safe.

---

## Timeline Estimates

| Phase | Duration | Dependencies |
|---|---|---|
| Phase 0: Data model | 1–2 weeks | None |
| Phase 1: Shadow mode | 2–3 weeks dev + 7+ days observation | Phase 0 |
| Phase 2: Namespace bindings | 1–2 weeks | Phase 0 |
| Phase 3: Endpoint enforcement | 2–3 weeks dev + 7+ days observation | Phases 1 + 2 |
| Phase 4: Cutover | 1 week + 7+ days monitoring | Phase 3 |

**Total estimated duration**: 8–12 weeks including observation periods.

Phases 1 and 2 can run in parallel after Phase 0 completes.

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Shadow mode reveals unexpected disagreements | Medium | Low (no enforcement impact) | Fix root causes before dual enforcement |
| Permission cache staleness causes stale allows | Low | Medium | Deny-from-DB + 60s TTL backstop |
| Namespace binding conflicts block legitimate operations | Low | Medium | Clear error messages; admin override via `OWNER` binding |
| Multi-team principals confused by `X-Team-Context` requirement | Medium | Low | Clear 400 error with guidance; default to single team when unambiguous |
| Cutover reveals edge case missed by shadow mode | Low | High | Rollback to dual enforcement within minutes |
| Performance regression from RBAC evaluation | Low | Medium | Permission caching; target < 10ms p99 added latency |

---

## Artifacts Produced

| Phase | Artifacts |
|---|---|
| 0 | 3 Alembic migrations, seed data script, 7 SQLAlchemy ORM models |
| 1 | `rbac/` package: resolver, deny, cache, shadow middleware; shadow metrics dashboard |
| 2 | `rbac/namespace.py`, namespace binding API routes, memory service integration |
| 3 | `rbac/dependencies.py`, endpoint wiring, audit query scoping |
| 4 | Cleanup PR removing legacy checks; final migration dropping legacy columns |
