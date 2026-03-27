# Implementation Plan — v1.4.0: Enterprise Runtime

**Sprint Duration:** 3 weeks  
**Branch:** `release/v1.4.0`  
**Spec Reference:** `v1_4_0-enterprise-runtime-revised.md`  
**Depends on:** v1.3.0 shipped; migrations `001`–`013` applied

---

## Overview

Three sequential weeks: scheduler (with correct `SKIP LOCKED` locking), multi-tenancy (NOT NULL namespaces from day one, org model, quota decorators), and performance hardening (status-aware caching, indexes, load testing baselines). The scheduler's lock fields are the most critical correctness concern; they must be implemented and tested before any HA deployment.

---

## Prerequisites

- [ ] v1.3.0 deployed; migrations through `013` applied
- [ ] `pytimeparse` and `croniter` added to runtime dependencies
- [ ] A staging environment with two scheduler instances available for HA duplicate-execution testing
- [ ] Locust installed in dev dependencies for load testing
- [ ] `SYNDICATECLAW_SCHEDULER_LOCK_LEASE_SECONDS` and `SYNDICATECLAW_SCHEDULER_BATCH_SIZE` env var slots confirmed in `Settings`
- [ ] Decision made on org role → RBAC mapping and confirmed with security: OWNER→tenant_admin, ADMIN→admin, MEMBER→operator, VIEWER→viewer
- [ ] New permissions (`org:read`, `org:manage`) added to `PERMISSION_VOCABULARY`

---

## Week 1 — Scheduled Workflows

### Milestone 1.1: Schedule Migration

**Owner:** 1 engineer  
**File:** `migrations/versions/016_workflow_schedules.py`

```python
def upgrade():
    op.create_table(
        "workflow_schedules",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("workflow_version", sa.Integer()),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("schedule_type", sa.Text(), nullable=False),
        sa.Column("schedule_value", sa.Text(), nullable=False),
        sa.Column("input_state", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("namespace", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="ACTIVE"),
        sa.Column("next_run_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("last_run_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("max_runs", sa.Integer()),
        sa.Column("run_count", sa.Integer(), nullable=False, server_default="0"),
        # Lock fields — critical for HA duplicate-execution prevention
        sa.Column("locked_by", sa.Text()),           # scheduler instance_id
        sa.Column("locked_until", sa.TIMESTAMP(timezone=True)),  # lock expiry
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )
    # Partial index on ACTIVE schedules only — most efficient for scheduler poll query
    op.create_index(
        "idx_schedules_next_run",
        "workflow_schedules",
        ["next_run_at"],
        postgresql_where=sa.text("status = 'ACTIVE'")
    )
```

---

### Milestone 1.2: Schedule Value Validation

**Owner:** 1 engineer  
**File:** `syndicateclaw/services/schedule_service.py` (validation helpers)

```python
import pytimeparse
from croniter import croniter
from datetime import datetime

def validate_schedule_value(schedule_type: str, value: str) -> datetime:
    """Validate and compute first next_run_at. Raises ValueError on invalid input."""
    if schedule_type == "CRON":
        if not croniter.is_valid(value):
            raise ValueError(f"Invalid cron expression: {value!r}")
        return croniter(value, datetime.utcnow()).get_next(datetime)
    elif schedule_type == "INTERVAL":
        seconds = pytimeparse.parse(value)
        if seconds is None:
            raise ValueError(f"Invalid interval string: {value!r}")
        return datetime.utcnow() + timedelta(seconds=seconds)
    elif schedule_type == "ONCE":
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError(f"Unknown schedule_type: {schedule_type!r}")
```

---

### Milestone 1.3: SchedulerService — SKIP LOCKED Implementation

**Owner:** 1 engineer (most critical task of the sprint)  
**File:** `syndicateclaw/services/scheduler_service.py`

