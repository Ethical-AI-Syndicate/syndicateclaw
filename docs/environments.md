# On-Demand Environments

SyndicateClaw supports four isolated environments on a shared PostgreSQL cluster:

| Environment | Port | DB | Redis DB | RBAC | Deploy Trigger |
|-------------|------|-----|----------|------|----------------|
| **dev** | 8001 | `syndicateclaw_dev` | 1 | Shadow (off) | Auto on `main` push |
| **qa** | 8002 | `syndicateclaw_qa` | 2 | Shadow (off) | Auto on `main` push + seed |
| **perf** | 8003 | `syndicateclaw_perf` | 3 | Enforced | Manual |
| **staging** | 8004 | `syndicateclaw_staging` | 4 | Enforced | Manual on tag (`v*`) |

## Quick Start

```bash
# Start all environments
docker compose -f docker-compose.env.yml up -d

# Or start a specific one
docker compose -f docker-compose.env.yml up -d syndicateclaw-dev

# Seed QA with test data
docker compose -f docker-compose.env.yml exec syndicateclaw-qa python /scripts/seed-qa.py

# Run perf load tests
docker compose -f docker-compose.env.yml up -d locust
# Open http://localhost:8089

# Tear down
docker compose -f docker-compose.env.yml down
```

## Registry

All images are pushed to `registry.mikeholownych.com/ai-syndicate/syndicateclaw`:

```
registry.mikeholownych.com/ai-syndicate/syndicateclaw:<tag>

Tags:
  - latest              → latest main build
  - main                → latest main build
  - <commit-sha>        → exact commit
  - mr-<number>         → merge request build
  - v*                  → release tag
```

## CI/CD Flow

```
MR → lint → test → build (mr-N) → deploy dev → smoke test
                    ↓
main → lint → test → build (latest) → deploy dev → deploy qa
                                                    ↓
                                               smoke test
                                                    ↓
tag v* → lint → test → build (tag) → deploy staging → smoke test
```

## Perf Environment

The perf environment includes resource constraints (1 CPU, 512MB RAM) and a Locust load testing companion:

```bash
# Start perf stack
docker compose -f docker-compose.env.yml up -d syndicateclaw-perf locust

# Run load tests
curl -X POST http://localhost:8089/swarm \
  -d "user_count=100&spawn_rate=10"
```

## Environment Variables (CI)

Set these in GitLab CI/CD settings:

| Variable | Required For | Description |
|----------|-------------|-------------|
| `REGISTRY_USER` | Build | Docker registry username |
| `REGISTRY_PASSWORD` | Build | Docker registry password |
| `STAGING_SECRET_KEY` | Staging | Production-grade secret for staging |
