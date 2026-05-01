# Identity Integration

## Supported auth modes

- JWT authentication with OIDC/JWKS settings is present.
- API key access is present where enabled by the service.
- SAML 2.0 is not implemented natively; use an identity-aware proxy or IdP bridge to OIDC.
- Azure AD, Okta, and Google Workspace can be used when they issue OIDC/JWKS-compatible tokens with required claims.
- SCIM is not implemented.

## Session/token model

The API validates bearer tokens/API keys per request. Browser sessions are not the primary model in this repo. OIDC tokens should be short-lived and validated against configured issuer, audience, and JWKS.

## MFA assumptions

MFA must be enforced by the IdP before token issuance. The service does not perform local MFA challenges.

## Group and role mapping

RBAC enforcement is application-side. IdP group/role claims must map to application roles through configured claims and seeded RBAC data. The mapping must be tested for each customer IdP.

## JIT provisioning

JIT user provisioning is not established as a production control. Treat user/org membership provisioning as an explicit admin or bootstrap workflow until proven.

## Deprovisioning

Deprovisioning must revoke IdP tokens, API keys, organization membership, RBAC assignments, and provider credentials. SCIM-based deprovisioning is a gap.

## Break-glass admin model

Break-glass should use a short-lived customer-approved credential, protected secret storage, dual approval, and post-use audit review. Do not leave anonymous/dev fallback enabled outside local development.

## Required metadata and claims

Expected OIDC inputs:

- `SYNDICATECLAW_OIDC_ISSUER` or standardized alias `AUTH_OIDC_ISSUER_URL` if mapped by deployment config
- `SYNDICATECLAW_OIDC_JWKS_URL`
- `SYNDICATECLAW_JWT_AUDIENCE` / client ID
- `sub`, `email` or equivalent principal
- group/role claim used by RBAC mapping

## Clock skew and expiry

Token expiry should be short for privileged routes. IdP and cluster clocks should stay within 5 minutes.

## Audit events

Login/auth failures, API key lifecycle, RBAC changes, workflow execution, policy denials, provider access, and admin changes must be retained with request IDs and actor IDs.
