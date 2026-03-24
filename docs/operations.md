# SyndicateClaw Operations Guide

This document covers deployment, configuration, monitoring, maintenance, and troubleshooting for the SyndicateClaw platform.

---

## Deployment

### Docker Compose (Recommended for Development / Staging)

The `docker-compose.yml` at the project root brings up three services:

| Service | Image | Port | Purpose |
|---|---|---|---|
| `app` | Built from `Dockerfile` | 8000 | SyndicateClaw API |
| `postgres` | `postgres:16` | 5432 | Primary data store |
| `redis` | `redis:7-alpine` | 6379 | Memory cache |

**Start the stack:**

```bash
docker compose up -d
```

**Verify health:**

```bash
# Liveness
curl http://localhost:8000/healthz

# Readiness (checks DB, Redis, policy engine, decision ledger)
curl http://localhost:8000/readyz

# PostgreSQL
docker compose exec postgres pg_isready -U syndicateclaw

# Redis
docker compose exec redis redis-cli ping
```

**View logs:**

```bash
docker compose logs -f app
```

**Tear down (preserving data):**

```bash
docker compose down
```

**Tear down (destroying volumes):**

```bash
docker compose down -v
```

### Docker Image

The multi-stage `Dockerfile` produces a minimal runtime image:

- **Base**: `python:3.12-slim`
- **Builder stage**: Installs dependencies with pip into `/install`
- **Runtime stage**: Copies installed packages, application source, migrations, and alembic config
- **Security**: Runs as non-root user `app` (UID 1000)
- **Entrypoint**: `uvicorn syndicateclaw.api.main:app --host 0.0.0.0 --port 8000`

**Build manually:**

```bash
docker build -t syndicateclaw:latest .
```

### Production Deployment Considerations

- Place a reverse proxy (nginx, Caddy, or a cloud load balancer) in front of uvicorn for TLS termination, rate limiting, and request buffering.
- Run multiple uvicorn workers: `uvicorn syndicateclaw.api.main:app --workers 4`
- Use a managed PostgreSQL service with automated backups and failover.
- Use a managed Redis service (e.g., ElastiCache, Upstash) with persistence enabled.
- Mount secrets via environment variables or a secret manager — never bake credentials into images.

---

## Configuration Reference

All configuration is loaded from environment variables by `syndicateclaw.config.Settings` using Pydantic Settings. The env prefix is `SYNDICATECLAW_` (case-insensitive). A `.env` file is also supported.

| Variable | Type | Default | Description |
|---|---|---|---|
| `SYNDICATECLAW_DATABASE_URL` | str | **required** | Async PostgreSQL DSN (e.g., `postgresql+asyncpg://user:pass@host:5432/db`) |
| `SYNDICATECLAW_REDIS_URL` | str | `redis://localhost:6379/0` | Redis connection URL |
| `SYNDICATECLAW_API_HOST` | str | `0.0.0.0` | Host to bind the API server |
| `SYNDICATECLAW_API_PORT` | int | `8000` | Port for the API server (1–65535) |
| `SYNDICATECLAW_LOG_LEVEL` | str | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL) |
| `SYNDICATECLAW_OTEL_ENDPOINT` | str | `None` | OpenTelemetry collector gRPC endpoint (e.g., `http://localhost:4317`) |
| `SYNDICATECLAW_APPROVAL_TIMEOUT_SECONDS` | int | `3600` | Default timeout for approval requests |
| `SYNDICATECLAW_MEMORY_DEFAULT_TTL_SECONDS` | int | `2592000` (30 days) | Default TTL for memory records |
| `SYNDICATECLAW_MAX_WORKFLOW_DEPTH` | int | `10` | Maximum nesting depth for sub-workflows |
| `SYNDICATECLAW_MAX_CONCURRENT_RUNS` | int | `100` | Maximum concurrent workflow runs |
| `SYNDICATECLAW_RATE_LIMIT_REQUESTS` | int | `100` | Max requests per actor per rate window |
| `SYNDICATECLAW_RATE_LIMIT_WINDOW_SECONDS` | int | `60` | Rate limit sliding window in seconds |
| `SYNDICATECLAW_RATE_LIMIT_BURST` | int | `20` | Max burst requests allowed per 1-second sub-window |
| `SYNDICATECLAW_CORS_ORIGINS` | list[str] | `[]` | Allowed CORS origins (JSON array) |
| `SYNDICATECLAW_SECRET_KEY` | str | **required** | Secret key for signing tokens, sessions, and HMAC integrity |
| `SYNDICATECLAW_ENVIRONMENT` | str | `production` | Deployment environment. Anonymous auth only in `development`/`test`. |
| `SYNDICATECLAW_RATE_LIMIT_STRICT` | bool | `false` | If true, `/readyz` fails when rate limiting is unavailable (Redis down) |
| `SYNDICATECLAW_REQUIRE_ASYMMETRIC_SIGNING` | bool | `false` | If true, system refuses to start without Ed25519 private key |
| `SYNDICATECLAW_ED25519_PRIVATE_KEY_PATH` | str | `None` | Path to Ed25519 private key PEM file for asymmetric evidence signing |
| `SYNDICATECLAW_MEMORY_MAX_VALUE_BYTES` | int | `1048576` (1MB) | Maximum size in bytes for a memory record value |
| `SYNDICATECLAW_MEMORY_MAX_KEY_LENGTH` | int | `256` | Maximum length of a memory key string |
| `SYNDICATECLAW_MEMORY_MAX_NAMESPACE_LENGTH` | int | `128` | Maximum length of a memory namespace string |
| `SYNDICATECLAW_JWT_ALGORITHM` | str | `HS256` | JWT signing algorithm. `HS256` (symmetric) or `EdDSA` (Ed25519 asymmetric, requires `ED25519_PRIVATE_KEY_PATH`) |

