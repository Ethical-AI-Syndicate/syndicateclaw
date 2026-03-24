# Phase 0 Execution Checklist

Operational execution plan for the data model and migration phase of RBAC implementation.

Parent documents:
- `docs/rbac-design.md` — authoritative design spec
- `docs/rbac-implementation-plan.md` — phased implementation plan

---

## Migration Order

Execute in this exact order. Each step must complete successfully before the next begins.

### Migration 1: New RBAC tables

**File**: `migrations/versions/001_rbac_tables.py`

Creates 7 new tables. No FK references to existing tables (except team_memberships → principals, role_assignments → principals/roles, etc. within the new table set).

Tables created:

| # | Table | Row estimate (initial) |
|---|---|---|
| 1 | `principals` | one per distinct actor |
| 2 | `team_memberships` | empty (no teams yet) |
| 3 | `roles` | 5 built-in + 1 custom |
| 4 | `role_assignments` | one per principal |
| 5 | `deny_assignments` | empty |
| 6 | `namespace_bindings` | empty |
| 7 | `impersonation_sessions` | empty |

**Indexes created with tables** (not deferred):
- `principals`: UNIQUE on `(principal_type, name)`
- `team_memberships`: UNIQUE on `(principal_id, team_id)`, INDEX on `team_id`
- `roles`: UNIQUE on `(name, scope_type)`
- `role_assignments`: INDEX on `(principal_id, scope_type, scope_id)`, INDEX on `role_id`
- `deny_assignments`: INDEX on `(principal_id, permission)`
- `namespace_bindings`: INDEX on `team_id`, INDEX on `namespace_pattern`
- `impersonation_sessions`: INDEX on `real_principal_id`, INDEX on `effective_principal_id`

**Rollback**: `DROP TABLE` in reverse order (impersonation_sessions → namespace_bindings → deny_assignments → role_assignments → roles → team_memberships → principals).

### Migration 2: Owning scope columns on existing tables

**File**: `migrations/versions/002_owning_scope_columns.py`

Adds nullable columns to 5 existing tables. No default values, no NOT NULL constraints.

```sql
-- workflow_definitions
ALTER TABLE workflow_definitions ADD COLUMN owning_scope_type TEXT;
ALTER TABLE workflow_definitions ADD COLUMN owning_scope_id TEXT;
ALTER TABLE workflow_definitions ADD COLUMN owner_principal_id TEXT;

-- workflow_runs
ALTER TABLE workflow_runs ADD COLUMN owning_scope_type TEXT;
ALTER TABLE workflow_runs ADD COLUMN owning_scope_id TEXT;
ALTER TABLE workflow_runs ADD COLUMN initiated_by_principal_id TEXT;

-- memory_records
ALTER TABLE memory_records ADD COLUMN owning_scope_type TEXT;
ALTER TABLE memory_records ADD COLUMN owning_scope_id TEXT;
ALTER TABLE memory_records ADD COLUMN actor_principal_id TEXT;

-- approval_requests
ALTER TABLE approval_requests ADD COLUMN owning_scope_type TEXT;
ALTER TABLE approval_requests ADD COLUMN owning_scope_id TEXT;

-- policy_rules
ALTER TABLE policy_rules ADD COLUMN owning_scope_type TEXT;
ALTER TABLE policy_rules ADD COLUMN owning_scope_id TEXT;
```

**Rollback**: `ALTER TABLE ... DROP COLUMN` for each added column.

### Migration 3: Audit event extensions

**File**: `migrations/versions/003_audit_rbac_columns.py`

Adds 4 nullable columns to `audit_events` and 1 to `api_keys`.

```sql
-- audit_events
ALTER TABLE audit_events ADD COLUMN real_actor TEXT;
ALTER TABLE audit_events ADD COLUMN impersonation_session_id TEXT;
ALTER TABLE audit_events ADD COLUMN resource_scope_type TEXT;
ALTER TABLE audit_events ADD COLUMN resource_scope_id TEXT;
ALTER TABLE audit_events ADD COLUMN actor_principal_id TEXT;

-- api_keys
ALTER TABLE api_keys ADD COLUMN actor_principal_id TEXT;
```

