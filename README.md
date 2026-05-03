# SyndicateClaw

Runtime approval enforcement for sensitive AI execution.

SyndicateClaw is the enterprise approval add-on for the AI Syndicate runtime execution enforcement suite. When Gate receives a sensitive request, it creates a Claw approval task. The request blocks until an approver acts, then Gate resumes or terminates the same request with the same correlation ID.

## Gate Approval Path

1. Gate receives a sensitive request and sends the approval checkpoint to SyndicateClaw.
2. SyndicateClaw creates a pending approval task for an authorized operator.
3. Gate blocks execution before the provider call while the approval is pending.
4. Approval resumes the same Gate request; rejection terminates it cleanly with no provider call.

## Architecture Overview

```
  API Gateway (FastAPI)
       │
  Service Layer
  ├── Workflow Engine   — graph-based execution with retry & checkpoints
  ├── Tool Executor     — policy-gated, timeout-enforced tool invocations
  ├── Memory Service    — namespaced key-value store with provenance tracking
  ├── Policy Engine     — fail-closed RBAC with condition-based rules
  ├── Approval Service  — human-in-the-loop gates with expiration
  └── Audit Service     — append-only event log with OpenTelemetry tracing
       │
  Persistence
  ├── PostgreSQL        — state, definitions, audit log
  └── Redis             — memory cache (optional, graceful degradation)
```

See [docs/architecture.md](docs/architecture.md) for the full architecture document.

## Deployment Reality Checks

- **RBAC mode**: `SYNDICATECLAW_RBAC_ENFORCEMENT_ENABLED` defaults to `true` (enforcement on). Set it to `false` to run shadow-only during a rollout window.
- **API key scope model**: OAuth-style per-key scopes are stored and validated at key creation, but request authorization is still decided by the resolved actor's RBAC permissions (not by key scope alone).
- **Python runtime**: SyndicateClaw requires Python 3.12 or newer, matching the verified package metadata.

See [docs/operations.md](docs/operations.md) for runtime preflight checks and an upgrade path.

## First Run

Install the SyndicateClaw package for your platform, then start the approval service:

```bash
syndicateclaw start
```

When Gate sends a sensitive request, SyndicateClaw creates a pending approval task. The operator approves or rejects that task from the approval surface, and Gate resumes or terminates the same request with the same correlation ID.

The approval surface shows pending tasks immediately. A granted approval resumes the waiting Gate request; a rejection ends it cleanly with no provider call.

Verify readiness:

```bash
curl http://localhost:8000/healthz
```

## API Endpoints

All endpoints are under `/api/v1/` and require JWT or API key authentication (anonymous fallback in development).

| Group | Prefix | Key Endpoints |
|---|---|---|
| **Workflows** | `/api/v1/workflows` | Create, list, get definitions; start/pause/resume/cancel/replay runs; get node executions and timeline |
| **Tools** | `/api/v1/tools` | List tools, get tool details, execute a tool |
| **Memory** | `/api/v1/memory` | Write, read, search, update, delete records; get lineage |
| **Policies** | `/api/v1/policies` | CRUD policy rules, evaluate policies |
| **Approvals** | `/api/v1/approvals` | List pending, approve, reject, get by run |
| **Audit** | `/api/v1/audit` | Query events, get by trace ID, get run timeline |
| **System** | `/health`, `/api/v1/info` | Health check, application info |

Interactive API documentation is available at `/docs` (Swagger UI) and `/redoc` (ReDoc).

## Project Structure

