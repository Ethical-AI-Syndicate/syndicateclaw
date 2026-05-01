# Backup And Restore

## Data requiring backup

- PostgreSQL application database, including workflows, policies, RBAC, audit events, provider metadata, and run state.
- Redis if used for durable queues/session semantics in the deployed topology.
- Kubernetes manifests/config maps/secret references.
- Audit exports and integrity/signing evidence.

## RPO and RTO assumptions

RPO/RTO must be set by the customer. The repo provides migration and restore-drill helper scripts but does not enforce backup scheduling or snapshot retention.

## Encryption expectations

Database snapshots, logs, audit exports, and backups must be encrypted using customer-managed KMS/storage controls. Restore requires database credentials, API key material, IdP metadata, provider credentials, and any audit signing keys.

## Restore verification

1. Restore to an isolated database/namespace.
2. Confirm Alembic migration head/current state.
3. Start the API with staging ingress only.
4. Run health, auth, workflow read, and audit export checks.
5. Capture all outputs as change evidence.

## Post-restore integrity checks

Verify representative organizations, RBAC assignments, workflow definitions, audit continuity, and provider configuration. Confirm no dev/auth fallback is enabled.

## Rollback of bad restore

Keep the previous database and image running until validation passes. Roll back by returning traffic to the previous release and snapshot.

## Drill helper

Run `scripts/restore-drill-checklist.sh`. It prints steps only and does not mutate data.
