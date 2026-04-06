# SyndicateClaw

Agent orchestration platform — graph-based workflows, policy-gated tools, append-only audit log.

## Commands

```bash
# Install
pip install -e ".[dev]"

# Dev server
uvicorn syndicateclaw.api.main:app --reload --host 0.0.0.0 --port 8000

# Tests (unit + integration — requires SYNDICATECLAW_DATABASE_URL pointing to a test DB)
pytest

# Tests — exclude integration (no DB required)
pytest -m "not integration"

# Linting / formatting
ruff check src/ tests/
ruff format --check src/ tests/

# Type checking
mypy src/syndicateclaw

# Migrations
alembic upgrade head
alembic revision --autogenerate -m "description"

# Coverage
pytest --cov=src/syndicateclaw --cov-report=term-missing
```

## Environment Setup

```bash
# Copy the template to a per-environment file (dev/staging/prod):
cp .env.example .env.dev

# Load an environment (sets SYNDICATECLAW_ENV and exports all vars):
source scripts/env.sh dev   # or staging / prod

# Required vars (SYNDICATECLAW_ prefix for all):
# SYNDICATECLAW_DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/syndicateclaw
# SYNDICATECLAW_SECRET_KEY=<random>
# SYNDICATECLAW_REDIS_URL=redis://localhost:6379/0
```

## Architecture

```
API Gateway (FastAPI) → Service Layer → PostgreSQL + Redis
```

Key packages under `src/syndicateclaw/`:
- `api/` — FastAPI routes + middleware
- `orchestrator/` — graph workflow engine
- `tools/` — policy-gated tool executor
- `memory/` — namespaced record store with provenance tracking
- `policy/` — fail-closed RBAC rule evaluation
- `authz/` — route registry + shadow RBAC middleware
- `audit/` — append-only event log, dead letter queue
- `approval/` — human-in-the-loop gates
- `inference/` — model catalog, provider routing, idempotency
- `security/` — JWT auth, API keys, SSRF protection
- `db/` — SQLAlchemy async models + repositories

## Test Markers

| Marker | Meaning |
|--------|---------|
| `integration` | Requires real DB/services |
| `requires_api_keys` | Requires real provider API keys — fails in CI without them |
| `pentest` | Security penetration scenarios (v2.0.0) |
| `chaos` | Failure injection (v2.0.0) |
| `perf` | Benchmarks — **excluded from default run**, CI scheduled job only |

Run perf explicitly: `pytest -m perf`

## Gotchas

**Alembic migration drift:** `alembic check` fails when local DB is not at head. `alembic upgrade head` can raise `DuplicateTableError` if schema objects exist but `alembic_version` is behind. Use `alembic stamp head` + manual reconciliation — do not blindly re-run migrations on existing DBs.

**Route registry keys:** `ROUTE_PERMISSION_MAP` in `authz/route_registry.py` must use FastAPI template strings exactly (e.g., `/api/v1/agents/{agent_id}` not `{id}`). A wrong key causes `ROUTE_UNREGISTERED` disagreement events — shadow metrics and enforcement will not apply to that route.

**Coverage targets:** memory ≥75% (currently 75.7%), inference ≥80% (currently 80.8%), overall ≥80%. Do not regress below these baselines. See `COVERAGE_DELTA.md` for current per-module numbers.

**Redis in tests vs production:** Tests pass without Redis (graceful degradation). In production/staging, Redis failure causes the `/readyz` probe to return 503 — treat a Redis outage as a real incident.
