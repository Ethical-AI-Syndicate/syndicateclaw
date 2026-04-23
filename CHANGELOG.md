## [2.1.1](https://gitlab.mikeholownych.com/ai-syndicate/[secure]/compare/v2.1.0...v2.1.1) (2026-04-23)


### Bug Fixes

* **ci:** fix mutation_test job — add mutmut config and use db job ([fe2aeea](https://gitlab.mikeholownych.com/ai-syndicate/[secure]/commit/fe2aeea0d9480123a57852c97f4a799edff6502e))
* **ci:** fix mutation_test set -e exit-code capture and add 120m timeout ([2c99911](https://gitlab.mikeholownych.com/ai-syndicate/[secure]/commit/2c9991192f0d82a25781bbffbd6df1093294d6f1))
* **ci:** pin mutmut to 3.2.0 to avoid copy_src_dir broken-symlink crash ([b7263f6](https://gitlab.mikeholownych.com/ai-syndicate/[secure]/commit/b7263f605bd690266ede4306a4f669389462efa5))
* **mutmut:** prevent Pydantic v2 rejection of injected mutant class attrs ([dd7e409](https://gitlab.mikeholownych.com/ai-syndicate/[secure]/commit/dd7e409a6dd02e9b0dabe9c026227dd6eb3c0eea))
* **testing:** ignore mutmut-injected attributes in Pydantic models ([f69adb5](https://gitlab.mikeholownych.com/ai-syndicate/[secure]/commit/f69adb5fd91384ebcc518c25b16cc4d5bfbf56a2))

# [2.1.0](https://gitlab.mikeholownych.com/ai-syndicate/[secure]/compare/v2.0.0...v2.1.0) (2026-04-19)


### Bug Fixes

* add DinD service and wait loop for docker_build ([857e441](https://gitlab.mikeholownych.com/ai-syndicate/[secure]/commit/857e4416d4d9ec2bcf7abc046142dbafb3aecb97))
* allow pip-audit to continue so check_audit_gates.py can evaluate vulnerabilities ([b87e10f](https://gitlab.mikeholownych.com/ai-syndicate/[secure]/commit/b87e10f4b9c4e65ff622c9456e1ff27835a7341b))
* **ci:** always run image build on main and restore strict deploy needs ([ec3df87](https://gitlab.mikeholownych.com/ai-syndicate/[secure]/commit/ec3df8718cfb4e06767d62df0fb3804d27ad5788))
* **ci:** bump version to bust stale Python 3.14 pip cache ([c7f33b2](https://gitlab.mikeholownych.com/ai-syndicate/[secure]/commit/c7f33b24a6a818516adc029998db75ffab04d522))
* **ci:** disable Docker TLS in docker_build to fix DinD daemon startup ([3e304d3](https://gitlab.mikeholownych.com/ai-syndicate/[secure]/commit/3e304d3196973bebf3a6600eedb2941a2fe8d88b))
* **ci:** disable git SSL verification for release job ([2adf4ac](https://gitlab.mikeholownych.com/ai-syndicate/[secure]/commit/2adf4ac5dab4eedb5b1cfaf673cf1ec4996a7a77))
* **ci:** downgrade Python from 3.14 to 3.13 to fix asyncio event loop errors ([22b3651](https://gitlab.mikeholownych.com/ai-syndicate/[secure]/commit/22b36514ca50e0a3746ac5de417f231ad861a48d))
* **ci:** install git for semantic-release job ([aca0434](https://gitlab.mikeholownych.com/ai-syndicate/[secure]/commit/aca043477956ca191d333c786390311dcbe29cd2))
* **ci:** install semantic-release plugins before running release ([94d18b3](https://gitlab.mikeholownych.com/ai-syndicate/[secure]/commit/94d18b302f608b71b33971a7e5115736729452cc))
* **ci:** make deploy and release needs optional ([f3b1dc8](https://gitlab.mikeholownych.com/ai-syndicate/[secure]/commit/f3b1dc85c64eea0365214c74654490132d901fac))
* **ci:** make release job automatic on main branch pushes ([fc1dd53](https://gitlab.mikeholownych.com/ai-syndicate/[secure]/commit/fc1dd532d905ae40453287933af045e402ecc3ac))
* **ci:** purge pip cache before install to clear stale Python 3.14 wheel metadata ([d1ebdb3](https://gitlab.mikeholownych.com/ai-syndicate/[secure]/commit/d1ebdb3b5df73385afc5a94d0ce45b5a89a65c2f))
* **ci:** remove silent bypasses in audit and mutation test gates ([c0b60a4](https://gitlab.mikeholownych.com/ai-syndicate/[secure]/commit/c0b60a451bd8c9b3b5b5114801fed32252aea099))
* **ci:** update .python-version from 3.14.3 to 3.13 ([491a3f0](https://gitlab.mikeholownych.com/ai-syndicate/[secure]/commit/491a3f0ef45702d2c13958d31554347277abd4dc))
* **ci:** use --no-cache-dir to bypass stale Python 3.14 pip cache ([fcbbb00](https://gitlab.mikeholownych.com/ai-syndicate/[secure]/commit/fcbbb0015fa1df66add1fbe6536a0cee18635316))
* **docker:** upgrade Alpine packages to patch HIGH CVEs ([0da06de](https://gitlab.mikeholownych.com/ai-syndicate/[secure]/commit/0da06de7080688edfdfd31d93f04607fda5103ca))
* handle Event loop is closed during pytest-asyncio 1.2.0 session teardown ([b6000bf](https://gitlab.mikeholownych.com/ai-syndicate/[secure]/commit/b6000bfe7ac61a6bcf56652e922634d0d6f683c4))
* handle Event loop is closed in security conftest fixtures ([3dfe36a](https://gitlab.mikeholownych.com/ai-syndicate/[secure]/commit/3dfe36ad0ec2469841cf82a3c2b9ccef8930e6cb))
* harden security checks and stabilize test infrastructure ([a8068a1](https://gitlab.mikeholownych.com/ai-syndicate/[secure]/commit/a8068a1b12330a2b803b49e8ad02ae9936a508bf))
* **integration-tests:** use NullPool in _cancel_stale_runs to prevent event loop conflicts ([8e7e9f8](https://gitlab.mikeholownych.com/ai-syndicate/[secure]/commit/8e7e9f8ff37c1669bc48f1702a84a420e69bb7a2))
* **lint:** fix ruff E501 line-too-long in _session_env fixture ([eab4ccf](https://gitlab.mikeholownych.com/ai-syndicate/[secure]/commit/eab4ccf24399b2dbd6c23713acf5db84bd31f0d9))
* **lint:** reorder python imports for ruff ([f179c13](https://gitlab.mikeholownych.com/ai-syndicate/[secure]/commit/f179c1333c01efdd696e259e7049fe8c18c418ad))
* **lint:** satisfy ruff import and context rules ([18c43d9](https://gitlab.mikeholownych.com/ai-syndicate/[secure]/commit/18c43d9c9ec4ee0021eafa57329313ba8265f239))
* merge NullPool import into existing sqlalchemy import line (ruff I001) ([7dbdb48](https://gitlab.mikeholownych.com/ai-syndicate/[secure]/commit/7dbdb488d1e4be0faf5fbcb00f3aaca705569791))
* raise postgres max_connections to 200 in CI to prevent TooManyConnectionsError ([cbc24e3](https://gitlab.mikeholownych.com/ai-syndicate/[secure]/commit/cbc24e3984f4f450e70bf6f7370becc02911c4f8))
* remove runner tag requirement ([397601c](https://gitlab.mikeholownych.com/ai-syndicate/[secure]/commit/397601ca5eb7647ddf67a8563fc3416bf02c6095))
* **test:** remove forced syndicategate db credential rewrite ([457d76a](https://gitlab.mikeholownych.com/ai-syndicate/[secure]/commit/457d76ab907e94581132b2b39f31519baffeefd8))
* **test:** resolve conftest ruff import warnings ([2232a4a](https://gitlab.mikeholownych.com/ai-syndicate/[secure]/commit/2232a4a018b6b63e2911e70aa670073c252e2a93))
* **tests:** force asyncio tests to use session event loop scope ([8955f41](https://gitlab.mikeholownych.com/ai-syndicate/[secure]/commit/8955f4141e2b9f90e9049e0cd91f2126bde20cd3))
* **tests:** make session_factory and client session-scoped ([b129309](https://gitlab.mikeholownych.com/ai-syndicate/[secure]/commit/b12930972331dbc9f8146878bec3c02c2a06675e))
* use NullPool for test environment to prevent asyncio loop errors ([1de394e](https://gitlab.mikeholownych.com/ai-syndicate/[secure]/commit/1de394e0782b3e16bf4de389d677d9f63c62b538))


### Features

* add --dry-run and --verify flags to RBAC seed script; CI autouse fixture; shadow gate tests ([6201dd2](https://gitlab.mikeholownych.com/ai-syndicate/[secure]/commit/6201dd2813f3bd5eb7fd5191dbc5bd4c21b937ad))
* **auth:** add oidc validation and gate integration ([ae7f47a](https://gitlab.mikeholownych.com/ai-syndicate/[secure]/commit/ae7f47a5ab9cd43a946f98140cff2b6741dde1b7))
* **claw:** wire admin/control-plane endpoints to real services ([2b01e8b](https://gitlab.mikeholownych.com/ai-syndicate/[secure]/commit/2b01e8b4f4c40716a4ade6e509d0b569b7056767))

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

- RBAC enforcement defaults to **enabled** (`SYNDICATECLAW_RBAC_ENFORCEMENT_ENABLED=true`); set it to `false` for shadow-only rollout and disagreement review (`docs/adr/0001-rbac-enforcement-promotion.md`).
- **Per-API-key OAuth-style scopes** are not enforced: a valid key resolves to an actor; use RBAC on that principal. Narrow per-key scopes are planned for v1.1 (see `docs/operations/RUNBOOK.md`).
- **Coverage targets** for governance modules (policy, audit, approval, authz, tools) require running the full suite against a migrated Postgres database so integration tests execute; see release checklist.
