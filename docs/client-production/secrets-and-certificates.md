# Secrets & Certificates — DRAFT

**Status: DRAFT. Platform NOT SHIPPABLE. Do not commit real secrets.**

## Required material

| Item | Holder | Purpose | Custody requirement |
|---|---|---|---|
| ControlPlane permit signing key | ControlPlane | sign per-tool permits | Vault/KMS; never on disk in prod `<TBD>` |
| ControlPlane audit signing key (Ed25519) | ControlPlane | sign audit chain | Vault/KMS `<TBD>` |
| mTLS server/client certs + client CA | every host↔CP edge | mutual TLS | issued per environment; rotation `<TBD>` |
| Permit trust anchor | Code/Claw/Gate | verify permit signatures | distributed config; not secret |
| Provider API keys | Gate | model/API access | Vault/KMS, scoped per tenant `<TBD>` |
| Vault/KMS credentials | all | credential custody | platform secret store `<TBD>` |

## Rules

- No local/ambient/dev-fallback secret may satisfy production readiness.
- Vault/KMS production-shape custody is **not proven** — gate open.
- Keys, passphrases, and base64 key material must never appear in logs or evidence
  artifacts (golden-path runs are secret-scanned).

## Not proven

- Vault/KMS scoped lookup, tenant-mismatch denial, rotation, and failure behavior at
  production scale are `<TBD>`.