**New indexes** (for audit query scoping in Phase 3):
```sql
CREATE INDEX ix_audit_events_resource_scope
    ON audit_events (resource_scope_type, resource_scope_id);
CREATE INDEX ix_audit_events_actor_principal
    ON audit_events (actor_principal_id);
```

**Rollback**: Drop indexes, then drop columns.

---

## Seed Script

**File**: `scripts/seed_rbac_phase0.py`

Runs as a standalone async script after all three migrations complete. Idempotent — safe to run multiple times.

### Step 1: Extract distinct actors

```sql
SELECT DISTINCT actor_name FROM (
    SELECT owner AS actor_name FROM workflow_definitions WHERE owner IS NOT NULL
    UNION
    SELECT initiated_by FROM workflow_runs WHERE initiated_by IS NOT NULL
    UNION
    SELECT actor FROM memory_records WHERE actor IS NOT NULL
    UNION
    SELECT actor FROM api_keys
    UNION
    SELECT actor FROM audit_events
) AS actors;
```

### Step 2: Create principals

For each distinct actor string:

| Actor pattern | `principal_type` |
|---|---|
| `system:*` | `SERVICE_ACCOUNT` |
| all others | `USER` |

**Invariant S1**: Every row produced by Step 1 has exactly one corresponding `principals` row after Step 2.

### Step 3: Create built-in roles

| Role | `built_in` | `inherits_from` | `scope_type` | Permissions |
|---|---|---|---|---|
| `viewer` | true | NULL | PLATFORM | `workflow:read`, `memory:read`, `audit:read`, `tool:read`, `policy:read`, `approval:read` |
| `operator` | true | `viewer` | PLATFORM | + `workflow:create`, `workflow:execute`, `memory:write`, `tool:execute`, `approval:request` |
| `admin` | true | `operator` | PLATFORM | + `workflow:delete`, `memory:delete`, `tool:manage`, `policy:manage`, `policy:evaluate`, `approval:decide`, `namespace:read`, `namespace:bind` |
| `tenant_admin` | true | `admin` | PLATFORM | + `audit:export`, `system:manage_keys`, `system:manage_principals` |
| `platform_admin` | true | `tenant_admin` | PLATFORM | + `system:configure`, `system:impersonate` |

Custom role (for migration):

| Role | `built_in` | Permissions |
|---|---|---|
| `policy_manager` | false | `policy:read`, `policy:evaluate`, `policy:manage` |

**Invariant S2**: Exactly 6 roles exist after Step 3 (5 built-in + 1 custom).

**Invariant S3**: Each built-in role's resolved permission set (including inherited) matches the design spec section 3 exactly.

### Step 4: Create role assignments

| Actor pattern | Role | Scope |
|---|---|---|
| `admin:*` | `admin` | `(PLATFORM, platform)` |
| `policy:*` | `policy_manager` | `(PLATFORM, platform)` |
| `system:engine` | `operator` | `(PLATFORM, platform)` |
| `system:scheduler` | `operator` | `(PLATFORM, platform)` |
| `system:audit` | `viewer` | `(PLATFORM, platform)` |
| All other actors | `operator` | `(PLATFORM, platform)` |

**Invariant S4**: Every principal has at least one role assignment.

**Invariant S5**: No principal has more than one role assignment after seeding (roles are not duplicated).

**Invariant S6**: The `operator` role at platform scope for non-service, non-admin principals is tagged `transitional = true` in metadata (or equivalent marker) so it can be identified and removed before Phase 4 cutover.

### Step 5: Populate principal ID columns

```sql
UPDATE workflow_definitions wd
   SET owner_principal_id = p.id
  FROM principals p
 WHERE p.name = wd.owner AND wd.owner IS NOT NULL;

UPDATE workflow_runs wr
   SET initiated_by_principal_id = p.id
  FROM principals p
 WHERE p.name = wr.initiated_by AND wr.initiated_by IS NOT NULL;

UPDATE memory_records mr
   SET actor_principal_id = p.id
  FROM principals p
 WHERE p.name = mr.actor AND mr.actor IS NOT NULL;

UPDATE audit_events ae
   SET actor_principal_id = p.id
  FROM principals p
 WHERE p.name = ae.actor;

UPDATE api_keys ak
   SET actor_principal_id = p.id
  FROM principals p
 WHERE p.name = ak.actor;
```

