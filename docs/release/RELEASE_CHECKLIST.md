# Pre-release gate

## Code quality

- [ ] `mypy src --ignore-missing-imports` — zero errors
- [ ] `ruff check src` — zero violations
- [ ] `pytest tests/` — all required tests passing; coverage targets met for governance modules

## Security

- [ ] RBAC: `rbac_enforcement_enabled` promotion path understood (see `docs/adr/0001-rbac-enforcement-promotion.md`)
- [ ] SSRF: outbound HTTP uses hardened clients for catalog sync and tools
- [ ] JWT: algorithm allowlist, `exp` (and `nbf` if used) validated in `security/auth.py`
- [ ] Audit: append-only semantics preserved; no unauthorized update/delete of audit rows

## Database

- [ ] `alembic check` — no unintended drift
- [ ] Migrations reviewed for destructive ops and lock risk

## Observability

- [ ] `/healthz` liveness
- [ ] `/readyz` readiness (DB + optional Redis / rate-limit behavior per settings)

## Deployment

- [ ] Docker image builds; non-root user
- [ ] Required environment variables documented

## Release mechanics

- [ ] `CHANGELOG.md` and version bump in `pyproject.toml`
- [ ] Git tag `vX.Y.Z` and matching container tags