```python
import asyncio
import uuid
from datetime import datetime, timedelta

class SchedulerService:
    instance_id: str = f"{socket.gethostname()}-{os.getpid()}"  # unique per process

    async def run(self):
        while True:
            try:
                await self._process_due_schedules()
            except Exception as e:
                logger.error("scheduler.poll_error", error=str(e))
            await asyncio.sleep(settings.scheduler_poll_interval)

    async def _process_due_schedules(self):
        async with get_db_session() as session:
            # SKIP LOCKED: contention-free under concurrent schedulers
            result = await session.execute(
                text("""
                    SELECT id, workflow_id, workflow_version, input_state,
                           schedule_type, schedule_value, run_count, max_runs
                    FROM workflow_schedules
                    WHERE status = 'ACTIVE'
                      AND next_run_at <= NOW()
                      AND (locked_by IS NULL OR locked_until < NOW())
                    ORDER BY next_run_at
                    LIMIT :batch_size
                    FOR UPDATE SKIP LOCKED
                """),
                {"batch_size": settings.scheduler_batch_size},
            )
            due = result.fetchall()

            for row in due:
                # Claim lock WITHIN the same transaction as the SELECT FOR UPDATE
                lock_expiry = datetime.utcnow() + timedelta(seconds=settings.scheduler_lock_lease_seconds)
                await session.execute(
                    text("""
                        UPDATE workflow_schedules
                        SET locked_by = :instance_id, locked_until = :expiry, updated_at = NOW()
                        WHERE id = :id
                    """),
                    {"instance_id": self.instance_id, "expiry": lock_expiry, "id": row.id},
                )

            # Commit lock claims before spawning tasks
            await session.commit()

            # Spawn execution tasks after commit (outside transaction)
            for row in due:
                asyncio.create_task(self._execute_and_release(row))

    async def _execute_and_release(self, schedule_row):
        try:
            # Check global run limit before creating run
            if await self._is_run_limit_reached():
                logger.warning("scheduler.deferred_run_limit_reached", schedule_id=schedule_row.id)
                await self._release_lock(schedule_row.id)
                return

            # Create workflow run
            run = await workflow_service.start_run(
                workflow_id=schedule_row.workflow_id,
                version=schedule_row.workflow_version,
                input_state=schedule_row.input_state,
                actor=f"scheduler:{self.instance_id}",
            )

            # Update schedule: next_run_at, last_run_at, run_count, clear lock
            await self._update_after_execution(schedule_row, run.id)

        except Exception as e:
            logger.error("scheduler.execution_failed", schedule_id=schedule_row.id, error=str(e))
            await self._release_lock(schedule_row.id)

    async def _release_lock(self, schedule_id: str):
        async with get_db_session() as session:
            await session.execute(
                text("UPDATE workflow_schedules SET locked_by = NULL, locked_until = NULL WHERE id = :id"),
                {"id": schedule_id}
            )
            await session.commit()
```

**Tests (spec §9.1):**
- `test_schedule_concurrent_lock_no_duplicate`: spin up two `SchedulerService` instances in the same test; trigger one due schedule; assert exactly one run created.
- `test_schedule_lock_expiry_recovered`: manually set `locked_until` in the past; assert second instance picks it up.
- `test_schedule_crash_after_lock_recovers`: set `locked_by` without `locked_until`; set `locked_until` in past; verify recovery.

**Exit gate for Week 1:** All scheduling tests pass including duplicate-execution test; no duplicate runs under concurrent schedulers.

---

## Week 2 — Multi-Tenancy

### Milestone 2.1: Organization Migration (014)

**Owner:** 1 engineer  
**Files:** `migrations/versions/014_organizations.py`, `migrations/versions/015_organization_members.py`

```python
# Migration 014
op.create_table("organizations",
    sa.Column("id", sa.Text(), primary_key=True),
    sa.Column("name", sa.Text(), nullable=False, unique=True),
    sa.Column("display_name", sa.Text(), nullable=False),
    sa.Column("owner_actor", sa.Text(), nullable=False),  # actor string, not FK
    sa.Column("namespace", sa.Text(), nullable=False, unique=True),
    sa.Column("status", sa.Text(), nullable=False, server_default="ACTIVE"),
    sa.Column("quotas", postgresql.JSONB(), nullable=False),
    sa.Column("settings", postgresql.JSONB(), nullable=False, server_default="{}"),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
)

# Migration 015
op.create_table("organization_members",
    sa.Column("id", sa.Text(), primary_key=True),
    sa.Column("organization_id", sa.Text(), sa.ForeignKey("organizations.id"), nullable=False),
    sa.Column("actor", sa.Text(), nullable=False),
    sa.Column("org_role", sa.Text(), nullable=False),    # OWNER|ADMIN|MEMBER|VIEWER
    sa.Column("rbac_role", sa.Text(), nullable=False),   # mapped RBAC role
    sa.Column("joined_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
)
op.create_unique_constraint("uq_org_members", "organization_members", ["organization_id", "actor"])
```