**Additional variables used by the Docker Compose stack** (not prefixed, read directly):

| Variable | Default in Compose | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://syndicateclaw:syndicateclaw@postgres:5432/syndicateclaw` | Overridden in compose environment |
| `REDIS_URL` | `redis://redis:6379/0` | Overridden in compose environment |
| `ENVIRONMENT` | `development` | Environment name |
| `LOG_LEVEL` | `debug` | Logging level |

**JWT-specific variables** (referenced in `.env.example`):

| Variable | Default | Description |
|---|---|---|
| `JWT_SECRET_KEY` | — | Secret for JWT signing |
| `JWT_ALGORITHM` | `HS256` | JWT signing algorithm |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Token lifetime |

---

## Health Check Endpoints

| Endpoint | Method | Auth | Response |
|---|---|---|---|
| `/healthz` | GET | None | `{"status": "ok", "version": "0.1.0"}` — liveness probe |
| `/readyz` | GET | None | `{"status": "ready", "version": "0.1.0", "checks": {...}}` — readiness probe |
| `/api/v1/info` | GET | None | Application metadata (title, version, Python version, docs URL) |

**Liveness probe** (`/healthz`): Confirms the process is running. Suitable for Kubernetes liveness probes and basic load balancer checks. Does not verify dependencies.

**Readiness probe** (`/readyz`): Verifies all critical dependencies are reachable:
- **Database**: Executes `SELECT 1` against PostgreSQL
- **Redis**: Sends `PING` command
- **Policy engine**: Confirms the engine is initialized
- **Decision ledger**: Confirms the ledger is initialized

Returns 200 with per-check status when all checks pass. Returns 503 with `{"status": "degraded", ...}` and per-check error details when any dependency is unhealthy. Use this for Kubernetes readiness probes and deployment gates.

---

## Monitoring

### Structured Logging

SyndicateClaw uses `structlog` with JSON output. Every log line includes:

- `timestamp` (ISO 8601)
- `level` (debug, info, warning, error)
- `event` (the log message key)
- `request_id` (from `RequestIDMiddleware`, when in a request context)

Example log line:

```json
{"timestamp": "2026-03-24T12:00:00.000Z", "level": "info", "event": "http.request", "method": "POST", "path": "/api/v1/workflows/", "status": 201, "duration_ms": 42.5, "actor": "dev-agent", "request_id": "01JAQX..."}
```

### OpenTelemetry

When `SYNDICATECLAW_OTEL_ENDPOINT` is set, the application configures:

- A `TracerProvider` with service name `syndicateclaw`.
- A `BatchSpanProcessor` with an `OTLPSpanExporter` sending traces via gRPC.
- `FastAPIInstrumentor` auto-instruments all HTTP endpoints.

Audit events carry `trace_id` and `span_id` fields for correlation.

**Recommended observability stack:**

```
SyndicateClaw → OTLP gRPC → OpenTelemetry Collector → Jaeger / Tempo / Datadog
```

### Key Metrics to Monitor

