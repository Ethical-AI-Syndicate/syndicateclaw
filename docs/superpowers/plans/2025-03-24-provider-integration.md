# Provider Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the Phase 1 provider layer (chat + embeddings, buffered tool facade, YAML-authoritative config) per the consolidated design spec, with migrations, domain types, registry/catalog/router, ProviderService, protocol adapters, models.dev sync, API routes, and tests.

**Architecture:** New `syndicateclaw.inference` package holds types, config loading, registry, catalog, router, ProviderService, and adapters. Persistence for idempotency and decision records is additive SQLAlchemy models + Alembic. Policy integrates with existing `PolicyEngine` and audit with `AuditService`. **Provider topology comes from YAML only in Phase 1;** the database stores derived artifacts (decisions, envelopes, catalog materialization) and must not become an alternate source of truth for “which providers exist” or override YAML for operator convenience.

**Tech Stack:** Python 3.14.3+, Pydantic v2, SQLAlchemy 2 async, Alembic, httpx, existing FastAPI/structlog/OTEL stack.

**Sole design reference:** `docs/superpowers/specs/2025-03-24-provider-integration-architecture-design.md` — implement from this document, not from chat history.

**Binding constraints (do not violate):**
- **Spec-only:** Treat the spec as the implementation contract.
- **YAML authoritative:** Phase 1 provider topology and sync policy live in YAML (or env-pointed path). Do not add DB-backed provider definitions or “convenience” overrides that diverge from YAML without a new spec revision.

---

## File structure (target)

| Path | Responsibility |
|------|----------------|
| `src/syndicateclaw/inference/__init__.py` | Package exports |
| `src/syndicateclaw/inference/types.py` | Enums, Pydantic request/response/decision/routing types |
| `src/syndicateclaw/inference/errors.py` | `InferenceError` hierarchy + `RoutingFailureReason` |
| `src/syndicateclaw/inference/hashing.py` | SHA-256 canonical JSON for payloads + idempotency hash |
| `src/syndicateclaw/inference/config_schema.py` | YAML-loaded `ProviderSystemConfig` (sync, providers, routing, baseline_policies) |
| `src/syndicateclaw/inference/config_loader.py` | Load, validate, atomic reload, structured diff, `system_config_version` bump |
| `src/syndicateclaw/inference/registry.py` | `ProviderRegistry` + circuit breaker + rate-limit cooldown + runtime disable override |
| `src/syndicateclaw/inference/catalog.py` | `ModelCatalog` with indexes, atomic swap, entry status |
| `src/syndicateclaw/inference/router.py` | `InferenceRouter` deterministic pipeline + scoring + policy cache hooks |
| `src/syndicateclaw/inference/policy_gates.py` | Gate 2–3 helpers, `PolicyChain` assembly, context hash, fail-closed timeout |
| `src/syndicateclaw/inference/idempotency.py` | DB-backed `acquire`, in-progress wait policy |
| `src/syndicateclaw/inference/service.py` | `ProviderService` pipeline (infer_chat, infer_embedding, stream_chat API-only) |
| `src/syndicateclaw/inference/adapters/base.py` | `ModelProvider` protocol + shared HTTP helpers |
| `src/syndicateclaw/inference/adapters/openai_compatible.py` | OpenAI-compatible chat/embed/health |
| `src/syndicateclaw/inference/adapters/ollama.py` | Ollama-native |
| `src/syndicateclaw/inference/catalog_sync/modelsdev.py` | Fetch, validate, filter, normalize, merge, rollback |
| `src/syndicateclaw/inference/metrics.py` | OTEL metrics (low-cardinality labels only) |
| `src/syndicateclaw/db/models.py` | New tables: envelopes, decision records, pins, catalog, policy chains, routing decisions |
| `src/syndicateclaw/db/repository.py` | Repositories for new tables (or `inference/repository.py`) |
| `migrations/versions/NNN_inference_tables.py` | Additive migration |
| `src/syndicateclaw/api/routes/inference.py` | Chat, embedding, stream endpoints |
| `src/syndicateclaw/api/routes/providers.py` | Providers list, health, reload, kill switch, runtime disable |
| `src/syndicateclaw/api/dependencies.py` | Wire ProviderService, config loader |
| `src/syndicateclaw/api/main.py` | Register routers, lifespan warmup optional |
| `src/syndicateclaw/tools/builtin.py` | Register `llm_inference`, `embedding_inference` handlers |
| `providers.yaml.example` | Example topology (repo root or `deploy/`) |
| `tests/unit/inference/` | Unit tests |
| `tests/integration/test_inference_api.py` | API integration |

