# Tenancy Model

## Model

`syndicateclaw` is best treated as logical multi-tenant when organizations/namespaces are shared. Physical isolation is required for customers that do not accept shared database/application tenancy.

## Boundary controls

- Enforce organization/namespace scope on every API, workflow, RBAC, and audit query.
- Keep provider credentials scoped per tenant/customer.
- Disable anonymous/dev fallback outside local development.

## Namespace, database, and schema assumptions

Default manifests deploy a shared application/database. Stronger isolation requires separate Kubernetes namespaces, databases/schemas, Redis instances, secrets, and provider credentials.

## Admin visibility risks

Application/database administrators can view cross-tenant state unless customer-controlled encryption and operational separation are added.

## Log segregation

Logs must include organization/namespace identifiers and be exportable/filterable per customer. Do not share raw cross-tenant logs externally.

## Backup segregation

Shared backups contain all tenants. Per-customer deployment is preferred where restore segregation is a buyer requirement.
