# Pilot Deployment Checklist

## Customer prerequisites

- Kubernetes namespace.
- PostgreSQL and Redis plan.
- Ingress/TLS and network policy.
- Secret manager.
- IdP/OIDC configuration.
- Monitoring/logging destination.

## Required secrets

- `SYNDICATECLAW_DATABASE_URL`.
- `SYNDICATECLAW_REDIS_URL` if Redis is required.
- `SYNDICATECLAW_SECRET_KEY`.
- OIDC/JWT settings.
- Provider/API credentials.

## IdP inputs

- JWKS URL.
- Issuer.
- Audience/client ID.
- Subject/email/group/role claim mapping.
- MFA and deprovisioning policy.

## DNS and certificate inputs

- API hostname.
- TLS certificate secret/reference.
- IdP and provider DNS reachability.

## Ownership

- Backup owner: customer SRE/DBA.
- Monitoring owner: customer SRE.
- Rollback owner: joint vendor engineering and customer SRE.

## Go-live checklist

- `APP_ENV=production scripts/preflight-env-check.sh` passes.
- `scripts/smoke-test.sh` passes.
- `scripts/postdeploy-verify.sh` passes.
- Alembic status captured.
- Config fingerprint captured.
- Restore drill plan accepted.

## First-week hypercare checks

- Workflow failures.
- Provider failures.
- Auth/RBAC denial spikes.
- DB/Redis saturation.
- Audit export spot check.

## Evidence after go-live

Capture readiness, smoke/postdeploy output, migration status, config fingerprint, SBOM/provenance, backup metadata, and audit export.
