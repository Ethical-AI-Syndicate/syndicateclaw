# SyndicateClaw

Production-oriented agent orchestration platform with stateful graph-based workflows, governance-first design, and full auditability.

SyndicateClaw executes agent workflows as directed graphs where every tool invocation is policy-gated, every state transition is checkpointed, and every action is recorded in an append-only audit log. Built for teams that need to run autonomous agents in regulated or high-trust environments.

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

## Quick Start

### Docker Compose

```bash
# Clone and start the stack
git clone <repo-url> syndicateclaw
cd syndicateclaw
cp .env.example .env    # edit secrets before production use

docker compose up -d

# Verify
curl http://localhost:8000/health
# {"status": "ok", "version": "0.1.0"}

# Run database migrations
docker compose exec app alembic upgrade head

# Open the API docs
open http://localhost:8000/docs
```

### Development Setup

Requires Python 3.12+, a running PostgreSQL instance, and optionally Redis.

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install with dev dependencies
pip install -e ".[dev]"

# Configure environment
cp .env.example .env
# Edit .env with your DATABASE_URL, SECRET_KEY, etc.

# Run database migrations
alembic upgrade head

# Start the dev server
uvicorn syndicateclaw.api.main:app --reload --host 0.0.0.0 --port 8000
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
│   └── config.py               # Settings (env vars + .env)
├── tests/
│   ├── conftest.py
│   └── unit/
│       └── test_models.py
├── examples/
│   ├── incident_triage.py      # Incident response workflow
│   ├── knowledge_capture.py    # Knowledge extraction pipeline
│   ├── outbound_comms.py       # Outbound communication workflow
│   └── scheduled_memory_review.py  # Periodic memory review
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
├── .env.example                # Environment variable template
└── .gitignore
```

## Configuration

Configuration is loaded from environment variables with the `SYNDICATECLAW_` prefix. Copy `.env.example` to `.env` and edit:

```bash
SYNDICATECLAW_DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/syndicateclaw
SYNDICATECLAW_REDIS_URL=redis://localhost:6379/0
SYNDICATECLAW_SECRET_KEY=change-me-to-a-random-secret
SYNDICATECLAW_LOG_LEVEL=INFO
SYNDICATECLAW_OTEL_ENDPOINT=http://localhost:4317  # optional
```

See [docs/operations.md](docs/operations.md) for the full configuration reference.

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

## Contributing

1. Fork the repository and create a feature branch.
2. Install dev dependencies: `pip install -e ".[dev]"`
3. Run tests and linting before submitting: `pytest && ruff check src/ tests/ && mypy src/syndicateclaw`
4. Write tests for new functionality.
5. Follow the existing code style (enforced by ruff, configured in `pyproject.toml`).
6. Submit a pull request with a clear description of the change.

## License

MIT