---

## Phase 0: Prerequisites and hygiene

### Task 0: Read spec and align policy call sites

**Files:**
- Read: `docs/superpowers/specs/2025-03-24-provider-integration-architecture-design.md`
- Read: `src/syndicateclaw/policy/engine.py`, `src/syndicateclaw/tools/executor.py`

- [ ] **Step 1:** Confirm `PolicyEngine.evaluate(resource_type, resource_id, action, actor, context)` signature; note `ToolExecutor._check_policy` mismatch.

- [ ] **Step 2:** Decide whether to fix `ToolExecutor` policy invocation in this branch or a minimal follow-up PR. If in scope: add a single adapter function that calls `evaluate` with five arguments and map `Tool` → resource_type/id. **Do not change policy semantics beyond signature correctness.**

- [ ] **Step 3:** Commit if fixing executor.

```bash
git add src/syndicateclaw/tools/executor.py tests/unit/test_tools.py
git commit -m "fix: align ToolExecutor policy evaluate signature with PolicyEngine"
```

---

## Phase 1a: Domain types and hashing (no I/O)

### Task 1: Inference types package

**Files:**
- Create: `src/syndicateclaw/inference/types.py`
- Create: `src/syndicateclaw/inference/errors.py`
- Create: `src/syndicateclaw/inference/__init__.py`
- Test: `tests/unit/inference/test_types.py`

- [ ] **Step 1:** Write failing tests that import enums and build minimal `ChatInferenceRequest` / `EmbeddingInferenceRequest` with required fields (`actor`, `trace_id`, `scope_type`, `scope_id`).

- [ ] **Step 2:** Run `pytest tests/unit/inference/test_types.py -v` — expect import/validation failures.

- [ ] **Step 3:** Implement enums and Pydantic models per spec §1 (including `InferenceDecisionRecord`, `RoutingDecision`, `PolicyChain`, `InferenceRequestEnvelope` fields, `ConcurrencyPolicy`, `ErrorCategory`, `CircuitState`, `ProviderTrustTier` defaults).

- [ ] **Step 4:** Run `pytest tests/unit/inference/test_types.py -v` — expect PASS.

- [ ] **Step 5:** Commit.

```bash
git add src/syndicateclaw/inference/ tests/unit/inference/
git commit -m "feat(inference): add core domain types and errors"
```

### Task 2: Canonical hashing

**Files:**
- Create: `src/syndicateclaw/inference/hashing.py`
- Test: `tests/unit/inference/test_hashing.py`

- [ ] **Step 1:** Test that `canonical_json_hash(obj)` returns stable SHA-256 for key reordering.

- [ ] **Step 2:** Implement `canonical_json_hash` using `json.dumps(..., sort_keys=True, separators=(",", ":"))` + UTF-8 + `hashlib.sha256`.

- [ ] **Step 3:** `pytest tests/unit/inference/test_hashing.py -v` — PASS.

- [ ] **Step 4:** Commit.

```bash
git add src/syndicateclaw/inference/hashing.py tests/unit/inference/test_hashing.py
git commit -m "feat(inference): add canonical SHA-256 payload hashing"
```

---

## Phase 1b: Database migrations and repositories

### Task 3: Alembic migration for inference tables

**Files:**
- Create: `migrations/versions/NNN_inference_provider_tables.py` (use next revision id)
- Modify: `src/syndicateclaw/db/models.py`
- Modify: `src/syndicateclaw/db/repository.py` (or new `src/syndicateclaw/inference/repository.py`)

- [ ] **Step 1:** Add SQLAlchemy models matching spec §7: `inference_request_envelopes`, `inference_decision_records`, `model_pins`, `catalog_snapshots`, `catalog_entries`, `policy_chains`, `routing_decisions` with ULID/string PKs consistent with existing `Base`.