| Metric | Source | Alert Threshold |
|---|---|---|
| HTTP request latency (p99) | Audit middleware `duration_ms` | > 500ms |
| HTTP error rate (5xx) | Audit middleware `status` | > 1% of requests |
| Active workflow runs | `workflow_runs` table, status=RUNNING | > 80% of `max_concurrent_runs` |
| Approval requests pending | `approval_requests` table, status=PENDING | > 10 or age > 1 hour |
| Dead letter queue size | `dead_letter_records` table (status=PENDING) | > 0 |
| Redis cache hit rate | Memory service logs | < 50% |
| PostgreSQL connection pool utilization | SQLAlchemy pool stats | > 80% |
| Memory records pending deletion | `memory_records` table, status=MARKED_FOR_DELETION | Growing unbounded |

---

## Database Migrations

Migrations are managed by Alembic. The migration scripts live in the `migrations/` directory.

### Configuration

`alembic.ini` sets:
- `script_location = migrations`
- `prepend_sys_path = src` (so Alembic can import `syndicateclaw` models)
- `sqlalchemy.url` — override via `SYNDICATECLAW_DATABASE_URL` in `migrations/env.py`

### Common Commands

```bash
# Create a new migration
alembic revision --autogenerate -m "add_new_table"

# Apply all pending migrations
alembic upgrade head

# Roll back one migration
alembic downgrade -1

# Show current revision
alembic current

# Show migration history
alembic history --verbose

# Show pending migrations
alembic check
```

### Running Migrations in Docker

```bash
docker compose exec app alembic upgrade head
```

### Migration Best Practices

- Always review autogenerated migrations before applying — check for data loss.
- Test migrations against a copy of production data before deploying.
- Keep migrations idempotent where possible.
- Never modify a migration that has been applied to production — create a new one.

---

## Backup and Restore

### PostgreSQL

**Backup:**

```bash
# Logical backup (recommended for small-medium databases)
docker compose exec postgres pg_dump -U syndicateclaw syndicateclaw > backup_$(date +%Y%m%d).sql

# Compressed backup
docker compose exec postgres pg_dump -U syndicateclaw -Fc syndicateclaw > backup_$(date +%Y%m%d).dump
```

**Restore:**

```bash
# From SQL dump
docker compose exec -T postgres psql -U syndicateclaw syndicateclaw < backup_20260324.sql

# From compressed dump
docker compose exec -T postgres pg_restore -U syndicateclaw -d syndicateclaw backup_20260324.dump
```

### Redis

Redis is used as a cache only — data can be safely lost. If persistence is needed:

```bash
# Trigger a snapshot
docker compose exec redis redis-cli BGSAVE

# Copy the dump file
docker compose cp redis:/data/dump.rdb ./redis_backup.rdb
```

### Backup Schedule

| Component | Frequency | Retention |
|---|---|---|
| PostgreSQL (full) | Daily | 30 days |
| PostgreSQL (WAL/incremental) | Continuous | 7 days |
| Redis | Not required (cache) | — |

---

## Scaling Considerations

### Horizontal Scaling

- **API servers**: Run multiple instances behind a load balancer. The application is stateless at the HTTP layer (all state is in PostgreSQL/Redis).
- **Workers**: If background tasks are introduced (retention enforcement, approval expiration), use a distributed task queue (Celery, ARQ) to avoid duplicate execution.

### Database Scaling

- **Read replicas**: Route audit log queries and list endpoints to read replicas.
- **Connection pooling**: Use PgBouncer in front of PostgreSQL for connection multiplexing if running many API instances.
- **Table partitioning**: Partition `audit_events` by `created_at` (range partitioning) for high-volume deployments. A comment in the database models already notes this.

### Redis Scaling

- **Cluster mode**: For cache partitioning across many namespaces.
- **Eviction policy**: Set `maxmemory-policy allkeys-lru` to automatically evict cold cache entries.

---

## SLO Targets

| SLO | Target | Measurement |
|---|---|---|
| API availability | 99.9% (43 min downtime/month) | Health check uptime |
| API latency (p99) | < 500ms | Audit middleware `duration_ms` |
| API latency (p50) | < 100ms | Audit middleware `duration_ms` |
| Workflow run completion rate | > 95% | Runs reaching COMPLETED vs total |
| Audit event persistence | 99.99% | Dead letter queue size ≈ 0 |
| Approval SLA | Decisions within 1 hour | `expires_at` - `created_at` on approvals |

---

## Troubleshooting

### Application Won't Start

