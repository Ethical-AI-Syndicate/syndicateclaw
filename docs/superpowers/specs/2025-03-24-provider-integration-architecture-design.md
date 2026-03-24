# Provider Integration Architecture — Design Specification

**Status:** Approved for implementation (with incorporated hardening)  
**Scope:** Phase 1 — chat completions + embeddings; buffered tool facade; streaming via API only  
**System:** SyndicateClaw — governance-first agent orchestration platform

This document consolidates the provider abstraction, models.dev integration, local/remote providers, routing, policy, audit, configuration, security, observability, testing, and rollout. It is the single source of truth for the provider integration layer.

---

## Executive Summary

- **ProviderService** is the system of record for all inference. **Tool facades** (`llm_inference`, `embedding_inference`) are thin adapters that call ProviderService only — they do not own policy, routing, or provider topology.
- **One inference engine, multiple entry points, identical enforcement and evidence.** Gates 2–4 always run inside ProviderService for every entry path (tool and API). Gate 1 (tool coarse gate) is additive, not alternative.
- **Protocol adapters** (`OpenAICompatibleAdapter`, `OllamaAdapter`) are the default; **provider instances** are declarative configuration; **dedicated adapters** are explicit exceptions for fundamental protocol divergence. **No hooks in Phase 1.**
- **models.dev** is untrusted enrichment: fetch → validate → filter → normalize → merge; never activates providers or endpoints; never supplies auth.
- **Phase 1 capabilities:** chat + embeddings only; no reranking, multimodal, or provider-native tool calling as first-class features.
- **YAML** is the source of truth for provider topology in Phase 1; **DB** stores derived state (decision records, idempotency, catalog materialization) and never overrides YAML.

---

## 1. Core Domain Types and Interfaces

### 1.1 Enums

- `InferenceCapability`: `CHAT`, `EMBEDDING`
- `AdapterProtocol`: `OPENAI_COMPATIBLE`, `OLLAMA_NATIVE`
- `ProviderType`: `LOCAL`, `REMOTE`
- `ProviderStatus`, `HealthStrategy`, `InferenceStatus`, `DataSensitivity`
- `ConcurrencyPolicy`: `REJECT`, `QUEUE`, `SHED` — with deterministic SHED ordering: sensitivity tier (PUBLIC lowest → RESTRICTED highest), then FIFO within tier
- `ErrorCategory`: `POLICY`, `PROVIDER`, `TRANSPORT`, `TIMEOUT`, `VALIDATION`, `UNKNOWN`
- `CircuitState`: `CLOSED`, `OPEN`, `HALF_OPEN` — sliding time window with timestamped events and eviction
- `ProviderTrustTier`: `TRUSTED`, `RESTRICTED`, `UNTRUSTED` — models.dev-derived entries default `UNTRUSTED`; local providers default **network-trusted** for transport but **not** model-trusted (see §6.2)

### 1.2 Provider configuration (declarative only)

`ProviderConfig` includes: id, name, type, adapter protocol, base URL, auth (`env_var`, headers, `additional_headers`), timeout profile, capabilities, allow/deny lists, health strategy, enabled, concurrency policy + queue timeout, `max_allowed_sensitivity`, `trust_tier`, `config_version`. **No executable config** (no request/response transforms, no arbitrary health logic).

### 1.3 Model descriptor and requests

- Separate types: `ChatInferenceRequest`, `EmbeddingInferenceRequest` with shared envelope fields (actor, scope, sensitivity, trace_id).
- `model_pinning`: `required` | `preferred` | `none` — **embeddings default `required`**; chat default `preferred`.
- `ModelDescriptor`: for embedding-capable models, **`embedding_dimensions` is mandatory** at catalog ingestion.

### 1.4 Idempotency

- `InferenceRequestEnvelope`: idempotency key, request hash, timestamps, status, inference_id.
- **Rule:** same `(idempotency_key, request_hash)` → same `inference_id`; **different hash with same key → hard reject.**
- **Atomic `acquire(key, hash) -> (envelope, is_new)`** with DB uniqueness — prevents races.
- **In-progress:** if status is PENDING/EXECUTING, second caller **waits with timeout** or receives in-progress response — no duplicate execution.

### 1.5 Inference decision record

Includes: provider/model requested vs resolved, `resolved_provider_type`, `adapter_protocol`, `adapter_version`, `provider_config_version`, `catalog_snapshot_version`, `routing_decision_id`, `policy_decision_id`, `policy_chain_id`, hashes, latency breakdown (`routing_latency_ms`, `provider_latency_ms`, `queue_latency_ms`), `parent_decision_id`, `attempt_number`, `fallback_used`, structured `error_category` + `retryable`, `resolved_model_alias` when provider canonicalizes names.

