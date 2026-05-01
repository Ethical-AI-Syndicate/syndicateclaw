# Secrets Operations

## Required Secrets

Production requires `SYNDICATECLAW_DATABASE_URL`, `SYNDICATECLAW_REDIS_URL`, `SYNDICATECLAW_SECRET_KEY`, provider API keys, OIDC/JWT verification material where enabled, webhook credentials, encryption keys, and any customer integration tokens.

## Environments

Local development may use disposable local database and Redis credentials. Staging must use isolated non-production credentials. Production Kubernetes manifests require the `syndicateclaw-secrets` Secret to be created out-of-band with explicit keys; the checked-in Secret manifest intentionally contains no values.

## Rotation

The customer platform/security owner owns production rotation. Recommended cadence is 90 days for API tokens, immediately after exposure or personnel changes, and per customer cryptographic policy for signing/encryption keys.

## Bootstrap

Create the Kubernetes Secret through the customer external secret manager or a controlled break-glass process before rollout. Do not place plaintext or base64 production values in Git.

## Revocation

Revoke the credential at its issuer, update the secret manager, trigger a rollout, and verify `/readyz`, auth failures for the old credential, and successful provider/database access with the new credential.

## Secret Zero

Initial access to the external secret manager is customer-owned and must be audited. This repository does not provide a bootstrap credential.

## Supported Injection Methods

Supported methods are environment variables, Kubernetes `secretKeyRef`, mounted files, External Secrets Operator style sync, and protected CI/CD variables. Production must not rely on repository defaults.
