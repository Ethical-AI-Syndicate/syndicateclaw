# Enterprise Deployment Readiness Evidence

This document records evidence found in this repository as of 2026-05-01. It is an evidence baseline, not a certification statement.

## Current Deployment Maturity Assessment

- Python/FastAPI orchestration service with Alembic migrations, PostgreSQL/Redis dependencies, Dockerfile, raw Kubernetes manifests, monitoring artifacts, and GitLab CI.
- The Dockerfile creates and runs as non-root user `app`.
- CI includes lint/format/type checks, unit/integration tests, migration checks, Bandit/pip-audit processing, Semgrep, Docker build, Trivy image scan, scheduled benchmark/chaos/security tests, and manual staging/production Kubernetes deploy jobs.
- Console UI exists under `console/` with a build script but no test or lint script.
- Raw Kubernetes `deploy/k8s/secret.yaml` intentionally contains an empty Secret object. Operators must create or inject `syndicateclaw-secrets` out-of-band before pods can start.

## Explicit Production Blockers

- The Kubernetes Secret manifest contains no data by design; customer deployments must inject required secret keys through sealed secrets, external secrets, or an equivalent controlled process.
- Raw Kubernetes manifests use placeholder image `REGISTRY_IMAGE:TAG` and fixed sample ingress host `api.syndicateclaw.dev`.
- No Helm chart or customer values validation exists in this repo.
- No executable backup/restore drill is present for PostgreSQL, Redis, audit logs, migrations, or namespace data.
- README runtime requirements currently mention Python 3.14.3 while `pyproject.toml` allows `>=3.12` and CI uses Python 3.12; this needs an explicit supported-runtime decision.
- Production identity mode depends on customer OIDC/JWKS/JWT settings and is not validated through a deployment manifest gate.

## Required Customer-Controlled Dependencies

- Customer-managed PostgreSQL for workflow, policy, audit, and inference state.
- Customer-managed Redis if cache, revocation, rate limiting, or queue behavior is enabled.
- Customer-managed Kubernetes cluster or equivalent orchestrator, registry, ingress controller, TLS issuer, and DNS.
- Customer-managed IdP/JWKS endpoint when JWT/OIDC authentication is used.
- Customer-approved provider catalog, SyndicateGate endpoint, and provider credentials.
- Customer observability stack for Prometheus, OpenTelemetry, logs, and alert routing.

## Required Secrets And Where They Must Come From

- `SYNDICATECLAW_DATABASE_URL`, database credentials, and database TLS material from customer secret management.
- `SYNDICATECLAW_SECRET_KEY`, JWT signing material, optional Ed25519 private key, and OIDC client material from customer KMS or sealed secret workflow.
- `SYNDICATECLAW_REDIS_URL` credentials if Redis authentication/TLS is enabled.
- `SYNDICATEGATE_API_KEY` and provider API keys from customer-approved secret storage.
- CI provider integration keys from protected CI/Vault variables only.
- For raw Kubernetes manifests, the `syndicateclaw-secrets` Secret must provide at least `SYNDICATECLAW_DATABASE_URL`, `SYNDICATECLAW_SECRET_KEY`, and any required Redis/provider credentials before deploying workloads.

## Required Identity Integration Assumptions

- Request authentication must be configured for JWT, API keys, or an identity-aware proxy; anonymous/dev fallback must be disabled for customer production.
- OIDC/JWKS issuer, audience, algorithm, role/permission mapping, token lifetime, and revocation behavior must be customer approved.
- RBAC enforcement must remain enabled unless a documented rollout window explicitly uses shadow mode.
- Approval authorities and break-glass paths require customer-owned role assignment and audit evidence.

## Required Network Ingress/Egress Assumptions

- API ingress must terminate TLS, enforce allowed origins, and route only approved public endpoints.
- Admin/console ingress, if enabled, must be private or identity-gated.
- Egress must be restricted to PostgreSQL, Redis, SyndicateGate, provider endpoints, OIDC/JWKS, telemetry collectors, and approved webhooks.
- Built-in outbound HTTP/webhook tools require SSRF protections plus customer egress allow-lists.

## Required Persistence, Backup, Restore, And Migration Assumptions

- PostgreSQL is authoritative for workflows, runs, memory, policies, audit events, and inference tables.
- Alembic migrations must be applied through a controlled release process and checked with `python -m alembic check`.
- Backups must include PostgreSQL, migration version, provider catalog, policy state, audit records, and any Redis data designated durable.
- Restore must prove schema compatibility, replay/lineage integrity, audit queryability, and application readiness before traffic resumes.

## Required Observability Signals

- `/healthz`, `/readyz`, request rate, latency, 4xx/5xx, workflow state transitions, tool execution denials, policy evaluations, approvals, and audit dead-letter size.
- PostgreSQL/Redis connectivity, pool exhaustion, migration version, scheduler lag, rate-limit decisions, and provider errors.
- OpenTelemetry traces for API/workflow/provider paths when configured.
- Prometheus alerts from `deploy/monitoring/alerts.yaml`, tuned to customer SLOs and routed to customer incident management.

## Required Audit/Evidence Artifacts

- CI logs for validate, unit, integration, migration, Bandit/pip-audit, Semgrep, Docker build, Trivy, and readiness check.
- Alembic migration check output and rendered Kubernetes manifests with customer secret references.
- Audit-log export/query evidence for workflow, tool, memory, approval, and policy events.
- Backup/restore drill evidence proving restored audit and workflow state.
- Provider integration test evidence where real providers are in scope.

## CI/CD Release Gates Currently Present

- `validate` runs Ruff, format check, and mypy.
- Unit and integration tests run against local PostgreSQL and Redis.
- `migration_check` rebuilds schema and runs Alembic check for migration-related changes.
- `bandit_and_audit`, `semgrep_scan`, Docker build, and Trivy image scan are present.
- Manual staging and tagged production deploy jobs use Kubernetes rollout status.

## CI/CD Release Gates Missing

- No deployment-manifest secret gate before this evidence-layer script.
- No backup/restore drill or restored audit validation gate.
- No Helm render/lint because no Helm chart is present.
- No customer OIDC/JWKS integration test gate.
- No console UI test/lint gate.
- No release provenance/signing/SBOM gate observed in the pipeline.

## Known Non-Production Defaults

- `deploy/k8s/secret.yaml` is intentionally empty and exists only to reserve the Secret name expected by the Deployment.
- `docker-compose.yml` and `docker-compose.syndicategate.yml` contain development credentials and dev-only secrets.
- `.env.example` contains placeholder secrets and local database URLs.
- Raw Kubernetes ingress host and image placeholders require customer replacement.
- CI database credentials are test-only.

## Explicit Not Production Ready Until Checklist

- [ ] Kubernetes secrets are injected from customer-controlled secret management before workloads are deployed.
- [ ] Customer deployment manifests use immutable image tags, TLS, resource controls, and explicit network policies.
- [ ] Supported Python runtime is reconciled across Dockerfile, `pyproject.toml`, README, and CI.
- [ ] Backup, restore, migration, and audit validation are executable release gates.
- [ ] Customer identity integration and RBAC enforcement are tested end to end.
- [ ] Console build, test, and lint expectations are defined.
- [ ] `scripts/enterprise-readiness-check.sh` passes in CI.