### 1.6 ModelProvider protocol

Stateless adapter: `list_models`, `infer_chat`, `infer_embedding`, `stream_chat`, `health_check` — all take `ProviderConfig` per call. **`stream_chat` is API/ProviderService-only; tool facade MUST NOT call it.**

### 1.7 Payload hashing

- **SHA-256** over **canonical JSON** (sorted keys, UTF-8, defined normalization — no ambiguous whitespace). Used for request/response payload hashes and idempotency request hash. Documented in implementation.

### 1.8 Global latency cap

- `max_total_latency_ms` enforced across the entire pipeline (routing + queue + all fallback attempts). Abort when exceeded regardless of remaining fallbacks.

### 1.9 Execution-time revalidation

Before each adapter call: enabled, circuit, sensitivity, model in catalog, embedding dimensions, allow/deny lists, concurrency — **using the `system_config_version` captured at request start** (see §6.1).

---

## 2. Registry, Catalog, Routing

### 2.1 Responsibilities

- **ProviderRegistry:** configured providers + ephemeral health/circuit/rate-limit cooldown.
- **ModelCatalog:** facts about models (config + models.dev + optional runtime validation).
- **InferenceRouter:** deterministic routing; pure decision; materialized `RoutingDecision`.

### 2.2 Routing pipeline

Ordered filters: catalog lookup → explicit provider/model → pin enforcement → enabled → circuit (OPEN excluded) → health (UNAVAILABLE excluded; DEGRADED penalized) → sensitivity → **policy (cached, bounded, read-only)** → capability/latency → **explicit scoring** (status, cost, latency, sensitivity_match with `cost_weight_cap`) → deterministic tiebreak.

**Precedence:** DISABLED > CIRCUIT_OPEN > HEALTH_UNAVAILABLE > DEGRADED (penalized).

### 2.3 Fallback

- Precomputed chain; **no re-routing mid-flight.**
- Each fallback **re-runs safety checks (steps equivalent to 4–7)** before execution.
- Distinct failure reasons: `NO_CANDIDATES` vs `ALL_CANDIDATES_FAILED`.
- **Canonical identity:** `(provider_id, model_id)` — never assume cross-provider equivalence.

### 2.4 Catalog and execution

- At execution: if snapshot version changed, **re-validate** model exists and critical properties (e.g. embedding dimensions) unchanged, or fail strict / re-route per policy.

### 2.5 Policy evaluation for routing

- Shared cache key; **invalidate on RBAC/policy assignment changes.**
- Policy evaluation **fail-closed** on timeout/exception → DENY + `error_category=POLICY`.

### 2.6 Overrides

- `override_applied`, `override_rejected_reason` on `RoutingDecision`.

### 2.7 Indexing

- Index by `(capability, provider_id)` and `model_id` to avoid linear scan at scale.

---

## 3. models.dev Integration

### 3.1 Pipeline semantics

- **Fetch/parse failure → full abort** (previous catalog retained).
- **Per-record validation failure → skip record** with rejection reason.
- **Systemic anomaly → abort entire sync** (e.g. 50% drop) with optional **manual approval** before apply (`CatalogSnapshotPolicy`).

### 3.2 Trust and mapping

- **Never** use models.dev URLs or env vars for live calls — SyndicateClaw `ProviderConfig` only.
- **1:N mappings** with optional `model_filter` per mapping.
- Capability: strict allowlist first; heuristics only with **`validated_capability`** + first-use verification; mismatch → quarantine.
- **Cost** bounded in routing (`cost_weight_cap`); untrusted catalog cost may be ignored unless allowlisted.
- **Schema:** reject unexpected top-level keys / track expected structure version.
- **Sync:** single-flight lock + **atomic catalog swap**.
- **Rollback:** `rollback_to_snapshot(snapshot_version)`.
- **SSRF:** post-redirect DNS resolution check; block private/link-local/metadata IPs; scheme allowlist (https/http); document alignment with `syndicateclaw.security.ssrf`.
- **Catalog entry status:** ACTIVE, QUARANTINED, REJECTED.
- **Jitter** on sync interval.

---

## 4. ProviderService Execution

### 4.1 Steps

1. Entry validation — **generate `trace_id` if missing**
2. Idempotency — **atomic acquire**
3. Policy pre-check (capability) — **`policy_chain_id` started; `context_hash` computed once and verified downstream**
4. Route
5. Execution-time revalidation (bound to **captured `system_config_version`**)
6. Adapter execution — **response schema validation before normalization**
7. Response validation — **global latency cap**
8. Record decision + audit — **provisional record for streaming at start**
9. Return

