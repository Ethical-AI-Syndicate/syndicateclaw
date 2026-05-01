# SCIM Gap

## Current Status

SCIM provisioning and deprovisioning is not implemented.

## Pilot Path

Use OIDC group/role claims and customer-owned IdP deprovisioning. Verify disabled users by token expiry and RBAC/audit evidence.

## Architecture Path

1. Add SCIM `/Users` and `/Groups` endpoints behind admin authentication.
2. Map external IDs to principals and role assignments.
3. Deactivate users and revoke tokens on SCIM suspend/delete.
4. Emit audit events for user and group lifecycle changes.

## Blockers

- RBAC ownership and external group mapping require product approval.
- Token revocation dependencies must be operationally proven.

## Effort Estimate

M/L depending on customer group complexity and revocation requirements.