```
syndicateclaw/
├── src/syndicateclaw/
│   ├── api/                    # FastAPI gateway
│   │   ├── main.py             #   App factory, lifespan, middleware
│   │   ├── middleware.py       #   RequestID and audit middleware
│   │   ├── dependencies.py     #   Dependency injection (auth, services)
│   │   └── routes/
│   │       ├── workflows.py    #     Workflow CRUD and run lifecycle
│   │       ├── tools.py        #     Tool listing and execution
│   │       ├── memory.py       #     Memory CRUD and lineage
│   │       ├── policy.py       #     Policy rule CRUD and evaluation
│   │       ├── approvals.py    #     Approval lifecycle
│   │       └── audit.py        #     Audit event queries
│   ├── orchestrator/           # Workflow engine
│   │   ├── engine.py           #   Graph executor, safe condition parser
│   │   └── handlers.py         #   Built-in node handlers
│   ├── tools/                  # Tool framework
│   │   ├── registry.py         #   Explicit tool registry
│   │   ├── executor.py         #   Policy-gated execution with timeouts
│   │   └── builtin.py          #   Built-in tools (http_request, memory_*)
│   ├── memory/                 # Memory service
│   │   ├── service.py          #   CRUD with provenance and caching
│   │   └── retention.py        #   TTL enforcement and purging
│   ├── policy/                 # Policy engine
│   │   └── engine.py           #   Fail-closed rule evaluation (fnmatch)
│   ├── approval/               # Approval service
│   │   └── service.py          #   Human-in-the-loop gates
│   ├── audit/                  # Audit logging
│   │   ├── service.py          #   Append-only event persistence
│   │   ├── events.py           #   In-process event bus
│   │   ├── tracing.py          #   OpenTelemetry setup
│   │   └── dead_letter.py      #   Failed event queue with retry
│   ├── channels/               # Channel connectors
│   │   ├── __init__.py         #   ChannelConnector protocol
│   │   ├── webhook.py          #   Outbound HTTP with SSRF protection
│   │   └── console.py          #   Local development logger
│   ├── inference/              # Model catalog, provider routing, idempotency
│   │   ├── service.py          #   ProviderService execution path
│   │   └── catalog_sync/       #   models.dev-style feed fetch (SSRF-checked)
│   ├── observability/          # Prometheus metric definitions
│   ├── authz/                  # RBAC evaluator, route registry, shadow middleware
│   ├── runtime/                # Phase 1 skill/runtime contracts (experimental)
│   ├── security/               # Auth & SSRF protection
│   │   ├── auth.py             #   JWT creation/verification, API keys
│   │   ├── ssrf.py             #   URL validation (DNS + blocklist)
│   │   └── revocation.py     #   Optional Redis JWT revocation check
│   ├── db/                     # Database layer
│   │   ├── base.py             #   SQLAlchemy engine, session factory
│   │   ├── models.py           #   ORM table definitions (10 tables)
│   │   └── repository.py       #   Async CRUD repositories
│   ├── models.py               # Domain models (Pydantic)
│   └── config.py               # Runtime settings
├── tests/
│   ├── conftest.py
│   └── unit/
│       └── test_models.py
├── migrations/                 # Alembic database migrations
│   └── env.py
├── docs/
│   ├── architecture.md         # System architecture
│   ├── threat-model.md         # STRIDE-based threat analysis
│   ├── failure-modes.md        # Failure scenarios and recovery
│   └── operations.md           # Deployment and operations guide
├── docker-compose.yml          # Dev/staging stack
├── Dockerfile                  # Multi-stage production image
├── pyproject.toml              # Project metadata and dependencies
├── alembic.ini                 # Alembic configuration
└── .gitignore
```

## Configuration

Configuration is loaded from environment variables with the `SYNDICATECLAW_` prefix:

```bash
SYNDICATECLAW_DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/syndicateclaw
SYNDICATECLAW_REDIS_URL=redis://localhost:6379/0
SYNDICATECLAW_SECRET_KEY=change-me-to-a-random-secret
SYNDICATECLAW_LOG_LEVEL=INFO
SYNDICATECLAW_OTEL_ENDPOINT=http://localhost:4317  # optional
```

The package bootstrap path supplies the verified defaults for first run. See [docs/operations.md](docs/operations.md) for the full operator configuration reference.

## Testing

```bash
# Run all tests
pytest

# With coverage
pytest --cov=syndicateclaw --cov-report=term-missing

# Type checking
mypy src/syndicateclaw

# Linting
ruff check src/ tests/
ruff format --check src/ tests/
```

## Documentation

- [Architecture](docs/architecture.md) — system design, component descriptions, data flow, design decisions
- [Threat Model](docs/threat-model.md) — STRIDE analysis, SSRF protection, memory poisoning, cross-tenant isolation
- [Failure Modes](docs/failure-modes.md) — failure scenarios, detection, mitigation, recovery procedures
- [Operations](docs/operations.md) — deployment, configuration, monitoring, migrations, backup, scaling, troubleshooting

## Commercial Packaging

SyndicateClaw is distributed as part of the AI Syndicate commercial enforcement suite. Package builds are intended for licensed enterprise deployments where Gate uses Claw to enforce human approval before sensitive AI execution.

## License

Proprietary commercial license. Redistribution or standalone open source use is not permitted without a commercial agreement.
