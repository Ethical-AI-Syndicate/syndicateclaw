# Changelog

## [2.0.0] — 2026-03-27

### Added

- Automated security regression suite under `tests/security/` (pentest marker): unauthenticated API behavior, SSRF validation, workflow safety limits, JWT and checkpoint checks, DX/builder and plugin guardrails; some scenarios skipped pending heavier RBAC/DB harnesses.
- Chaos test scaffolding under `tests/chaos/` (chaos marker), skipped in CI until staging/Docker hooks exist.
- `scripts/check_benchmark_regression.py` and `tests/perf/test_smoke_benchmark.py` for scheduled pytest-benchmark JSON vs `tests/perf/baseline_v2.0.0.json` (trimmed mean/min/max/median stats for the smoke benchmark).
- CI: `security_scan` runs Bandit and pip-audit with JSON reports and `scripts/check_audit_gates.py`; optional manual `pentest` and `chaos_tests` jobs on `release/v2.0.0`; scheduled `benchmark` job.

### Notes

- Regenerate `tests/perf/baseline_v2.0.0.json` after changing the smoke benchmark or if scheduled CI runners move to meaningfully different hardware (comparison is ±10% on mean).

## [1.0.0] — 2026-03-25

### Added

- Workflow engine with stateful graph execution, pause, resume, cancel, and replay.
- Policy engine with fail-closed evaluation and audit integration.
- Human-in-the-loop approval system with authority routing.
- Namespaced memory with provenance and access controls.
- Append-only audit log with dead-letter queue and optional integrity signing.
- Inference provider layer: YAML catalog, routing, idempotency (Postgres-backed), OpenAI-compatible adapters.
- JWT and API key authentication with algorithm allowlists and optional token revocation (Redis).
- Shadow RBAC middleware (`SYNDICATECLAW_RBAC_ENFORCEMENT_ENABLED` for enforcement).
- Prometheus metrics (`/metrics`) for workflows, tools, policy, inference, and RBAC shadow.
- OpenTelemetry spans for workflow nodes, inference calls, tool execution, and auth validation.
- SSRF validation on user-controlled URL surfaces (tools, webhooks, catalog sync).

### Security

- Policy evaluation failures default to DENY (fail-closed).
- JWT `exp` / `nbf` validated; algorithms explicitly allowlisted.
- Optional `jti` revocation path when Redis is configured.

### Known limitations (v1.0)

- RBAC remains in **shadow mode** by default; enable enforcement only after operator review of shadow logs (`docs/adr/0001-rbac-enforcement-promotion.md`).
- **Per-API-key OAuth-style scopes** are not enforced: a valid key resolves to an actor; use RBAC on that principal. Narrow per-key scopes are planned for v1.1 (see `docs/operations/RUNBOOK.md`).
- **Coverage targets** for governance modules (policy, audit, approval, authz, tools) require running the full suite against a migrated Postgres database so integration tests execute; see release checklist.