**Invariant S7**: Zero rows with non-NULL actor string and NULL `*_principal_id` after this step.

### Step 6: Populate owning scope columns

All existing resources are single-domain (Gate 1). Set all to platform scope.

```sql
UPDATE workflow_definitions
   SET owning_scope_type = 'PLATFORM', owning_scope_id = 'platform'
 WHERE owning_scope_type IS NULL;

UPDATE workflow_runs
   SET owning_scope_type = 'PLATFORM', owning_scope_id = 'platform'
 WHERE owning_scope_type IS NULL;

UPDATE memory_records
   SET owning_scope_type = 'PLATFORM', owning_scope_id = 'platform'
 WHERE owning_scope_type IS NULL;

UPDATE approval_requests
   SET owning_scope_type = 'PLATFORM', owning_scope_id = 'platform'
 WHERE owning_scope_type IS NULL;

UPDATE policy_rules
   SET owning_scope_type = 'PLATFORM', owning_scope_id = 'platform'
 WHERE owning_scope_type IS NULL;
```

**Invariant S8**: Zero rows with NULL `owning_scope_type` in any of the 5 tables after this step.

---

## Verification Queries

Run after seed script completes. All must pass.

### V1: Principal coverage

```sql
-- Must return 0: actors without principals
SELECT COUNT(*) FROM (
    SELECT owner AS actor_name FROM workflow_definitions WHERE owner IS NOT NULL
    UNION
    SELECT initiated_by FROM workflow_runs WHERE initiated_by IS NOT NULL
    UNION
    SELECT actor FROM memory_records WHERE actor IS NOT NULL
    UNION
    SELECT actor FROM api_keys
    UNION
    SELECT actor FROM audit_events
) AS actors
LEFT JOIN principals p ON p.name = actors.actor_name
WHERE p.id IS NULL;
```

**Expected**: `0`

### V2: Role completeness

```sql
-- Must return exactly 6
SELECT COUNT(*) FROM roles;

-- Must return exactly 5
SELECT COUNT(*) FROM roles WHERE built_in = true;
```

**Expected**: `6`, `5`

### V3: Assignment completeness

```sql
-- Must return 0: principals without assignments
SELECT COUNT(*) FROM principals p
LEFT JOIN role_assignments ra ON ra.principal_id = p.id
WHERE ra.id IS NULL;
```

**Expected**: `0`

### V4: Principal ID population

```sql
-- Each must return 0
SELECT COUNT(*) FROM workflow_definitions
 WHERE owner IS NOT NULL AND owner_principal_id IS NULL;

SELECT COUNT(*) FROM workflow_runs
 WHERE initiated_by IS NOT NULL AND initiated_by_principal_id IS NULL;

SELECT COUNT(*) FROM memory_records
 WHERE actor IS NOT NULL AND actor_principal_id IS NULL;

SELECT COUNT(*) FROM audit_events
 WHERE actor_principal_id IS NULL;

SELECT COUNT(*) FROM api_keys
 WHERE actor_principal_id IS NULL;
```

**Expected**: All `0`

### V5: Owning scope population

```sql
-- Each must return 0
SELECT COUNT(*) FROM workflow_definitions WHERE owning_scope_type IS NULL;
SELECT COUNT(*) FROM workflow_runs WHERE owning_scope_type IS NULL;
SELECT COUNT(*) FROM memory_records WHERE owning_scope_type IS NULL;
SELECT COUNT(*) FROM approval_requests WHERE owning_scope_type IS NULL;
SELECT COUNT(*) FROM policy_rules WHERE owning_scope_type IS NULL;
```

**Expected**: All `0`

### V6: Role permission integrity

```sql
-- viewer must have exactly 6 permissions
SELECT jsonb_array_length(permissions) FROM roles WHERE name = 'viewer';

-- operator must have viewer's permissions + 5 more = 11
-- (resolved via inherits_from chain)
SELECT r.name,
       jsonb_array_length(r.permissions) AS direct_count,
       r.inherits_from
  FROM roles r
 WHERE r.built_in = true
 ORDER BY jsonb_array_length(r.permissions);
```

**Expected**: Verify counts match design spec section 3.

### V7: No orphaned assignments