- [ ] **Step 2:** Generate migration with `alembic revision --autogenerate -m "inference provider tables"` (adjust manually for indexes: idempotency unique on `(idempotency_key, request_hash)`, catalog indexes per spec §2.7).

- [ ] **Step 3:** Run `alembic upgrade head` against dev DB (or document docker-compose exec).

- [ ] **Step 4:** Commit.

```bash
git add migrations/versions/ src/syndicateclaw/db/models.py
git commit -m "feat(db): add inference and catalog tables"
```

### Task 4: Idempotency repository — atomic acquire

**Files:**
- Create: `src/syndicateclaw/inference/idempotency.py`
- Modify: repositories
- Test: `tests/unit/inference/test_idempotency.py` (use async session + transaction or sqlite if project supports)

- [ ] **Step 1:** Write test: two concurrent `acquire` with same key/hash → one `is_new=True`, one `is_new=False` (use asyncio tasks + unique constraint).

- [ ] **Step 2:** Implement `IdempotencyStore.acquire` using `INSERT ... ON CONFLICT` or equivalent asyncpg pattern; conflict on hash mismatch raises `IdempotencyConflictError`.

- [ ] **Step 3:** `pytest tests/unit/inference/test_idempotency.py -v` — PASS.

- [ ] **Step 4:** Commit.

```bash
git add src/syndicateclaw/inference/idempotency.py tests/unit/inference/test_idempotency.py
git commit -m "feat(inference): atomic idempotency acquire"
```

---

## Phase 1c: YAML config loader (authoritative)

### Task 5: Config schema and loader

**Files:**
- Create: `src/syndicateclaw/inference/config_schema.py`
- Create: `src/syndicateclaw/inference/config_loader.py`
- Create: `providers.yaml.example`
- Modify: `src/syndicateclaw/config.py` (optional: `SYNDICATECLAW_PROVIDERS_YAML_PATH`)
- Test: `tests/unit/inference/test_config_loader.py`

- [ ] **Step 1:** Write tests: valid YAML loads; invalid YAML rejected; reload computes diff (added/removed/modified provider ids).

- [ ] **Step 2:** Implement loader: pydantic validation, `system_config_version` monotonic bump on successful reload, **`inference_enabled` kill switch**, no secrets in YAML (only env var names).

- [ ] **Step 3:** `pytest tests/unit/inference/test_config_loader.py -v` — PASS.

- [ ] **Step 4:** Commit.

```bash
git add src/syndicateclaw/inference/config_schema.py src/syndicateclaw/inference/config_loader.py providers.yaml.example src/syndicateclaw/config.py tests/unit/inference/test_config_loader.py
git commit -m "feat(inference): YAML provider config loader with diff and version"
```

---

## Phase 1d: Registry, catalog (static), router

### Task 6: ProviderRegistry + circuit breaker

**Files:**
- Create: `src/syndicateclaw/inference/registry.py`
- Test: `tests/unit/inference/test_registry.py`

- [ ] **Step 1:** Tests for sliding-window circuit breaker state transitions, runtime disable override, rate-limit cooldown flag.

- [ ] **Step 2:** Implement registry backed by **in-memory** structures loaded from `ProviderConfig` snapshot; **never read provider list from DB.**

- [ ] **Step 3:** `pytest tests/unit/inference/test_registry.py -v` — PASS.

- [ ] **Step 4:** Commit.

### Task 7: ModelCatalog (in-memory, static seed)

**Files:**
- Create: `src/syndicateclaw/inference/catalog.py`
- Test: `tests/unit/inference/test_catalog.py`

- [ ] **Step 1:** Tests for indexes `(capability, provider_id)` and `model_id`, atomic `replace_all` for swap.

- [ ] **Step 2:** Implement catalog; seed from YAML static model lists if present; DB persistence of entries can mirror state but **YAML remains source for which providers exist**.

- [ ] **Step 3:** `pytest` — PASS.

- [ ] **Step 4:** Commit.

### Task 8: InferenceRouter