| Symptom | Cause | Fix |
|---|---|---|
| `ValidationError: database_url` | Missing `SYNDICATECLAW_DATABASE_URL` | Set the env var or create a `.env` file |
| `ValidationError: secret_key` | Missing `SYNDICATECLAW_SECRET_KEY` | Set the env var with a random secret |
| `Connection refused` on port 5432 | PostgreSQL not running | `docker compose up postgres` and wait for health check |
| `OTEL setup failed` warning | OTLP endpoint unreachable | Set `SYNDICATECLAW_OTEL_ENDPOINT=None` or start the collector |

### Database Issues

| Symptom | Cause | Fix |
|---|---|---|
| `asyncpg.TooManyConnectionsError` | Connection pool exhausted | Increase `pool_size` / `max_overflow` or use PgBouncer |
| Alembic `Target database is not up to date` | Pending migrations | Run `alembic upgrade head` |
| Slow queries on `audit_events` | Table not partitioned | Consider range partitioning by `created_at` |

### Workflow Issues

| Symptom | Cause | Fix |
|---|---|---|
| Run stuck in `RUNNING` | Node handler hanging | Cancel the run; investigate the handler |
| Run stuck in `WAITING_APPROVAL` | No approver acted | Resume manually or expire the approval |
| `No handler registered for: X` | Missing handler in `BUILTIN_HANDLERS` | Register the handler at startup |
| `Workflow has no START node` | Malformed workflow definition | Ensure the definition includes a node with `node_type=START` |

### Tool Issues

| Symptom | Cause | Fix |
|---|---|---|
| `ToolDeniedError` | Policy engine returned DENY | Create an ALLOW policy rule for the tool |
| `ToolTimeoutError` | Handler exceeded timeout | Increase `timeout_seconds` on the tool definition |
| `SSRF blocked` | Tool tried to reach a private IP | This is working as intended; use a public URL |
| Tool not found in registry | Not registered at startup | Add to `BUILTIN_TOOLS` list or register manually |

### Memory Issues

| Symptom | Cause | Fix |
|---|---|---|
| Reads returning stale data | Redis cache not invalidated | Check Redis connectivity; clear cache manually |
| `Memory record not found` after write | Record expired or soft-deleted | Check `expires_at` and `deletion_status` |
| High Redis memory | TTL too long or too many records | Reduce TTL; configure eviction policy |

---

## Security Hardening Checklist

- [ ] Set strong, random values for `SYNDICATECLAW_SECRET_KEY` and `JWT_SECRET_KEY`
- [ ] Disable anonymous authentication fallback in production
- [ ] Replace the static API key store with a database-backed solution
- [ ] Enable TLS on the reverse proxy
- [ ] Restrict CORS origins to known frontends (`SYNDICATECLAW_CORS_ORIGINS`)
- [ ] Set `ENVIRONMENT=production` to enable production-mode behaviors
- [ ] Set `LOG_LEVEL=INFO` or `WARNING` in production (avoid DEBUG)
- [ ] Use a non-default PostgreSQL password
- [ ] Restrict PostgreSQL access to the application network only
- [ ] Enable Redis authentication (`requirepass`) and TLS
- [ ] Run the container as non-root (already configured in Dockerfile)
- [ ] Scan the Docker image for vulnerabilities (`trivy image syndicateclaw:latest`)
- [ ] Set up database backups and test restore procedures
- [ ] Enable PostgreSQL SSL connections (`sslmode=require` in DSN)
- [ ] Implement rate limiting at the reverse proxy or application layer
- [ ] Review and rotate JWT secret keys periodically
- [ ] Set up alerting on dead letter queue size and error rates
- [ ] Verify `/readyz` is used for deployment gates (not `/healthz`)
- [ ] Confirm policy RBAC is active: only `admin:`, `policy:`, or `system:` prefixed actors can manage rules
- [ ] Verify self-approval prevention is enforced in approval routes
- [ ] Confirm concurrent run admission control is active via `max_concurrent_runs`
- [ ] Verify dead letter queue is database-backed (check `dead_letter_records` table)
- [ ] Confirm memory access_policy is enforced at read/search time
- [ ] Enable EdDSA JWT signing (`SYNDICATECLAW_JWT_ALGORITHM=EdDSA`) with Ed25519 private key for asymmetric auth
- [ ] Enable checkpoint signing (automatic when `SECRET_KEY` is configured)
- [ ] Verify GET-by-ID ownership enforcement: non-owner actors see 404 on all resource endpoints
- [ ] Register namespace schemas for structured memory namespaces that require data integrity