**HTTP errors:** refine 404 → try fallback; 400/422 → fail; 409 → fail Phase 1; 401/403 → fail + degrade provider.

**Audit:** INFERENCE_STARTED / COMPLETED / FAILED; audit persistence retries via **background worker** + alerts on backlog; dead letter last resort.

**Env resolution:** resolve API key material **once per request** into request context; use same material across retries/fallbacks; log missing env as structured error before execution.

---

## 5. Policy and RBAC

### 5.1 Gates

- **Gate 1 (tool only):** `tool:execute` on `llm_inference` / `embedding_inference`
- **Gate 2:** `inference:invoke_chat` / `inference:invoke_embedding`
- **Gate 3:** per-candidate `model:use` with pre-filter prune
- **Gate 4:** runtime safety (not full policy re-eval)

**Invariant:** Tool ALLOW does **not** imply inference ALLOW — both visible under `policy_chain_id`.

### 5.2 RBAC vs PolicyEngine (post cutover)

1. RBAC DENY → hard deny  
2. RBAC ALLOW → PolicyEngine contextual rules (including REQUIRE_APPROVAL)

### 5.3 Precedence

`provider max_allowed_sensitivity` > policy DENY > REQUIRE_APPROVAL > ALLOW > default DENY.

### 5.4 Baseline policies

- UNTRUSTED: cannot receive CONFIDENTIAL/RESTRICTED (system default).
- RESTRICTED tier: explicit ALLOW required.
- Policy lint: reject dangerous `*/*` ALLOW without constraints.

### 5.5 Approvals

- Resumption re-runs Gates 2–3 with `approval_reference` in context.

### 5.6 Routes (representative)

- `/api/v1/inference/chat`, `/inference/chat/stream`, `/inference/embedding`
- `/api/v1/providers`, `/api/v1/models`, catalog sync/rollback
- `/api/v1/policies/simulate` for gate simulation

---

## 6. Configuration, Security, Observability, Testing, Rollout

### 6.1 Configuration

- **YAML source of truth** for provider topology; DB does not override YAML (derived/cache only).
- **Atomic reload** with validation; emit **structured diff** (added/removed/modified providers).
- **Per-request `system_config_version` binding** — revalidation uses the captured version, not latest global.
- **Kill switch:** `inference_enabled: bool` for immediate shutdown without redeploy.
- **Runtime provider disable** API (in-memory override) for incident response.
- **Budget guardrail:** max tokens + estimated cost threshold before execution.
- **Warmup (optional):** lightweight connectivity checks at startup; configurable fail-fast.

### 6.2 Security refinements

- Split **network trust** (local transport) vs **model trust** (not automatic). Default local tier **RESTRICTED** unless explicitly elevated.
- SSRF: explicit constraints (§3.2).
- Metrics: **no high-cardinality labels** (no `actor`, no `model_id` as labels — use logs for those).

### 6.3 Observability

- Metrics per §6 design; add **queue wait time histogram**.
- Logs: never raw prompts/responses; hashes only (SHA-256 canonical).

### 6.4 Testing

- Adapter contracts, conformance fixtures, ProviderService integration, chaos (including **slow degradation / latency inflation**), schema drift, audit replay, policy simulation.

### 6.5 Rollout phases

1. **1a:** Foundation, static catalog, no external calls  
2. **1b:** Local adapters + tools  
3. **1c:** models.dev + one tight remote provider  
4. **1d:** Streaming API  

**Staging gate checklist (not generic “review 100 records”):** verify policy_chain completeness, fallback correctness, sensitivity enforcement, deterministic routing under identical inputs, config version binding, idempotency behavior.

### 6.6 Trade-offs (additional)

- **Config sprawl** over time → future: modular YAML or composition.

---

## 7. Database Artifacts (Phase 1)

Representative tables: `inference_decision_records`, `inference_request_envelopes`, `model_pins`, `catalog_snapshots`, `catalog_entries`, `policy_chains`, `routing_decisions` — additive migrations.

---

## 8. Explicit Non-Goals (Phase 1)

- Reranking, multimodal, speech, image gen, provider-native tool calling as platform features, structured extraction guarantees, fine-tuning APIs, streaming through ToolExecutor, provider hooks.

---

## Document History

| Date | Change |
|------|--------|
| 2025-03-24 | Initial consolidated design spec from architecture review |