```sql
-- Must return 0: assignments referencing missing principals
SELECT COUNT(*) FROM role_assignments ra
LEFT JOIN principals p ON p.id = ra.principal_id
WHERE p.id IS NULL;

-- Must return 0: assignments referencing missing roles
SELECT COUNT(*) FROM role_assignments ra
LEFT JOIN roles r ON r.id = ra.role_id
WHERE r.id IS NULL;
```

**Expected**: Both `0`

### V8: Service account classification

```sql
-- All system:* actors must be SERVICE_ACCOUNT
SELECT COUNT(*) FROM principals
 WHERE name LIKE 'system:%' AND principal_type != 'SERVICE_ACCOUNT';
```

**Expected**: `0`

### V9: Transitional scaffolding marker

```sql
-- Count of platform-scope operator assignments for non-service principals
-- This number must reach 0 before Phase 4 cutover
SELECT COUNT(*) FROM role_assignments ra
  JOIN roles r ON r.id = ra.role_id
  JOIN principals p ON p.id = ra.principal_id
 WHERE r.name = 'operator'
   AND ra.scope_type = 'PLATFORM'
   AND ra.scope_id = 'platform'
   AND p.principal_type = 'USER';
```

**Expected**: Records the baseline count. This is the number that must reach `0` before Phase 4.

---

## Rollback Commands

### Full rollback (reverse all Phase 0 changes)

Execute in reverse migration order. Safe at any point during Phase 0.

```bash
# Step 1: Revert Migration 3 (audit extensions)
alembic downgrade -1

# Step 2: Revert Migration 2 (owning scope columns)
alembic downgrade -1

# Step 3: Revert Migration 1 (RBAC tables)
alembic downgrade -1
```

Alternatively, from a known pre-Phase-0 revision:

```bash
alembic downgrade <pre-phase0-revision>
```

### Partial rollback (seed only)

If migrations succeeded but seed script produced bad data:

```sql
-- Reverse seed in order
UPDATE api_keys SET actor_principal_id = NULL;
UPDATE audit_events SET actor_principal_id = NULL;
UPDATE memory_records SET actor_principal_id = NULL;
UPDATE workflow_runs SET initiated_by_principal_id = NULL;
UPDATE workflow_definitions SET owner_principal_id = NULL;

UPDATE policy_rules SET owning_scope_type = NULL, owning_scope_id = NULL;
UPDATE approval_requests SET owning_scope_type = NULL, owning_scope_id = NULL;
UPDATE memory_records SET owning_scope_type = NULL, owning_scope_id = NULL;
UPDATE workflow_runs SET owning_scope_type = NULL, owning_scope_id = NULL;
UPDATE workflow_definitions SET owning_scope_type = NULL, owning_scope_id = NULL;

TRUNCATE role_assignments CASCADE;
TRUNCATE deny_assignments CASCADE;
TRUNCATE namespace_bindings CASCADE;
TRUNCATE impersonation_sessions CASCADE;
TRUNCATE roles CASCADE;
TRUNCATE team_memberships CASCADE;
TRUNCATE principals CASCADE;
```

Then re-run seed script after fixing the issue.

### Verification after rollback

```sql
-- Confirm new tables are gone (after full rollback)
SELECT tablename FROM pg_tables
 WHERE schemaname = 'public'
   AND tablename IN (
       'principals', 'team_memberships', 'roles',
       'role_assignments', 'deny_assignments',
       'namespace_bindings', 'impersonation_sessions'
   );
-- Expected: 0 rows

-- Confirm new columns are gone (after full rollback)
SELECT column_name FROM information_schema.columns
 WHERE table_name = 'workflow_definitions'
   AND column_name IN ('owning_scope_type', 'owning_scope_id', 'owner_principal_id');
-- Expected: 0 rows

-- Confirm no data loss on existing tables
SELECT COUNT(*) FROM workflow_definitions;
SELECT COUNT(*) FROM workflow_runs;
SELECT COUNT(*) FROM memory_records;
SELECT COUNT(*) FROM audit_events;
-- Expected: same counts as pre-migration
```

---

## Shadow-Mode Dashboard Definitions

These metrics must be operational before Phase 1 begins. Define dashboards and alerts during Phase 0 so Phase 1 starts with full observability.

### Dashboard: RBAC Shadow Evaluator