---

### Milestone 2.2: Namespace Migrations (Per-Table, NOT NULL)

**Owner:** 1 engineer  
**Files:** `migrations/versions/017_namespace_workflows.py` through `022_namespace_policies.py`

**Pattern for each migration** (6 separate files, one per table):

```python
# Example: 017_namespace_workflows.py
def upgrade():
    # Step 1: Add column with temporary DEFAULT for backfill
    op.add_column("workflow_definitions",
        sa.Column("namespace", sa.Text(), nullable=True, server_default="default"))

    # Step 2: Backfill all existing rows
    op.execute("UPDATE workflow_definitions SET namespace = 'default' WHERE namespace IS NULL")

    # Step 3: Enforce NOT NULL, drop DEFAULT
    op.alter_column("workflow_definitions", "namespace", nullable=False, server_default=None)

def downgrade():
    op.drop_column("workflow_definitions", "namespace")
```

Tables to migrate: `workflow_definitions`, `workflow_runs`, `agents`, `memory_records`, `agent_messages`, `policy_rules`.

**Critical:** After migration, verify with: `SELECT COUNT(*) FROM <table> WHERE namespace IS NULL` — must return 0.

---

### Milestone 2.3: OrganizationService and Quota Validation

**Owner:** 1 engineer  
**File:** `syndicateclaw/services/organization_service.py`

Key behavior:
- `create_organization(name, actor)`: derives `namespace` from name (slug); validates Pydantic `OrganizationQuotas`; creates the owner as first member with `org_role=OWNER`, `rbac_role=tenant_admin`.
- `get_actor_org(actor) -> Organization`: looks up actor's org membership. Used as a FastAPI dependency.
- `map_org_role_to_rbac(org_role: str) -> str`: OWNER→tenant_admin, ADMIN→admin, MEMBER→operator, VIEWER→viewer.
- `get_actor_permissions(actor) -> set[str]`: resolves from RBAC system using `rbac_role` from org membership — **never from JWT claims**.
- `handle_deleting_state(org_id)`: pause all active schedules; block new run creation; start cleanup background task.

**Default quota validation at startup:**
```python
# In Settings
class Settings(BaseSettings):
    organization_default_quotas: str | None = None

    @validator("organization_default_quotas")
    def validate_org_quotas(cls, v):
        if v:
            OrganizationQuotas.model_validate_json(v)  # raises on invalid JSON or schema
        return v
```

---

### Milestone 2.4: Quota Enforcement Decorators

**Owner:** 1 engineer  
**File:** `syndicateclaw/api/decorators/quota.py`

```python
def require_quota(quota_field: str, count_fn: Callable):
    """Route-level decorator for quota enforcement."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, actor_org: Organization = Depends(get_actor_org), **kwargs):
            limit = getattr(actor_org.quotas, quota_field)
            current = await count_fn(actor_org.id)
            if current >= limit:
                raise HTTPException(
                    status_code=429,
                    detail={
                        "error": "quota_exceeded",
                        "quota": quota_field,
                        "limit": limit,
                        "current": current,
                    }
                )
            return await func(*args, actor_org=actor_org, **kwargs)
        return wrapper
    return decorator
```

Apply to all creation endpoints:
```python
@router.post("/api/v1/workflows")
@require_quota("max_workflows", get_workflow_count)
async def create_workflow(...): ...

@router.post("/api/v1/agents")
@require_quota("max_agents", get_agent_count)
async def register_agent(...): ...

@router.post("/api/v1/workflows/{id}/schedule")
@require_quota("max_schedules", get_schedule_count)
async def create_schedule(...): ...

@router.post("/api/v1/memory")
@require_quota("max_memory_records", get_memory_count)
@require_quota_bytes("storage_limit_bytes", get_storage_bytes, get_request_bytes)
async def write_memory(...): ...
```

**`require_quota_bytes` for storage**: measure `len(json.dumps(value).encode())` of the incoming memory value; add to `organization_quotas_usage.storage_bytes_used`; check before insert.

---

### Milestone 2.5: Namespace Filtering in Repositories

**Owner:** 1–2 engineers  
**Files:** All repository files