**Files:**
- Create: `src/syndicateclaw/inference/router.py`
- Create: `src/syndicateclaw/inference/policy_gates.py`
- Test: `tests/unit/inference/test_router.py`

- [ ] **Step 1:** Tests: deterministic ordering with fixed seeds; fallback chain; `NO_CANDIDATES` vs `ALL_CANDIDATES_FAILED`; sensitivity cap denies before adapter; mock policy returns DENY.

- [ ] **Step 2:** Implement pipeline per spec §2 with scoring weights, pre-filter prune, **policy cache stub** with TTL interface, `RoutingConstraints` → `RoutingDecision`.

- [ ] **Step 3:** `pytest tests/unit/inference/test_router.py -v` — PASS.

- [ ] **Step 4:** Commit.

---

## Phase 1e: Adapters — contract tests first

### Task 9: Mock HTTP server + OpenAI-compatible adapter contract

**Files:**
- Create: `src/syndicateclaw/inference/adapters/openai_compatible.py`
- Create: `src/syndicateclaw/inference/adapters/base.py`
- Test: `tests/unit/inference/test_adapter_openai_contract.py`

- [ ] **Step 1:** Use `httpx` ASGI mock or `respx`/`pytest-httpx` if already in tree; otherwise minimal `starlette` app in tests.

- [ ] **Step 2:** Contract tests: list models, chat, embedding, health, timeout, malformed JSON → validation error, 404 vs 400 behavior per spec §4.

- [ ] **Step 3:** Implement adapter; validate response JSON schema before returning.

- [ ] **Step 4:** `pytest tests/unit/inference/test_adapter_openai_contract.py -v` — PASS.

- [ ] **Step 5:** Commit.

### Task 10: Ollama adapter contract

**Files:**
- Create: `src/syndicateclaw/inference/adapters/ollama.py`
- Test: `tests/unit/inference/test_adapter_ollama_contract.py`

- [ ] **Step 1:** Mock Ollama `/api/tags`, `/api/chat`, `/api/embed` (or official paths per Ollama docs).

- [ ] **Step 2:** Implement adapter per spec; health strategy `TAGS_LIST`.

- [ ] **Step 3:** `pytest` — PASS.

- [ ] **Step 4:** Commit.

---

## Phase 1f: ProviderService

### Task 11: ProviderService core pipeline

**Files:**
- Create: `src/syndicateclaw/inference/service.py`
- Modify: `src/syndicateclaw/inference/repository.py` (decision/routing persistence)
- Test: `tests/unit/inference/test_provider_service.py`

- [ ] **Step 1:** Tests with fake adapters: happy path; policy DENY; routing failure; fallback chain; **global latency cap** exceeded; **config version** captured at start and used in revalidation; idempotency hit.

- [ ] **Step 2:** Implement `infer_chat` / `infer_embedding` per spec §4; resolve env once per request; record `InferenceDecisionRecord`; emit audit events (`INFERENCE_*` — add to `AuditEventType` in `models.py` if needed).

- [ ] **Step 3:** `pytest tests/unit/inference/test_provider_service.py -v` — PASS.

- [ ] **Step 4:** Commit.

### Task 12: Streaming path (API-only)

**Files:**
- Modify: `src/syndicateclaw/inference/service.py`
- Test: `tests/unit/inference/test_provider_service_stream.py`

- [ ] **Step 1:** Test provisional decision record EXECUTING → COMPLETED; stream failure marks FAILED.

- [ ] **Step 2:** Implement `stream_chat` calling adapter; tool code path must not import this in handlers.

- [ ] **Step 3:** `pytest` — PASS.

- [ ] **Step 4:** Commit.

---

## Phase 1g: models.dev sync

### Task 13: ModelsDevCatalogSync

**Files:**
- Create: `src/syndicateclaw/inference/catalog_sync/modelsdev.py`
- Modify: `src/syndicateclaw/inference/catalog.py`
- Test: `tests/unit/inference/test_modelsdev_sync.py`

- [ ] **Step 1:** Fixture tests with recorded `api.json` snippets: full abort on parse failure; per-record skip; anomaly 50% drop; atomic swap; rollback API.

