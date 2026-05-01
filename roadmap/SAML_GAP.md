# SAML 2.0 Gap

## Current Status

Native SAML 2.0 service-provider support is not implemented.

## Pilot Path

Use OIDC bearer validation through `SYNDICATECLAW_OIDC_JWKS_URL`, `SYNDICATECLAW_OIDC_ISSUER`, and `SYNDICATECLAW_JWT_AUDIENCE`, or use a customer SAML-to-OIDC gateway.

## Architecture Path

1. Add SAML metadata ingestion and ACS route.
2. Validate signatures, audience, issuer, replay windows, and clock skew.
3. Map SAML attributes/groups into existing RBAC inputs.
4. Add audit events for login, assertion failure, role mapping, and logout.

## Blockers

- OIDC/JWKS exists; native SAML does not.
- Attribute mapping needs customer IdP examples and RBAC mapping approval.

## Effort Estimate

M for gateway-backed pilot; L for native SAML SP support.