**Pattern:** Every list/search query in every repository adds `WHERE namespace = :ns`. Add a code review checklist item and an integration test per repository asserting cross-namespace isolation.

**Cross-namespace access:** `admin:*` actors use explicit impersonation sessions (defined in RBAC design). No silent namespace bypass.

**Tests (spec §9.2):**
- `test_namespace_not_null_enforced`: try inserting a row with `namespace=NULL`; assert DB rejects it.
- `test_org_isolation_workflows`: actor in Org A cannot see Org B's workflows.
- `test_cross_namespace_requires_impersonation`: `admin:*` actor without impersonation session gets 403 on cross-namespace query.

**Exit gate for Week 2:** All namespace isolation tests pass; `namespace IS NULL` returns 0 rows in all tables; quota decorator tests pass for all six quota types.

---

## Week 3 — Performance Hardening

### Milestone 3.1: Status-Aware State Cache

**Owner:** 1 engineer  
**File:** `syndicateclaw/cache/state_cache.py`

```python
TTL_BY_STATUS = {
    "RUNNING":                    3600,
    "WAITING_APPROVAL":           3600,
    "WAITING_AGENT_RESPONSE":     3600,
    "PAUSED":                     600,
    "COMPLETED":                  60,   # short — run is done
    "FAILED":                     60,
    "CANCELLED":                  60,
}

async def set(self, run_id: str, state: dict, status: str):
    ttl = TTL_BY_STATUS.get(status, 300)
    key = f"syndicateclaw:run_state:{run_id}"
    await self.redis.setex(key, ttl, json.dumps(state))
```

Cache holds **state dict only** — not the full `WorkflowRun` ORM object.

---

### Milestone 3.2: Performance Indexes Migration

**Owner:** 1 engineer  
**File:** `migrations/versions/023_performance_indexes.py`

```sql
-- Run queries
CREATE INDEX IF NOT EXISTS idx_workflow_runs_status ON workflow_runs(status);
CREATE INDEX IF NOT EXISTS idx_workflow_runs_initiated_by ON workflow_runs(initiated_by);
CREATE INDEX IF NOT EXISTS idx_workflow_runs_namespace_status ON workflow_runs(namespace, status);

-- Audit queries
CREATE INDEX IF NOT EXISTS idx_audit_events_resource ON audit_events(resource_type, resource_id);
CREATE INDEX IF NOT EXISTS idx_audit_events_actor_created ON audit_events(actor, created_at DESC);

-- Schedule queries (partial index)
CREATE INDEX IF NOT EXISTS idx_schedules_next_run ON workflow_schedules(next_run_at)
    WHERE status = 'ACTIVE';
```

