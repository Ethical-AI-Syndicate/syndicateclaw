# Operations runbook

1. **Starting the service** — Set `SYNDICATECLAW_DATABASE_URL`, `SYNDICATECLAW_SECRET_KEY`, and optional Redis URL. Run migrations with `alembic upgrade head`, then start the API (e.g. uvicorn).

2. **Database migrations** — Use Alembic; for zero-downtime deploys, prefer additive migrations and dual-write/dual-read phases before dropping columns.

3. **Redis unavailable** — Rate limiting may open or `/readyz` may reflect degraded state depending on `rate_limit_strict`; see `Settings`.

4. **Audit dead-letter queue** — Inspect dead-letter records via the repository/API surfaces provided for operators; retry or mark resolved per your policy.

5. **JWT key rotation** — Update signing material and deploy; for asymmetric Ed25519, rotate `SYNDICATECLAW_ED25519_PRIVATE_KEY_PATH` and matching public material used for verification.

6. **API key rotation** — Issue new keys in your API key service, revoke old keys, verify clients.

7. **Pause/resume workflows** — Use workflow run APIs (see OpenAPI) to transition run state where supported.

8. **Stuck workflow** — Inspect run status, node executions, and logs; cancel or patch state only through supported APIs.

9. **Audit persistence failures** — Check logs for emit failures; drain dead-letter paths and fix downstream DB connectivity.

10. **RBAC enforcement** — Enable `SYNDICATECLAW_RBAC_ENFORCEMENT_ENABLED=true` only after shadow mode shows acceptable agreement; see `docs/adr/0001-rbac-enforcement-promotion.md`.

## Known limitations — v1.0

### API key scope enforcement

API keys are validated for existence, revocation, and expiry. They resolve to an **actor** string used with the rest of the stack. There is **no** separate per-key scope list (e.g. `read:workflows` vs `write:workflows`) enforced at the key layer in v1.0. Authorization for routes uses **RBAC** against the resolved principal. Fine-grained per-key scopes are a **v1.1** item.

### Inference idempotency

When `SYNDICATECLAW_DATABASE_URL` is set and migrations are applied, chat/embedding idempotency uses Postgres (`InferenceEnvelope` + `IdempotencyStore`). Operators should run integration tests against a live DB before release to confirm coverage of governance paths.
