# Pilot Quickstart

## Prerequisites

- Customer Kubernetes namespace or equivalent runtime with PostgreSQL, Redis, TLS, DNS, and secret manager ownership assigned.
- OIDC issuer, JWKS URL, and audience for bearer token validation if IdP-backed access is enabled.
- Customer-owned log retention and backup target.
- Approved migration and rollback window.

## 30-Minute Deployment Path

1. Create database and Redis endpoints in the customer environment.
2. Inject `SYNDICATECLAW_DATABASE_URL`, `SYNDICATECLAW_REDIS_URL`, `SYNDICATECLAW_SECRET_KEY`, and OIDC settings from the secret manager.
3. Run `./scripts/preflight-env-check.sh`.
4. Run `./scripts/predeploy-migration-check.sh` and capture the backup evidence.
5. Deploy the image and run `./scripts/postdeploy-verify.sh`.

## Required Secrets

- `SYNDICATECLAW_DATABASE_URL`
- `SYNDICATECLAW_REDIS_URL`
- `SYNDICATECLAW_SECRET_KEY`
- `SYNDICATECLAW_OIDC_JWKS_URL`, `SYNDICATECLAW_OIDC_ISSUER`, and `SYNDICATECLAW_JWT_AUDIENCE` when OIDC bearer validation is enabled.
- Provider credentials only for enabled integrations.

## Smoke Test

```sh
PYTHONPATH=src ./scripts/preflight-env-check.sh
PYTHONPATH=src ./scripts/smoke-test.sh
PYTHONPATH=src ./scripts/postdeploy-verify.sh
```

## Rollback

Redeploy the previous approved image tag and config fingerprint. Restore database state only through the customer-approved restore procedure after impact review.

## Top 5 Common Mistakes

1. Running unit-only checks against live database fixtures.
2. Missing OIDC issuer or audience while JWKS is configured.
3. Redis defaults pointing to localhost in production.
4. Skipping backup confirmation before migrations.
5. Leaving break-glass or dev fallback paths enabled.

## Call Vendor Support When

- Unit tests pass but postdeploy verification fails.
- OIDC tokens validate locally but fail in the customer ingress path.
- RBAC seed or migration status does not match the approved release notes.