| Panel | Source | Query pattern | Display |
|---|---|---|---|
| Total evaluations (rate) | `rbac:metrics:total` | `INCR` per request | Time series, 1m buckets |
| Agreement rate | `rbac:metrics:agree / rbac:metrics:total` | Computed | Gauge, target 100% |
| Disagreements (count) | `rbac:metrics:disagree` | `INCR` per disagreement | Counter + sparkline |
| RBAC stricter | `rbac:metrics:rbac_stricter` | `INCR` | Counter |
| Legacy stricter | `rbac:metrics:legacy_stricter` | `INCR` | Counter |
| Cache hit rate | `rbac:metrics:cache_hit / (cache_hit + cache_miss)` | Computed | Gauge, target > 80% |
| Deny check latency | Application metrics (histogram) | p50, p95, p99 | Histogram |
| Permission resolution latency | Application metrics (histogram) | p50, p95, p99 | Histogram |
| Unregistered routes | `rbac:metrics:unregistered_route` | `INCR` | Counter (must be 0) |

### Dashboard: RBAC Data Integrity

| Panel | Source | Query pattern | Display |
|---|---|---|---|
| Principals total | `SELECT COUNT(*) FROM principals` | Periodic query | Counter |
| Assignments total | `SELECT COUNT(*) FROM role_assignments WHERE NOT revoked` | Periodic query | Counter |
| Orphaned principals | V3 query | Periodic query | Counter (must be 0) |
| Missing principal IDs | V4 queries | Periodic query | Counter (must be 0) |
| Missing scopes | V5 queries | Periodic query | Counter (must be 0) |
| Transitional scaffolding | V9 query | Periodic query | Counter (must reach 0 before Phase 4) |

### Alert Thresholds

| Alert | Condition | Severity | Action |
|---|---|---|---|
| `rbac.shadow.disagreement` | `rbac:metrics:disagree` incremented | **P2** | Investigate immediately. Root-cause before proceeding. |
| `rbac.shadow.unregistered_route` | `rbac:metrics:unregistered_route` incremented | **P2** | New route added without permission mapping. Block Phase 1 completion. |
| `rbac.shadow.latency_high` | Permission resolution p99 > 10ms | **P3** | Investigate cache hit rate. Tune TTL or indexes. |
| `rbac.shadow.cache_low` | Cache hit rate < 60% sustained 15m | **P3** | Check Redis connectivity, TTL, invalidation frequency. |
| `rbac.data.orphan_principal` | V3 query > 0 | **P2** | New actor created without principal record. Fix seed script or runtime principal creation. |
| `rbac.data.missing_scope` | V5 query > 0 | **P3** | New resource created without owning scope. Fix resource creation path. |
| `rbac.data.scaffolding_stale` | V9 count unchanged for 14+ days after teams created | **P3** | Transitional assignments not being narrowed. Block Phase 4. |

---

## Pre-Phase-1 Readiness Gate

All conditions must be true before shadow-mode middleware is enabled.

- [ ] All 3 migrations applied successfully.
- [ ] Seed script completed without errors.
- [ ] All 9 verification queries pass.
- [ ] No existing test suite regressions (run full `pytest`).
- [ ] Shadow dashboard is deployed and receiving metrics from a canary/staging instance.
- [ ] Alert thresholds are configured and routed to the correct on-call channel.
- [ ] Static route-to-permission registry covers all existing API routes (verified by comparing registry keys against FastAPI `app.routes`).
- [ ] Rollback procedure tested on staging (apply Phase 0, verify, rollback, verify clean state).

---

## Execution Timeline

| Day | Action |
|---|---|
| D+0 | Create migration files. Code review. |
| D+1 | Apply Migration 1 (new tables) to staging. Verify. |
| D+1 | Apply Migration 2 (scope columns) to staging. Verify. |
| D+1 | Apply Migration 3 (audit columns) to staging. Verify. |
| D+2 | Run seed script on staging. Run all verification queries. |
| D+2 | Run full test suite against staging DB. |
| D+3 | Deploy dashboards and alerts to monitoring. |
| D+3 | Execute rollback procedure on staging. Verify clean state. Re-apply. |
| D+4 | Apply migrations to production. Run seed script. Run verification queries. |
| D+4 | Confirm dashboards show production data. |
| D+5 | Phase 0 complete. Begin Phase 1 development. |
