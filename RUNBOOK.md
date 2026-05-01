# Runbook

## Service Purpose

SyndicateClaw provides agent orchestration APIs, workflow runtime services, provider integrations, RBAC, and audit/event processing.

## Dependencies

Postgres, Redis, provider APIs, customer identity provider/JWKS where configured, Kubernetes ingress/TLS, and customer-managed secrets.

## Startup Procedure

Confirm backup status, run the migration predeploy check, inject `syndicateclaw-secrets`, apply manifests, and wait for init containers, `/healthz`, and `/readyz`.

## Health Indicators

Liveness is `GET /healthz`. Readiness is `GET /readyz` and includes dependency checks implemented by the application.

## Read-Only Root Filesystem Notes

The Kubernetes deployment sets `readOnlyRootFilesystem: true` and mounts `/tmp` as an `emptyDir`. Any additional runtime write path must be declared explicitly as a volume mount.

## Common Failure Modes

Missing Secret keys, failed Alembic migration, database DNS failure, Redis outage, provider credential rejection, JWKS/OIDC misconfiguration, and network policy blocking ingress.

## Log Locations And Signals

Application logs, init-container migration logs, audit/RBAC seed logs, readiness probe failures, provider timeout/error rates, and database pool errors must be captured from stdout/stderr and cluster events.

## Restart Procedure

Use Kubernetes rollout restart only after verifying migration state and dependency availability. Do not repeatedly restart during migration failures until the database revision is known.

## Secret Rotation Touchpoints

Rotate database URL/passwords, Redis credentials, `SYNDICATECLAW_SECRET_KEY`, provider keys, webhook secrets, and identity verification material. Roll pods after secret version changes.

## Deploy Rollback Procedure

Rollback image tags only after checking Alembic revision compatibility. If a migration is not backward compatible, restore from backup or apply an approved compensating migration.

## Incident Triage First 15 Minutes

Collect pod status, events, init-container logs, `/healthz`, `/readyz`, current image digest, migration revision, database/Redis status, and most recent secret version change.

## Customer SRE Inputs Needed

Provide namespace, ingress controller identity labels, database endpoint status, Redis status, secret manager version IDs, network policies, image digest, and customer change ticket.
