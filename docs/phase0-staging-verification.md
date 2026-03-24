# Phase 0 Staging Verification Packet

**Date:** 2026-03-24  
**Environment:** staging (`syndicateclaw_staging` @ localhost:5432, Redis db 2, API port 8002)  
**Alembic revision:** `003_audit` (head)

---

## 1. Environment Isolation

Multiple environments coexist on a single host via database sharding and port separation:

| Environment | Database               | Redis DB | API Port |
|-------------|------------------------|----------|----------|
| dev         | `syndicateclaw_dev`    | 1        | 8001     |
| staging     | `syndicateclaw_staging`| 2        | 8002     |
| prod        | `syndicateclaw_prod`   | 3        | 8000     |

Selection: `SYNDICATECLAW_ENV=staging` loads `.env.staging`; `source scripts/env.sh staging` sets all env vars.

---

## 2. Migration Chain

Applied in order, all clean:

```
001_rbac    → create RBAC tables (principals, team_memberships, roles,
              role_assignments, deny_assignments, namespace_bindings,
              impersonation_sessions)
002_scope   → add owning_scope_type/id and principal_id columns to existing tables
003_audit   → add RBAC columns to audit_events and api_keys + indexes
```

Total tables after migration: **22** (14 base + 7 RBAC + alembic_version).

---

## 3. Seed Script Results

```
Step 1: Extracting distinct actors... Found 6 distinct actors
Step 2: Creating principals... 6 principals total
Step 3: Creating roles... 6 roles total
Step 4: Creating role assignments...
Step 5: Populating principal ID columns...
Step 6: Populating owning scope columns...
Running verification checks...
All invariants passed. Phase 0 seed complete.
```

---

## 4. V1–V9 Verification Query Results

| Test      | Description                                     | Result  |
|-----------|-------------------------------------------------|---------|
| V1        | Orphaned actors (no principal)                  | **0**   |
| V2a       | Total roles                                     | **6**   |
| V2b       | Built-in roles                                  | **5**   |
| V3        | Principals without assignments                  | **0**   |
| V4-wf     | workflow_definitions missing owner_principal_id  | **0**   |
| V4-run    | workflow_runs missing initiated_by_principal_id  | **0**   |
| V4-mem    | memory_records missing actor_principal_id        | **0**   |
| V4-audit  | audit_events missing actor_principal_id          | **0**   |
| V4-apikey | api_keys missing actor_principal_id              | **0**   |
| V5-wf     | workflow_definitions missing owning_scope_type   | **0**   |
| V5-run    | workflow_runs missing owning_scope_type           | **0**   |
| V5-mem    | memory_records missing owning_scope_type          | **0**   |
| V5-appr   | approval_requests missing owning_scope_type      | **0**   |
| V5-pol    | policy_rules missing owning_scope_type            | **0**   |
| V6        | Role permission hierarchy                        | **OK** (see below) |
| V7a       | Orphaned assignments (no principal)              | **0**   |
| V7b       | Orphaned assignments (no role)                   | **0**   |
| V8        | Service account misclassification                | **0**   |
| V9        | Transitional platform-scope operator count       | **3**   |

### V6 Detail: Role Permission Integrity

| Role            | Permission Count | Inherits From   |
|-----------------|-----------------|------------------|
| platform_admin  | 2               | tenant_admin     |
| tenant_admin    | 3               | admin            |
| operator        | 5               | viewer           |
| viewer          | 6               | —                |
| admin           | 8               | operator         |

### V9 Detail: Transitional Scaffolding Baseline

3 transitional platform-scope operator assignments for USER principals:
- `user:alice`
- `user:bob`
- `dev-agent`

These must be narrowed to zero before Phase 4 cutover.

---

## 5. Audit Event Denormalization Verification

After creating a workflow via the staging API as `user:alice`:

| Column                  | Value                         | Status      |
|-------------------------|-------------------------------|-------------|
| `actor_principal_id`    | `01KMFW1TJ9DHFBXK3VNQWT9S99` | **Populated** |
| Principal lookup        | `user:alice` (USER)           | **Correct**   |
| `resource_scope_type`   | *(empty)*                     | **Expected** (HTTP audit, not scoped entity) |
| `resource_scope_id`     | *(empty)*                     | **Expected** |

The `_resolve_principal_id()` function in `AuditService.emit()` correctly resolves
the actor string to the principal ID at write time. Resource scope resolution
activates for scoped entity types (workflow, memory, policy) via `_resolve_resource_scope()`.

---

## 6. Rollback Verification

Full downgrade → re-upgrade cycle executed and verified:

```
003_audit → 002_scope    ✓ audit RBAC columns removed (0 columns found)
002_scope → 001_rbac     ✓ owning_scope/principal_id columns removed (0 columns found)
001_rbac  → base         ✓ all 7 RBAC tables removed (0 tables found)
base      → 003_audit    ✓ all tables and columns restored
```

Seed re-applied after re-upgrade: all invariants passed, 6 principals, 6 roles.

---

## 7. Unit Test Results

```
321 passed in 3.30s
```

All tests green after:
- `DateTime(timezone=True)` fix in ORM base (TIMESTAMPTZ columns)
- `HTTP_REQUEST` audit event type added
- Audit middleware fixed to call `.emit()` instead of `.record()`
- `::jsonb` cast syntax fixed in seed script for asyncpg compatibility
- `revoked` column added to role_assignments INSERT in seed script

---

## 8. Fixes Applied During Verification

| Issue | Root Cause | Fix |
|-------|-----------|-----|
| Timezone mismatch (offset-naive vs offset-aware) | ORM `Mapped[datetime]` produces `TIMESTAMP WITHOUT TIME ZONE`; code sends UTC-aware datetimes | Added `type_annotation_map = {datetime: DateTime(timezone=True)}` to `Base` |
| `::jsonb` cast syntax error | asyncpg uses `$N` parameter syntax; `::jsonb` conflicts | Changed to `CAST(:param AS jsonb)` |
| `revoked` NOT NULL violation in role_assignments | Seed INSERT missing `revoked` column | Added `revoked = false` to INSERT |
| Audit middleware method mismatch | Middleware called `.record()` but AuditService exposes `.emit()` | Fixed to call `.emit()` |
| Audit middleware hardcoded event type | All HTTP requests logged as `WORKFLOW_CREATED` | Added `HTTP_REQUEST` event type |

---

## 9. Environment Configuration

Created per-environment `.env` files with the following isolation:

- `.env.dev` — DB: `syndicateclaw_dev`, Redis: db 1, Port: 8001
- `.env.staging` — DB: `syndicateclaw_staging`, Redis: db 2, Port: 8002
- `.env.prod` — DB: `syndicateclaw_prod`, Redis: db 3, Port: 8000

`Settings` class updated to resolve `.env.{SYNDICATECLAW_ENV}` with `.env` fallback.  
`migrations/env.py` updated to read `SYNDICATECLAW_DATABASE_URL` from environment.  
Helper script: `source scripts/env.sh <env>`.

---

## 10. Pre-Phase-1 Readiness Assessment

| Condition | Status |
|-----------|--------|
| Migrations 001–003 applied cleanly | **PASS** |
| Seed script idempotent and invariants pass | **PASS** |
| V1–V9 verification queries all pass | **PASS** |
| Audit denormalization populates principal_id | **PASS** |
| Rollback exercised end-to-end | **PASS** |
| Transitional scaffolding baseline recorded (3) | **PASS** |
| Unit tests green (321/321) | **PASS** |
| Environment isolation configured | **PASS** |

**Verdict: Phase 0 ACCEPTED. Ready for Phase 1 shadow evaluator development.**
