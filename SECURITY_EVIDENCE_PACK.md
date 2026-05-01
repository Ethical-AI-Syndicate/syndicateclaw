# Security Evidence Pack

## Encryption in transit

TLS is expected at ingress/service boundaries. Internal service TLS depends on customer platform configuration.

## Encryption at rest

Database, Redis, logs, and backups depend on customer-managed infrastructure encryption. Application-level encryption must be separately validated if required.

## Auth and SSO options

JWT/OIDC JWKS and API key auth are present. SAML requires an external proxy/bridge. SCIM is not implemented.

## RBAC model

Application RBAC exists and must be seeded/configured per environment. IdP group mapping requires customer-specific validation.

## Audit logging

Audit middleware/persistence exists. Immutability requires external retention, integrity/signing output, and customer storage controls.

## Secrets handling

Use Kubernetes secret refs, external secret manager, mounted files, or protected CI variables. Do not commit production secrets.

## Vulnerability management hooks

CI includes readiness, security scans, SBOM, dependency audit, and provenance evidence. Remediation SLAs must be agreed with the customer.

## Patching model

Tagged releases with test and migration evidence. Hotfix path is documented in `RELEASE_PROCESS.md`.

## Deployment models

Customer-managed Kubernetes is represented by manifests. Shared SaaS or customer VPC architecture needs a separate data-boundary review.

## Data residency

Residency depends on selected database, cluster, logs, backups, artifacts, and external model/provider routing.

## Backup and restore

See `BACKUP_RESTORE.md` and `scripts/restore-drill-checklist.sh`.

## Incident response touchpoints

Customer SRE/security must provide IdP logs, ingress logs, database/cluster events, provider audit logs, and emergency approvers.

## Unsupported claims and known gaps

No external certification is asserted. Native SAML, SCIM, physical isolation, automated restore proof, and immutable audit storage are gaps unless supplied by deployment architecture.