Use `CREATE INDEX CONCURRENTLY` in production to avoid table locks (handled in deployment runbook, not Alembic which doesn't support CONCURRENTLY in transactions).

---

### Milestone 3.3: Connection Pool Tuning

**Owner:** 1 engineer  
**File:** `syndicateclaw/db/engine.py`

```python
engine = create_async_engine(
    settings.database_url,
    pool_size=20,       # increased from 10
    max_overflow=30,    # increased from 20
    pool_pre_ping=True,
    pool_recycle=3600,
)
```

---

### Milestone 3.4: Load Testing Baselines

**Owner:** 1–2 engineers  
**Files:** `tests/perf/locustfile.py`, `tests/perf/baseline_v1.4.0.json`

**Locust scenarios:**

```python
class SyndicateClawUser(HttpUser):
    wait_time = between(0.1, 0.5)

    @task(4)
    def get_workflows(self):
        self.client.get("/api/v1/workflows", headers=self.auth_headers)

    @task(1)
    def create_and_run_workflow(self):
        wf = self.client.post("/api/v1/workflows", json=self.sample_workflow, headers=self.auth_headers)
        self.client.post(f"/api/v1/workflows/{wf.json()['id']}/runs", json={}, headers=self.auth_headers)
```

Run tests:
```bash
locust -f tests/perf/locustfile.py --headless -u 50 -r 10 --run-time 30m \
    --host https://staging.syndicateclaw.example.com \
    --json > tests/perf/baseline_v1.4.0.json
```

**Baseline document:** Commit `baseline_v1.4.0.json` to the repo. This is the reference for v2.0.0 regression comparison. Record: RPS achieved, P95 latency for GET and POST endpoints, memory RSS after 30 minutes.

**Tests:**
- `test_schedule_no_duplicates_under_load`: run scheduler load test (50 simultaneous due schedules, 2 scheduler instances); assert total runs created = 50.
- `test_memory_stability_30min`: RSS does not grow monotonically over sustained load.

---

## File Map

| File | Action | Description |
|------|--------|-------------|
| `syndicateclaw/models/organization.py` | **Create** | `Organization`, `OrganizationMember`, `OrganizationQuotas` |
| `syndicateclaw/models/workflow_schedule.py` | **Create** | `WorkflowSchedule` with `locked_by`, `locked_until` |
| `syndicateclaw/services/scheduler_service.py` | **Create** | `SchedulerService` with `SKIP LOCKED` |
| `syndicateclaw/services/schedule_service.py` | **Create** | Schedule CRUD + `validate_schedule_value` |
| `syndicateclaw/services/organization_service.py` | **Create** | Org CRUD + membership + role mapping + quota validation |
| `syndicateclaw/api/decorators/quota.py` | **Create** | `@require_quota` and `@require_quota_bytes` decorators |
| `syndicateclaw/api/routes/schedules.py` | **Create** | Schedule API endpoints |
| `syndicateclaw/api/routes/organizations.py` | **Create** | Organization API endpoints |
| `syndicateclaw/cache/state_cache.py` | **Create** | Status-aware TTL state cache |
| `syndicateclaw/db/engine.py` | **Modify** | Increase pool_size and max_overflow |
| `syndicateclaw/config.py` | **Modify** | Add scheduler, org, and quota settings; validate `DEFAULT_QUOTAS` at startup |
| `syndicateclaw/authz/route_registry.py` | **Modify** | Add all new v1.4.0 routes |
| `syndicateclaw/authz/permissions.py` | **Modify** | Add `org:read`, `org:manage` |
| `migrations/versions/014_organizations.py` | **Create** | Organizations table |
| `migrations/versions/015_organization_members.py` | **Create** | Organization members table |
| `migrations/versions/016_workflow_schedules.py` | **Create** | Schedule table with lock fields |
| `migrations/versions/017_namespace_workflows.py` | **Create** | NOT NULL namespace for workflow_definitions |
| `migrations/versions/018_namespace_runs.py` | **Create** | NOT NULL namespace for workflow_runs |
| `migrations/versions/019_namespace_agents.py` | **Create** | NOT NULL namespace for agents |
| `migrations/versions/020_namespace_memory.py` | **Create** | NOT NULL namespace for memory_records |
| `migrations/versions/021_namespace_messages.py` | **Create** | NOT NULL namespace for agent_messages |
| `migrations/versions/022_namespace_policies.py` | **Create** | NOT NULL namespace for policy_rules |
| `migrations/versions/023_performance_indexes.py` | **Create** | Additional indexes |
| `tests/perf/locustfile.py` | **Create** | Locust load test scenarios |
| `tests/perf/baseline_v1.4.0.json` | **Create** | Committed baseline results |

---

## Definition of Done

- [ ] `WorkflowSchedule` model has `locked_by` and `locked_until` fields
- [ ] `SKIP LOCKED` used in scheduler poll query; concurrent duplicate test passes
- [ ] Crashed scheduler's lock expires and is recovered; no orphaned ACTIVE schedules
- [ ] JWT contains no `permissions` claim; permissions resolved from RBAC at request time
- [ ] All namespace columns are `NOT NULL`; `namespace IS NULL` returns 0 rows in all tables
- [ ] Namespace backfill to `"default"` runs in same migration as column addition
- [ ] All 6 quota types have decorator enforcement; `storage_limit_bytes` tracked in usage table
- [ ] `SYNDICATECLAW_ORGANIZATION_DEFAULT_QUOTAS` validated at startup via Pydantic
- [ ] Cross-namespace access requires impersonation session; `admin:*` alone not sufficient
- [ ] Org DELETING state blocks new runs; cleanup job runs to completion
- [ ] `StateCache` uses status-aware TTL; completed runs use 60s TTL
- [ ] Performance indexes applied; load test baselines committed
- [ ] All new routes in RBAC route registry
- [ ] All new modules ≥80% integration test coverage
- [ ] `ruff` and `mypy` CI gates still passing