- [ ] **Step 2:** Implement sync per spec §3; integrate `security.ssrf` for fetch URL validation; single-flight lock.

- [ ] **Step 3:** `pytest tests/unit/inference/test_modelsdev_sync.py -v` — PASS.

- [ ] **Step 4:** Commit.

---

## Phase 1h: API routes and tools

### Task 14: FastAPI routes

**Files:**
- Create: `src/syndicateclaw/api/routes/inference.py`
- Create: `src/syndicateclaw/api/routes/providers.py`
- Modify: `src/syndicateclaw/api/main.py`, `src/syndicateclaw/api/dependencies.py`
- Modify: `src/syndicateclaw/authz/route_registry.py` (permissions for new routes)
- Test: `tests/integration/test_inference_api.py`

- [ ] **Step 1:** Integration test with `httpx.AsyncClient` + lifespan: chat POST returns 200 with mock adapter; kill switch returns 503; reload validates.

- [ ] **Step 2:** Wire routers under `/api/v1/` per spec §5.6; **no `model_id` in metric labels**.

- [ ] **Step 3:** `pytest tests/integration/test_inference_api.py -v` — PASS.

- [ ] **Step 4:** Commit.

### Task 15: Tool facades

**Files:**
- Modify: `src/syndicateclaw/tools/builtin.py`
- Modify: tool registration in `src/syndicateclaw/api/main.py` or wherever tools register
- Test: `tests/integration/test_inference_tools.py`

- [ ] **Step 1:** Test tool execute calls `infer_chat` only (assert not `stream_chat`).

- [ ] **Step 2:** Register `llm_inference` and `embedding_inference` with schemas; pass `ExecutionContext` into request building.

- [ ] **Step 3:** `pytest` — PASS.

- [ ] **Step 4:** Commit.

---

## Phase 1i: Policy simulation and baseline policies

### Task 16: Policy simulation endpoint + baseline seed

**Files:**
- Modify: `src/syndicateclaw/api/routes/policy.py` or new route module
- Optional: seed baseline deny rules from YAML into `policy_rules` table or document manual seed script

- [ ] **Step 1:** Implement `POST /api/v1/policies/simulate` returning gate outcomes (mock or real PolicyEngine calls).

- [ ] **Step 2:** Document how baseline policies from YAML map to `PolicyRule` rows (script in `scripts/` optional).

- [ ] **Step 3:** Commit.

---

## Phase 1j: Hardening and chaos

### Task 17: Chaos and load tests (optional CI)

**Files:**
- Create: `tests/scenarios/test_inference_chaos.py`

- [ ] **Step 1:** Tests: slow provider (delayed response), malformed body, provider killed mid-request.

- [ ] **Step 2:** Commit.

### Task 18: Metrics and audit retry hook

**Files:**
- Create: `src/syndicateclaw/inference/metrics.py`
- Modify: `src/syndicateclaw/inference/service.py`

- [ ] **Step 1:** Emit low-cardinality metrics; queue wait histogram stub.

- [ ] **Step 2:** Wire audit emit retry to existing dead-letter or background task pattern (minimal).

- [ ] **Step 3:** Commit.

---

## Rollout gates (staging checklist)

Before enabling in production:

- [ ] Policy chain complete for sample requests (tool + API path).
- [ ] Fallback chain behaves per spec; `ALL_CANDIDATES_FAILED` vs `NO_CANDIDATES` distinct.
- [ ] Sensitivity and `max_allowed_sensitivity` enforced; baseline UNTRUSTED rules effective.
- [ ] Deterministic routing: same inputs + same catalog snapshot + same config version → same primary candidate.
- [ ] Idempotency: concurrent acquire safe; hash conflict rejected.
- [ ] Config reload: in-flight request bound to old `system_config_version` (add explicit test).
- [ ] YAML remains authoritative: no provider-only-in-DB code paths.

---

## Plan review

After drafting, optionally run plan-document-reviewer with context: this file + the spec path.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2025-03-24-provider-integration.md`.

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks.

**2. Inline Execution** — execute tasks in this session using executing-plans with checkpoints.

Which approach do you want?
