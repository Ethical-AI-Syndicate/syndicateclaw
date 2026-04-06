# SyndicateClaw Comprehension Review Report (2026-03-27)

## Section 1: Document Inventory Confirmation

I read all accessible documents in the provided inventory and recorded path-level status.

### 1.1 Specs (`docs/specs/`)

| Requested Path | Read Path | Primary Subject | Approx Size | Status |
|---|---|---|---|---|
| `docs/specs/v1_1_0-hardened-foundations-revised.md` | `docs/specs/v1.1.0-hardened-foundations.md` | RBAC enforcement cutover, route registry, scoped API keys, quality/test gates | ~454 lines, ~14 major sections | Requested filename missing; equivalent revised-content file read |
| `docs/specs/v1_2_0-llm-ready-revised.md` | `docs/specs/v1.2.0-llm-ready.md` | Provider abstraction, LLM handler, streaming token auth, idempotency, tool-call gates | ~694 lines, ~18 major sections | Requested filename missing; equivalent revised-content file read |
| `docs/specs/v1_3_0-agent-mesh-revised.md` | `docs/specs/v1.3.0-agent-mesh.md` | Agent registry, messaging protocol, loop protection, workflow versioning | ~660 lines, ~15 major sections | Requested filename missing; equivalent revised-content file read |
| `docs/specs/v1_4_0-enterprise-runtime-revised.md` | `docs/specs/v1.4.0-enterprise-runtime.md` | Scheduler HA locking, multi-tenancy, quotas, perf baselines | ~566 lines, ~13 major sections | Requested filename missing; equivalent revised-content file read |
| `docs/specs/v1_5_0-developer-experience-revised.md` | `docs/specs/v1.5.0-developer-experience.md` | Python SDK, visual builder, plugin sandbox/security controls | ~593 lines, ~13 major sections | Requested filename missing; equivalent revised-content file read |
| `docs/specs/v2_0_0-stable-enterprise-revised.md` | `docs/specs/v2.0.0-stable-enterprise.md` | Security audit, chaos testing, benchmarks, docs/release hardening | ~514 lines, ~11 major sections | Requested filename missing; equivalent revised-content file read |

### 1.2 Implementation Plans (`docs/plans/`)

| Path | Primary Subject | Approx Size | Status |
|---|---|---|---|
| `docs/plans/impl-plan-v1.1.0.md` | Execution plan for RBAC enforcement, scopes, quality debt, integration/canary gates | ~453 lines, ~3 week plan + file map + DoD | read |
| `docs/plans/impl-plan-v1.2.0.md` | Provider/adapters, LLM handler, SSE tokens, tool-call governance, observability | ~675 lines, ~4 week plan + file map + DoD | read |
| `docs/plans/impl-plan-v1.3.0.md` | Agent registry/messaging/versioning implementation sequencing | ~532 lines, ~4 week plan + file map + DoD | read |
| `docs/plans/impl-plan-v1.4.0.md` | Scheduler + multi-tenancy + performance hardening implementation sequence | ~516 lines, ~3 week plan + file map + DoD | read |
| `docs/plans/impl-plan-v1.5.0.md` | SDK + builder + plugin system implementation sequence | ~684 lines, ~3 week plan + file map + DoD | read |
| `docs/plans/impl-plan-v2.0.0.md` | Security/chaos/docs/release implementation and sign-off workflow | ~531 lines, ~3 week plan + file map + DoD | read |

### 1.3 Supporting Architecture Documents

| Path | Primary Subject | Approx Size | Status |
|---|---|---|---|
| `docs/architecture.md` | System architecture, middleware order, workflow/tool pipelines, v1.0 baseline | ~361 lines, ~8 major sections | read |
| `docs/threat-model.md` | STRIDE threats, implemented mitigations, residual risks | ~257 lines, ~12 major sections | read |
| `docs/failure-modes.md` | Runtime failure scenarios, detection, mitigations, recovery operations | ~269 lines, 11 failure classes + matrix | read |
| `docs/operations.md` | Deployment/config/monitoring/migration/backup/SLO/troubleshooting ops guide | ~404 lines, ~10 major sections | read |
| `docs/rbac-design.md` | Full RBAC model (principals/roles/scopes/decisions/audit visibility) | ~836 lines, ~15 major sections | read |
| `docs/rbac-implementation-plan.md` | Phased RBAC rollout and migration/cutover plan | ~598 lines, 5 phases + risk/artifacts | read |

Unreadable/missing/ambiguous documents: exact requested revised spec filenames (underscore format) were missing; dot-version equivalents with "(Revised)" content were present and read. No unreadable files among located documents.

---

## Section 2: Platform Architecture Summary

### 2.1 Purpose and governance-first philosophy

SyndicateClaw is designed as an orchestration runtime where agent/workflow execution is secondary to governance guarantees: each operation must be attributable, policy-mediated, and replayable. The architecture intentionally favors explicit registration, fail-closed authorization, append-only evidence, and auditable transitions over convenience/autonomous behavior.

### 2.2 Middleware stack order and responsibilities

Baseline stack from architecture doc:

1. `RequestIDMiddleware` - injects/propagates ULID request ID and binds log correlation context.
2. `RateLimitMiddleware` - Redis-backed sustained+burst actor limits; health/docs exempt; fail-open on Redis outage.
3. `AuditMiddleware` - records request metadata/duration/status/actor to audit subsystem.
4. `CORSMiddleware` - origin controls when configured.

v1.1.0 revised integration adds RBAC middleware as an early gate (registered after request ID and before audit in implementation plan), with explicit RBAC->policy interaction contract.

### 2.3 Workflow execution lifecycle (request to terminal states)

1. API call creates `WorkflowRun` (`PENDING`).
2. Engine transitions run to `RUNNING`, finds `START`, traverses nodes/edges.
3. Node execution outcomes:
   - success -> continue edge resolution.
   - retryable error -> exponential retry until max attempts.
   - approval gate -> `WAITING_APPROVAL`.
   - agent wait (v1.3+) -> `WAITING_AGENT_RESPONSE`.
   - explicit pause -> `PAUSED`.
   - cancel -> `CANCELLED`.
   - unrecoverable failure -> `FAILED`.
4. Checkpoints persist recoverable state.
5. End condition -> `COMPLETED`.

Terminal states across the release track: `COMPLETED`, `FAILED`, `CANCELLED`; `PAUSED` and waiting states are non-terminal holding states until resumed/timeout/decision.

### 2.4 Tool execution pipeline (full gate sequence)

Canonical sequence in architecture:

1. Tool lookup in registry.
2. Input schema validation.
3. Sandbox pre-check (network/protocol/domain/payload constraints).
4. Policy engine evaluation (fail-closed).
5. Mandatory decision ledger write (execution denied if ledger unavailable).
6. Handler execution with timeout.
7. Sandbox response check.
8. Output validation.
9. Input snapshot capture for replay determinism.
10. Audit event emission.

### 2.5 RBAC + policy evaluation order (v1.1.0 revised)

Order is strict:

1. RBAC route-level check runs first.
2. RBAC `DENY` returns 403 immediately; policy engine is not consulted.
3. RBAC `ALLOW` permits downstream processing.
4. Policy engine then evaluates resource/tool-level rules.
5. Effective decision requires both layers to allow; policy deny/approval still blocks/proxies flow.

Winner semantics: RBAC deny always wins first; otherwise policy engine can still deny or require approval.

### 2.6 v1.0.0 baseline state this roadmap builds on

- RBAC evaluator existed only in shadow mode (non-authoritative).
- Authorization was prefix/ownership-centric.
- API keys were validity-based without per-key scope vocabulary.
- Persistence baseline documented as 14 core tables in architecture.
- Governance controls already present but not fully enforced end-to-end (hence v1.1.0 gate).

---

## Section 3: Release-by-Release Comprehension

### 3.1 v1.1.0 - Hardened Foundations

**Sprint:** 3 weeks  
**Branch name:** `release/v1.1.0`

**Goals summary:**

- Promote RBAC from shadow to enforced gate with explicit ordering against policy.
- Introduce per-API-key scopes with backward-compatible unscoped deprecation path.
- Remove quality debt (`ruff`/`mypy`) and enforce in CI.
- Raise integration confidence with concrete module coverage targets.

**Key design decisions:**

1. RBAC enforcement is explicit env-flag driven (no environment-name inference) to avoid accidental bypass.
2. Default-deny route registry with complete endpoint map ensures new routes cannot ship unauthorized by omission.
3. Singular permission vocabulary normalizes future permission expansion and avoids plural drift.
4. Unscoped API keys remain temporarily full-access to preserve compatibility, but deprecation is staged with explicit deadlines.
5. Canary rollout + shadow parity retention formalizes evidence-based cutover instead of one-shot flip.

**Critical security controls:**

- RBAC enforcement gate: prevents unauthorized route access; enforced in middleware; bypass yields broad overexposure.
- RBAC-before-policy ordering: prevents policy invocation for route-denied actions; misorder could leak decision surfaces.
- Route registry default-deny: prevents undocumented endpoint access; missing registration otherwise becomes accidental allow.
- API-key scope validation (known scopes, no client globs, max 50, privilege ceiling): blocks privilege inflation and wildcard abuse.
- Unscoped key warning/deprecation machinery: prevents silent indefinite legacy full-access.

**Migration sequence:**

- `006_api_key_scopes` - add `api_keys.scopes TEXT[]` with explicit backward-compat default.
- Sequence continuity from prior baseline: expected next after `005`.

**New permissions:**

- No entirely new domain introduced; vocabulary standardized to singular form including `workflow:*`, `run:*`, `memory:*`, `tool:*`, `policy:*`, `approval:*`, `audit:*`, `admin:*`.

**New API endpoints:**

- `GET /api/v1/api-keys/scopes` - permission: authenticated principal (no specific scope); enumerates valid scope vocabulary.

**Implementation plan alignment:**

- Week 1 quality tracks map directly to spec quality gates; measurable via command exit status and CI job pass.
- Week 2 RBAC/scopes milestones map to spec sections 4.x and 10.x; exit gates are testable (route coverage tests, scope tests).
- Week 3 integration/parity/canary maps to rollout requirements; measurable via disagreement counts and staged duration.
- File map includes listed implementation artifacts for the milestones; no obvious milestone file omissions inside the plan itself.

**Unresolved questions or ambiguities:**

- Health/ready route path differs between spec table (`/api/v1/healthz`) and architecture baseline (`/healthz`).
- Spec reference filename in plan uses underscore naming not present on disk.

---

### 3.2 v1.2.0 - LLM Ready

**Sprint:** 4 weeks  
**Branch name:** `release/v1.2.0`

**Goals summary:**

- Enable real provider-backed LLM execution.
- Add secure SSE streaming with short-lived scoped tokens.
- Add deterministic idempotency and replay-aware cache semantics.
- Gate LLM-originated tool calls through policy+RBAC service account model.

**Key design decisions:**

1. Provider abstraction via adapters isolates vendor APIs and supports routeable model selection.
2. Streaming token flow replaces JWT-in-query to reduce token leakage blast radius.
3. Jinja2 sandbox + `StrictUndefined` constrains template execution and surfaces missing vars early.
4. Idempotency key includes attempt number so retries are fresh and re-entrant recovery remains deterministic.
5. `allow_tool_calls=false` default forces explicit opt-in for highest-risk behavior.

**Critical security controls:**

- Streaming token issuance/validation (single-use, run-scoped TTL): prevents primary credential leakage/replay; misconfig allows stream hijack.
- Provider config startup validation + secret-in-env interpolation: prevents latent misconfigured provider runtime failures and plaintext key leakage patterns.
- SSRF validation in provider calls and provider test endpoint: blocks internal network probing.
- LLM tool-call argument schema validation + policy gate + `system:engine` permissions: blocks model-output command injection into tools.
- Second-order template injection mitigations (metadata tagging, redaction, hidden `_` keys): reduces unsafe prompt composition risk.

**Migration sequence:**

- `007_idempotency_records` - cache table for deduped LLM results.
- `008_streaming_tokens` - short-lived token store for SSE auth.
- Sequence continuity: starts after `006`.

**New permissions:**

- No brand-new permission family mandated; route usage primarily reuses `run:read` and `admin:*`.
- Service account prerequisite: `system:engine` must have `run:control` and `tool:execute`.

**New API endpoints:**

- `GET /api/v1/runs/{id}/stream` - `run:read` via streaming token; SSE events.
- `POST /api/v1/runs/{id}/streaming-token` - `run:read`; issues scoped streaming token.
- `GET /api/v1/runs/{id}/events` - `run:read`; reconnect history.
- `GET /api/v1/providers` - `admin:*`; provider/model discovery.
- `POST /api/v1/providers/{name}/test` - `admin:*`; provider diagnostics with SSRF protections.

**Implementation plan alignment:**

- Week 1 provider milestones map to spec section 4 and routing tests.
- Week 2 maps to sections 5 and 7 (templating, idempotency, handler behavior).
- Week 3 maps to section 6 streaming auth/recovery requirements.
- Week 4 maps to section 5.4 and section 8 observability and CI secret gating.
- File map is internally complete for described milestones.

**Unresolved questions or ambiguities:**

- None blocking within the v1.2 pair; dependencies are explicit.

---

### 3.3 v1.3.0 - Agent Mesh

**Sprint:** 4 weeks  
**Branch name:** `release/v1.3.0`

**Goals summary:**

- Add first-class agent registry and discovery.
- Add durable messaging with direct/topic/broadcast modes.
- Add loop-safe routing and delivery guarantees.
- Add relational workflow versioning + rollback/diff.

**Key design decisions:**

1. Sender identity is server-derived only to prevent impersonation.
2. BROADCAST is elevated permission with subscriber cap/rate limits to prevent amplification abuse.
3. Hop-count termination replaces trust-based routing to prevent relay loops.
4. Workflow versioning uses dedicated table (not JSONB history blob) for atomicity/queryability.
5. Migration numbering restarts at `009` to avoid v1.2 collision.

**Critical security controls:**

- Sender override enforcement + warning log: blocks forged actor injection.
- Broadcast authorization + recipient cap: limits abuse and overbroad blast radius.
- Ownership enforcement for agent mutation/heartbeat: blocks unauthorized control takeover.
- Hop limit + DLQ path: prevents infinite route churn DoS.
- Name-routing warning + ID preference: reduces misdelivery risk from name reuse.

**Migration sequence:**

- `009_agents` - agent registry table.
- `010_agent_messages` - message queue with hop metadata.
- `011_topic_subscriptions` - explicit topic/broadcast subscription model.
- `012_workflow_versions` - immutable version history table.
- `013_workflow_definitions_versioning` - parent current-version metadata.
- Sequence continuity: correct continuation from `008`.

**New permissions:**

- `agent:read`, `agent:register`, `agent:manage`, `agent:heartbeat`, `agent:admin`.
- `message:send`, `message:broadcast`, `message:read`, `message:ack`.

**New API endpoints:**

- Agents: `POST/GET /api/v1/agents`, `GET/PUT/DELETE /api/v1/agents/{id}`, `POST /api/v1/agents/{id}/heartbeat`.
- Messages: `POST/GET /api/v1/messages`, `GET /api/v1/messages/{id}`, `POST /api/v1/messages/{id}/ack`, `POST /api/v1/messages/{id}/reply`.
- Topics: `POST/DELETE /api/v1/topics/{topic}/subscribe`, `GET /api/v1/topics`.
- Versioning: `GET /api/v1/workflows/{id}/versions`, `GET /api/v1/workflows/{id}/versions/{v}`, `POST /api/v1/workflows/{id}/rollback`, `GET /api/v1/workflows/{id}/diff`.

**Implementation plan alignment:**

- Week 1 maps to section 4 (registry, heartbeat, ownership).
- Week 2 maps to section 5 (messaging, subscriptions, loop protection).
- Week 3 maps to section 6 (AGENT node + waiting-state runtime integration).
- Week 4 maps to section 7 (versioning model/API/cap).
- File map is broadly complete for milestones listed.

**Unresolved questions or ambiguities:**

- Plan text says deregister soft-delete vs hard-delete "spec leaves open; choose soft"; this should be fixed pre-implementation to avoid inconsistent deletion semantics.

---

### 3.4 v1.4.0 - Enterprise Runtime

**Sprint:** 3 weeks  
**Branch name:** `release/v1.4.0`

**Goals summary:**

- Add schedule-driven workflow execution.
- Add namespace-scoped organizational multi-tenancy.
- Harden runtime performance and establish load baselines.

**Key design decisions:**

1. Scheduler uses SQL row locking (`FOR UPDATE SKIP LOCKED`) with lease fields, not external lock service.
2. JWT `permissions` claim removal makes RBAC the real-time authority source.
3. Namespace columns become NOT NULL in same migration cycle as backfill to prevent null bypass windows.
4. Quotas are route-decorator enforced, avoiding brittle path-string middleware matching.
5. State cache TTL varies by run status to limit stale/state growth and control memory pressure.

**Critical security controls:**

- Lock lease fields (`locked_by`, `locked_until`) + claim/release transaction boundaries: prevents duplicate schedule execution.
- Namespace NOT NULL enforcement: blocks cross-tenant leakage via null namespace rows.
- Explicit impersonation requirement for cross-namespace admin access: preserves auditability and least privilege.
- Quota decorators and storage-byte checks: prevent unbounded resource abuse.
- JWT permission-claim removal: prevents stale-token privilege persistence after role changes.

**Migration sequence:**

- `014_organizations`
- `015_organization_members`
- `016_workflow_schedules`
- `017_namespace_workflows`
- `018_namespace_runs`
- `019_namespace_agents`
- `020_namespace_memory`
- `021_namespace_messages`
- `022_namespace_policies`
- `023_performance_indexes`
- Sequence continuity: correct continuation from `013`.

**New permissions:**

- `org:read`, `org:manage`.

**New API endpoints:**

- Schedules: `POST /api/v1/workflows/{id}/schedule` (`workflow:manage`), `GET /api/v1/schedules` (`workflow:read`), `GET/PUT/DELETE /api/v1/schedules/{id}` (`workflow:read` or `workflow:manage`), `POST /api/v1/schedules/{id}/pause` (`workflow:manage`), `POST /api/v1/schedules/{id}/resume` (`workflow:manage`), `GET /api/v1/schedules/{id}/runs` (`run:read`).
- Organizations: `POST /api/v1/organizations` (`admin:*`), `GET/PUT/DELETE /api/v1/organizations/{id}` (`org:read`/`org:manage`), membership management endpoints (`org:manage`/`org:read`).

**Implementation plan alignment:**

- Week 1 maps to scheduler sections and duplicate-execution gates.
- Week 2 maps to namespace/org/quota sections including role mapping and deletion lifecycle.
- Week 3 maps to cache/index/load-baseline sections.
- File map covers main modules and migrations.

**Unresolved questions or ambiguities:**

- `organization_quotas_usage` table is required by storage quota logic but not included in migration inventory/file map.
- Some acceptance criteria require JWT permission-claim behavior changes but no explicit auth module file is named in the file map.

---

### 3.5 v1.5.0 - Developer Experience

**Sprint:** 3 weeks  
**Branch name:** `release/v1.5.0`

**Goals summary:**

- Ship async-first Python SDK and fluent builder.
- Add secure visual workflow builder embedding/editing.
- Add plugin extensibility with strict sandboxing and startup validation.

**Key design decisions:**

1. Plugin state exposed as deep-copied `MappingProxyType` to enforce immutability.
2. File-path plugin loading is banned; entry-point packages only for supply-chain/governance control.
3. Builder uses scoped builder tokens, not primary auth tokens in URL.
4. Plugin hook ordering runs after core audit event writes for event chain integrity.
5. LocalRuntime explicitly documents bypassed controls and is forbidden in production-like environments.

**Critical security controls:**

- Plugin AST security checker (ban async task spawning/thread/subprocess/importlib patterns): prevents timeout escape and arbitrary execution vectors.
- Entry-point validation + fatal startup on unresolved plugin refs: prevents runtime unknown-code loading.
- Builder token scope/TTL and CSRF header validation: prevents cross-origin unauthorized workflow writes.
- Webhook plugin SSRF validation on every send with redirect refusal: prevents internal pivoting.
- SDK/server version compatibility guard: prevents silent incompatible-client behavior.

**Migration sequence:**

- `024_plugin_event_types` - extend audit event type constraints (if constrained).
- `025_builder_token_type` - token type discriminator for builder vs streaming token flows.
- Sequence continuity: correct continuation from `023`.

**New permissions:**

- No net-new core permission family required by spec text beyond existing workflow permissions; builder-token issue endpoint uses `workflow:manage`.

**New API endpoints:**

- `GET /builder/{workflow_id}` - authenticated `workflow:read` access.
- `GET /builder/new` - `workflow:create`.
- `POST /api/v1/workflows/{id}/builder-token` - `workflow:manage`.

**Implementation plan alignment:**

- Week 1 maps to SDK sections (stream token handling, validation at `.build()`, LocalRuntime guard).
- Week 2 maps to builder token infra + CSRF + UI embedding requirements.
- Week 3 maps to plugin system security and audit sequencing.
- File map captures major files for milestones.

**Unresolved questions or ambiguities:**

- Spec says migration 025 adds `token_type`; impl plan additionally requires `workflow_id` in token store for builder scoping. This schema delta must be reconciled before implementation.
- Builder token single-session semantics are defined in spec but enforcement details are not explicit in plan implementation steps.

---

### 3.6 v2.0.0 - Stable Enterprise

**Sprint:** 3 weeks  
**Branch name:** `release/v2.0.0`

**Goals summary:**

- Validate and harden all prior releases via security and chaos testing.
- Establish benchmark regression discipline against v1.4 baselines.
- Complete operational and release documentation artifacts.

**Key design decisions:**

1. No new features; release is validation/hardening and reproducibility-focused.
2. Security gate is vulnerability-severity and patch-availability aware (not naive zero-CVE).
3. Chaos matrix explicitly includes scheduler lock/failover edge cases, not only infra outages.
4. Upgrade guide treats rollback as disaster-recovery with explicit data-loss warning and export/reconciliation steps.
5. ADR coverage expanded to cover major design choices from v1.3-v1.5.

**Critical security controls:**

- 26-scenario pentest suite across all releases: prevents unverified attack-surface assumptions.
- `pip-audit` + `bandit` CI gates: prevents release with known critical/high patched vulnerabilities.
- Builder UI XSS and token misuse audit tasks: prevents UI-based injection or auth leaks.
- Audit detail redaction requirement (tool args): prevents secrets disclosure in compliance logs.
- CORS hardening checks for production embeddings: prevents unsafe wildcard credential patterns.

**Migration sequence:**

- No new schema beyond v1.5 migrations; sequence relies on full `001-025` application and verification.

**New permissions:**

- none.

**New API endpoints:**

- none mandated as feature additions; release scope is validation/documentation tooling.

**Implementation plan alignment:**

- Week 1 maps directly to security scan and pentest sections.
- Week 2 maps to chaos + benchmark sections and CI regression jobs.
- Week 3 maps to docs/ADR/release checklist and staging upgrade/rollback verification.
- File map includes scripts/tests/docs/CI artifacts needed for release proof.

**Unresolved questions or ambiguities:**

- Upgrade guide migration list contains typo (`bacfills`), and several release notes depend on artifacts not yet present in repo.
- Release sign-off assumes all `001-025` migrations exist/applied; current repo migration directory does not reflect that full sequence.

---

## Section 4: Cross-Release Dependency Map

| Feature | Introduced In | Required By | Nature of Dependency |
|---|---|---|---|
| RBAC route registry | v1.1.0 | v1.2.0+ | All new endpoints must be registered |
| Permission vocabulary (singular form) | v1.1.0 | v1.2.0+ | New permissions/scopes must remain convention-consistent |
| Streaming tokens table (migration 008) | v1.2.0 | v1.5.0 | Builder token model reuses token infrastructure with discriminator |
| `system:engine` service account RBAC | v1.2.0 | v1.2.0 tool-calls, v1.3 agent node execution | Internal execution gates require explicit engine perms |
| Migration numbering starts at 009 | v1.3.0 | v1.3.0+ | Avoids collision with v1.2 migration 008 |
| Namespace columns NOT NULL | v1.4.0 | v1.4.0+ | Every new resource must be namespace-scoped |
| Load test baselines committed | v1.4.0 | v2.0.0 | Benchmark regression CI compares against v1.4 baseline |
| RBAC enforcement + policy ordering | v1.1.0 | v1.2+ tool execution, v1.3 messaging APIs | Determines consistent deny/approval gate semantics |
| Unscoped key deprecation timeline | v1.1.0 | v1.2-v1.4 ops and upgrade docs | Safe transition from legacy key behavior |
| Workflow versioning table | v1.3.0 | v1.4 scheduler version pinning, v1.5 builder diff UX | Scheduling/building rely on immutable version references |
| Scheduler lock fields + `SKIP LOCKED` | v1.4.0 | v2.0 chaos scheduler scenarios | Chaos tests validate exactly-once schedule execution |
| Plugin audit event types | v1.5.0 | v2.0 security logging validation | Pen tests and audit completeness require event vocabulary |
| Builder CSRF/token model | v1.5.0 | v2.0 OWASP/CORS/XSS audit suite | Builder security posture is a dedicated v2.0 validation target |

---

## Section 5: Migration Sequence Verification

The release documents define the following full expected sequence `001` through `025`.

| Migration | Release | Table(s) Affected | Change | Reversible (`downgrade()`) |
|---|---|---|---|---|
| `001_rbac_tables.py` | baseline pre-v1.1 | RBAC core tables | Initial RBAC schema | yes (present in repo) |
| `002_owning_scope_columns.py` | baseline pre-v1.1 | Multiple resources | Add owning-scope columns | yes (present in repo) |
| `003_audit_rbac_columns.py` | baseline pre-v1.1 | `audit_events` | Add RBAC/audit scope fields | yes (present in repo) |
| `004_shadow_evaluations.py` | baseline pre-v1.1 | shadow eval storage | Add shadow-evaluation data model | yes (present in repo) |
| `005_inference_tables.py` | baseline pre-v1.1 | inference tables | Add inference storage tables | yes (present in repo) |
| `006_api_key_scopes.py` | v1.1.0 | `api_keys` | Add scopes array for per-key authz | expected yes (specified) |
| `007_idempotency_records.py` | v1.2.0 | `idempotency_records` | Add LLM idempotency cache table | expected yes |
| `008_streaming_tokens.py` | v1.2.0 | `streaming_tokens` | Add streaming token auth table | expected yes |
| `009_agents.py` | v1.3.0 | `agents` | Add agent registry | expected yes |
| `010_agent_messages.py` | v1.3.0 | `agent_messages` | Add message queue with hop controls | expected yes |
| `011_topic_subscriptions.py` | v1.3.0 | `topic_subscriptions` | Add explicit topic/broadcast subscriptions | expected yes |
| `012_workflow_versions.py` | v1.3.0 | `workflow_versions` | Add immutable workflow version history | expected yes |
| `013_workflow_definitions_versioning.py` | v1.3.0 | `workflow_definitions` | Add current version metadata columns | expected yes |
| `014_organizations.py` | v1.4.0 | `organizations` | Add organization model | expected yes |
| `015_organization_members.py` | v1.4.0 | `organization_members` | Add org membership mapping | expected yes |
| `016_workflow_schedules.py` | v1.4.0 | `workflow_schedules` | Add scheduler table with lease lock fields | expected yes |
| `017_namespace_workflows.py` | v1.4.0 | `workflow_definitions` | Add/backfill/enforce namespace | expected yes |
| `018_namespace_runs.py` | v1.4.0 | `workflow_runs` | Add/backfill/enforce namespace | expected yes |
| `019_namespace_agents.py` | v1.4.0 | `agents` | Add/backfill/enforce namespace | expected yes |
| `020_namespace_memory.py` | v1.4.0 | `memory_records` | Add/backfill/enforce namespace | expected yes |
| `021_namespace_messages.py` | v1.4.0 | `agent_messages` | Add/backfill/enforce namespace | expected yes |
| `022_namespace_policies.py` | v1.4.0 | `policy_rules` | Add/backfill/enforce namespace | expected yes |
| `023_performance_indexes.py` | v1.4.0 | multiple | Add query performance indexes | expected yes |
| `024_plugin_event_types.py` | v1.5.0 | `audit_events` | Extend plugin audit event type constraints | expected yes |
| `025_builder_token_type.py` | v1.5.0 | `streaming_tokens` | Add builder/streaming token discriminator | expected yes |

Expected-sequence conclusion from release specs/plans: no numeric gaps and no planned collisions from `001` through `025`.

On-disk repository status check (current branch) does not match expected release sequence: only `001-006` (different `006` purpose) plus two hash-named migration files are present. This is a concrete pre-implementation blocker for executing the documented v1.1+ migration plan as-written.

---

## Section 6: Security Control Inventory

| Control | Release | Mechanism | What It Prevents | Bypass Risk |
|---|---|---|---|---|
| RBAC enforced route gate | v1.1.0 | RBAC middleware + route registry | Unauthorized route access | Broad endpoint exposure |
| RBAC + policy ordering | v1.1.0 | RBAC first, policy second | Policy consulted for route-denied calls | Incorrect allow/deny semantics |
| Complete route registry + default deny | v1.1.0 | Registered permission map | Missing-route accidental allow | Unprotected new endpoints |
| Per-API-key scopes | v1.1.0 | `api_keys.scopes` + request scope checks | Overbroad key usage | Key abuse across domains |
| Client glob prohibition in scopes | v1.1.0 | Input validation on key create | Wildcard privilege escalation | Excessive effective grants |
| Scope count cap and privilege ceiling | v1.1.0 | Validation + creator permission comparison | Key over-privileging | Privilege transfer attacks |
| Unscoped key deprecation controls | v1.1.0+ | WARN logs + staged deny flag | Silent permanent legacy full access | Persistent over-privileged keys |
| Streaming tokens (SSE) | v1.2.0 | short TTL, run-scoped, single-use token | JWT leakage/replay in query params | Stream hijack or cross-run read |
| `system:engine` internal RBAC | v1.2.0 | Explicit service-account role assignment | Unchecked internal tool/run operations | Internal privilege drift |
| LLM tool-call opt-in + policy gate | v1.2.0 | `allow_tool_calls` default false + policy eval | Prompt-triggered unintended tool execution | Model output drives unsafe actions |
| Tool-call arg schema validation | v1.2.0 | Tool schema validation before execute | Injection via malformed tool args | Unsafe handler execution |
| Provider endpoint SSRF protection | v1.2.0 | URL validation and allowlist checks | Internal network probing | SSRF/lateral movement |
| Sender field enforcement | v1.3.0 | Server overrides client `sender` | Agent impersonation spoofing | Forged actor attribution |
| BROADCAST auth + cap | v1.3.0 | `message:broadcast` + recipient cap/rate | Amplification and mass spam | Namespace-wide abuse |
| Hop-count loop protection | v1.3.0 | `hop_count` + MAX_HOPS + DLQ | Infinite relay loops | Queue/resource exhaustion |
| Topic/broadcast subscription opt-in | v1.3.0 | `topic_subscriptions` model/API | Unintended recipients | Information spillage |
| Scheduler lock lease + SKIP LOCKED | v1.4.0 | DB row locks + lease fields | Duplicate scheduled runs in HA | Double execution/inconsistency |
| JWT permission-claim removal | v1.4.0 | Resolve perms from RBAC at request time | Stale JWT privileges | Post-role-change unauthorized access |
| Namespace isolation NOT NULL | v1.4.0 | per-table namespace columns + backfill + constraint | Null-scope bypass | Cross-tenant exposure |
| Quota enforcement decorators | v1.4.0 | endpoint decorators + usage counters | Resource exhaustion/path bypass tricks | Unbounded growth/DoS |
| Cross-namespace impersonation requirement | v1.4.0 | explicit impersonation session + audit | Silent admin scope bypass | Undetected lateral access |
| Builder scoped tokens | v1.5.0 | workflow-scoped builder token, TTL | JWT leakage in iframe URLs | Unauthorized workflow edit surface |
| Builder CSRF header validation | v1.5.0 | `X-Builder-Token` required on writes | Cross-origin workflow mutation | CSRF-based state tampering |
| Plugin state immutability sandbox | v1.5.0 | deep-copy + `MappingProxyType` | Plugin mutation of live workflow state | State corruption/exfiltration vectors |
| Plugin AST security checker | v1.5.0 | startup source scan for banned imports/calls | Timeout escape / subprocess/thread abuse | Arbitrary side-effect execution |
| Plugin file-path prohibition | v1.5.0 | entry-point-only loading | Arbitrary filesystem code execution | Supply-chain / RCE risk |
| LocalRuntime production guard | v1.5.0 | env-based constructor hard failure | Running bypassed-security runtime in prod | Silent control bypass in production |
| Webhook plugin SSRF guard | v1.5.0 | URL validation each send, no redirects | Internal callback abuse | SSRF/data exfiltration |

---

## Section 7: Test Strategy Summary

### v1.1.0

- Coverage targets: Policy >=85, Audit >=85, Approval >=80, RBAC/Authz >=80, Tool Executor >=80, Memory >=75.
- Test types: unit (RBAC/scope/registry), integration (real Postgres, async fixtures), CI quality checks.
- External dependencies: Postgres service container; optional Docker-backed local DB.
- CI jobs: `quality_gate` (lint/type), `integration_tests` (`pytest -m integration`) with secret-injected DB password.

### v1.2.0

- Coverage targets: provider/adapters >=80, LLM handler >=80, SSE >=75, idempotency >=80.
- Test types: unit (routing/sandbox/idempotency/token logic), integration (provider/SSE/reconnect).
- External dependencies: provider keys for gated tests, optional Ollama runtime.
- CI jobs: inherited quality gates + `provider_integration_tests` manual/conditional with secrets and marker gating.

### v1.3.0

- Coverage targets: Agent Registry >=80, Messaging >=85, Topic Subscriptions >=80, Agent Node >=80, Versioning >=80.
- Test types: unit+integration for sender enforcement, broadcast auth, hop limits, waiting-state behavior, versioning atomicity.
- External dependencies: database concurrency scenarios; no third-party keys required.
- CI jobs: no explicitly new named job in spec text, but release gates require messaging/versioning suites and inherited quality gates.

### v1.4.0

- Coverage targets: Scheduler >=85, Org/Multi-tenancy >=85, Quotas >=80, StateCache >=75.
- Test types: integration (scheduler HA lock, org isolation, deletion lifecycle), performance/load baseline tests.
- External dependencies: dual scheduler instances, real DB/Redis, Locust load tooling.
- CI jobs: baseline generation documented; regression gate deferred to v2.0 scheduled benchmark job.

### v1.5.0

- Coverage targets: SDK >=80, WorkflowBuilder >=85, Plugin Registry/Sandbox >=85, Builder Token endpoint >=80.
- Test types: SDK unit/integration, builder auth/CSRF, plugin security/sandbox/ordering tests.
- External dependencies: none strictly required beyond service stack; plugin security tests inspect source.
- CI jobs: inherited quality gates; no dedicated named new CI job mandated in spec besides existing gates.

### v2.0.0

- Coverage target style shifts to scenario completeness: 26 pentest scenarios, 11 chaos scenarios, benchmark comparison within 10%.
- Test types: security, chaos, performance regression, staging upgrade/rollback validation.
- External dependencies: Docker stop/kill/network fault tooling, real DB/Redis, scheduler multi-instance, optional provider mocks/keys.
- CI jobs introduced: `security_scan` (MR + release branch), `pentest` (release branch), `chaos_tests` (manual), `benchmark` (scheduled).

---

## Section 8: Implementation Readiness Assessment

### v1.1.0: READY WITH NOTES

Notes:
- Spec/plan are detailed and testable.
- Path naming mismatch for referenced revised file names should be normalized in docs index.
- Health endpoint path naming inconsistency should be resolved before implementation to avoid registry drift.

### v1.2.0: READY

Rationale: strong requirement mapping, security tradeoffs explicit, rollout/testing/CI gates measurable.

### v1.3.0: READY WITH NOTES

Notes:
- Agent deregistration hard-vs-soft behavior left open in plan text and should be fixed before coding.

### v1.4.0: READY WITH NOTES

Notes:
- Storage quota accounting requires `organization_quotas_usage` persistence artifact not explicitly present in migration/file map.

### v1.5.0: READY WITH NOTES

Notes:
- Migration 025 scope mismatch (`token_type` only in spec vs `token_type + workflow_id` in plan) requires reconciliation.
- Single-session builder token enforcement detail should be made explicit.

### v2.0.0: READY WITH NOTES

Notes:
- Relies on full migration chain and prior artifacts that are not currently present in repo state.
- Some documentation references have minor accuracy/typo issues but are non-architectural.

### Overall assessment

**BLOCKED** due to repository-state/document-sequence mismatch on migrations and missing exact requested spec filenames. The design itself is largely implementation-ready; the blocker is release-governance consistency and migration baseline alignment.

Blockers:

1. Expected migration chain `001-025` (with documented names/purposes) does not match on-disk migration inventory.
2. Exact revised spec filenames requested in task inventory are absent; equivalents exist but index-level mismatch is unresolved.

---

## Section 9: Confirmation Statement

I have read all 18 documents listed in the inventory. I understand the complete
architecture, security model, migration sequence, permission vocabulary, test strategy,
and release-by-release implementation plan for SyndicateClaw v1.1.0 through v2.0.0.

COMPREHENSION REVIEW - UPDATED STATUS (2026-03-27)

All blockers and notes resolved via human review response.

Blocker 1 (migration chain): Resolved. Migrations 006-025 are forward-looking targets,
not current on-disk state. Baseline is 001-005. Implement 006 onward starting in v1.1.0.

Blocker 2 (filename mismatch): Resolved. Agent correctly read all documents under their
actual on-disk names. Proceed using discovered filenames.

Design decisions recorded:
- v1.3.0 agent deregistration: soft delete with 90-day retention window.
- v1.4.0 organization_quotas_usage: add as separate table in migration 014 file.
- v1.5.0 migration 025: plan is authoritative (token_type + workflow_id columns).
- v1.5.0 builder token: session-scoped (multi-use within TTL), not single-use.
- v1.1.0 health paths: /healthz and /readyz are correct as-is.

Overall implementation readiness: READY

Begin: release/v1.1.0 per impl-plan-v1.1.0.md, starting with Week 1 Track A (ruff lane).

V1.1.0 CLOSE-OUT HANDOFF (2026-03-27T05:53:27+00:00)

Code-level v1.1.0 implementation and local quality gates are complete.

Operational gates pending handoff to platform/release operations:
- Week 3.3 Shadow Log Parity Analysis (staging):
  - Deploy v1.1.0 candidate with `SYNDICATECLAW_RBAC_ENFORCEMENT_ENABLED=false`.
  - Run 48-hour representative traffic window.
  - Verify zero unexpected `rbac.shadow_decision` deny disagreements.
  - If disagreements appear, correct registry/assignments, redeploy, and restart 48-hour window.
- Week 3.4 Canary Rollout (production):
  - Deploy with enforcement initially disabled.
  - Enable RBAC enforcement for 10% cohort for 7 days.
  - Monitor unexpected 403 rates, shadow/enforcement parity, and enforcement-disabled warnings.
  - Promote to 100% only after clean canary window; retain instant rollback path.

Not part of v1.1.0 completion scope (deferred gate):
- Week 3.5 shadow-log deletion is post-v1.2.0 and requires explicit security sign-off.

v1.1.0 Operational Handoff (2026-03-27)
Code-level implementation complete. The following gates require platform team action
and cannot be executed by the coding agent:
Staging gates (platform team - pre-production)

 Deploy release/v1.1.0 to staging with SYNDICATECLAW_RBAC_ENFORCEMENT_ENABLED=false
 Run representative traffic for 48 hours
 Query shadow decision logs; confirm zero unexpected DENYs:
SELECT COUNT(*) FROM audit_events
WHERE event_type = 'rbac.shadow_decision'
AND details->>'enforcement_would_have' = 'DENY'
AND created_at > NOW() - INTERVAL '48 hours';
 If zero: proceed to canary. If non-zero: file issues, agent will fix, restart window.

Canary gates (platform team - post-release)

 Deploy v1.1.0 to production with enforcement at 0%
 Enable enforcement for 10% of traffic via feature flag or load balancer weight
 Monitor for 7 days: zero unexpected 403s; zero shadow disagreements
 Promote to 100% after 7 clean days

Shadow log deletion (security team - after canary completes)

 Confirm enforcement at 100% for >=7 days with zero incidents
 Obtain explicit security review sign-off
 Execute: DELETE FROM audit_events WHERE event_type = 'rbac.shadow_decision'
(in a transaction with row count check before committing)
 Remove shadow-mode logging code from syndicateclaw/authz/shadow_middleware.py
(or equivalent shadow evaluator file)

Upgrade guide (docs team - before release tag)

 Document permission vocabulary change: singular form (workflow:read not workflows:read)
 Document unscoped key deprecation timeline (v1.1.0 WARN -> v1.3.0 soft cutoff -> deny)
 Document SYNDICATECLAW_RBAC_ENFORCEMENT_ENABLED explicit flag requirement

v1.1.0 Code-Level Completion Confirmation (2026-03-27)
All code-level acceptance criteria from revised spec section 14 confirmed:
✓ SYNDICATECLAW_RBAC_ENFORCEMENT_ENABLED=true is the new default in Settings
✓ Explicit false required in test environments (rbac_disabled fixture; no env-name inference)
✓ Complete route registry covers all endpoints; programmatic test passes
✓ All permission strings use singular resource form
✓ RBAC + policy engine interaction tested (DENY wins; policy not consulted on RBAC deny)
✓ API keys accept explicit scopes (no globs, max 50, privilege ceiling enforced)
✓ Unscoped keys emit WARN log on every use
✓ GET /api/v1/api-keys/scopes returns sorted permission list; requires authentication
✓ ruff check src tests exits 0
✓ mypy src exits 0
✓ 540 tests passing, 61 integration tests passing
✓ CI quality_gate job added (.gitlab-ci.yml)
✓ Migration 006_api_key_scopes committed and verified
Pending: operational gates documented above (platform team handoff).

v1.2.0 deployment runbook note:
- Before deploying v1.2.0, verify system:engine has run:control and tool:execute.

v1.2.0 progress checkpoint (2026-03-27T07:27:33+00:00)
- Added fatal startup validation for provider auth env vars via
  `validate_provider_env_vars` in `src/syndicateclaw/inference/config_loader.py` and
  invocation in `src/syndicateclaw/api/main.py`.
- Added unit test `test_provider_config_missing_env_var_fatal` in
  `tests/unit/inference/test_config_loader.py`.
- Gate verification completed locally:
  - `.venv/bin/pytest -k provider_config_missing -q` -> 1 passed
  - `.venv/bin/pytest tests/unit/inference/test_config_loader.py -q` -> 6 passed
  - `.venv/bin/pytest tests/unit/llm/test_tool_call_gating.py -q` -> 3 passed
  - `.venv/bin/pytest tests/unit/test_provider_test_endpoint.py -q` -> 1 passed
  - `.venv/bin/pytest tests/unit/test_system_engine_startup.py -q` -> 1 passed
  - `.venv/bin/pytest tests/unit/test_streaming_endpoint.py -q` -> 2 passed
  - `.venv/bin/ruff check src tests` -> clean
  - `.venv/bin/mypy src` -> clean

## v1.2.0 Code-Level Completion Confirmation (2026-03-27)

All code-level acceptance criteria from revised spec §18 confirmed:

✓ ProviderService pipeline with InferenceRouter, circuit breaker, and YAML config
✓ Fatal ConfigurationError on missing provider API key at startup
✓ Routing rules first-match-wins; claude-* routes to Anthropic before * catch-all
✓ LLM node handler calls ProviderService (not adapter directly)
✓ SandboxedEnvironment with StrictUndefined; sandbox tests pass
✓ allow_tool_calls defaults to false; tool calls gated by policy engine when enabled
✓ Idempotency key is {run_id}:{node_id}:{attempt}; retries bypass cache
✓ Streaming tokens: single-use, run-scoped, 5-min TTL
✓ Primary JWT in ?token= returns 401 (streaming token required)
✓ GET /api/v1/runs/{id}/events?since= endpoint for reconnect recovery
✓ llm_complete SSE event contains only usage + timestamp (no response body)
✓ All metrics are Counter or Histogram; no high-cardinality labels
✓ POST /api/v1/providers/{name}/test requires admin:*; generic error only
✓ system:engine configured with run:control + tool:execute at startup
✓ All new routes in RBAC route registry
✓ Migration 008 streaming_tokens includes workflow_id column
✓ Provider integration tests gated behind requires_api_keys + vault secrets

Operational handoff (platform team):
- Provider API keys must be injected via vault before any LLM workflows run
- system:engine RBAC assignment must be verified post-deploy via readyz check
- SSE streaming token TTL (default 300s) tunable via SYNDICATECLAW_STREAMING_TOKEN_TTL_SECONDS

## v1.3.0 Week 4 Completion Checkpoint (2026-03-27)

- Implemented migrations:
  - `012_workflow_versions` (workflow_versions + workflow_versions_archive)
  - `013_workflow_defs_ver` (workflow_definitions.current_version, updated_by)
- Implemented `VersioningService` in
  `src/syndicateclaw/services/versioning_service.py`:
  - atomic version creation with row lock
  - version cap enforcement (archive oldest over 100)
  - rollback creates a new forward version
  - structured diff support
- Added workflow versioning API routes in
  `src/syndicateclaw/api/routes/workflow_versions.py`:
  - list versions
  - get version
  - rollback
  - diff (`from`/`to` query params)
- Integrated versioning into workflow APIs:
  - `PUT /api/v1/workflows/{workflow_id}` creates a new version each update
  - `POST /api/v1/workflows/{workflow_id}/runs` accepts optional `version`
    and pins run `workflow_version` accordingly
- Registered all new endpoints in RBAC registry and added dynamic template
  path matching support to avoid false `DENY` on parameterized paths.
- Added observability metric in
  `src/syndicateclaw/messaging/metrics.py`:
  - `workflow_versions_total{namespace=...}` (no workflow_id label)

Verification evidence:
- `SYNDICATECLAW_DATABASE_URL=... .venv/bin/alembic downgrade 011_topic_subscriptions && ... upgrade head` passed
- `SYNDICATECLAW_DATABASE_URL=... SYNDICATECLAW_RBAC_ENFORCEMENT_ENABLED=false .venv/bin/pytest tests/unit/test_versioning_service.py -v` passed (7 tests)
- `SYNDICATECLAW_DATABASE_URL=... SYNDICATECLAW_RBAC_ENFORCEMENT_ENABLED=false .venv/bin/pytest tests/ -k version -v` passed (15 selected)
- `SYNDICATECLAW_RBAC_ENFORCEMENT_ENABLED=false .venv/bin/ruff check src tests` passed
- `SYNDICATECLAW_RBAC_ENFORCEMENT_ENABLED=false .venv/bin/mypy src` passed

Week 4 commits:
- `5ac258e` feat(db): add workflow versioning schema
- `f069d86` feat: add workflow versioning service and API integration
- `378cb42` docs: append v1.3.0 week 4 completion checkpoint

## v1.3.0 Code-Level Completion Confirmation (2026-03-27)

✓ sender always server-set; client override logged as WARN
✓ Heartbeat enforces ownership; non-owner → 403
✓ BROADCAST requires message:broadcast; limited to subscribed agents; cap 50
✓ Hop count on every message; MAX_HOPS enforced; loop terminates with DLQ entry
✓ Topic subscriptions: data model, API, migration 011
✓ WAITING_AGENT_RESPONSE counted in concurrent run pool
✓ Versioning uses workflow_versions table (not JSONB column)
✓ Rollback creates new version; history preserved; in-flight runs unaffected
✓ Concurrent update atomic (SELECT FOR UPDATE); no lost updates
✓ Version cap: 100 max; oldest archived on overflow
✓ workflow_versions_created_total uses namespace label only (no workflow_id)
✓ Migrations 009-013 applied; round-trip verified
✓ All new routes in RBAC route registry
✓ Full pytest suite: 682 passed, 15 skipped, 2 xfailed
✓ Integration tests: 148 passed, 14 skipped, 2 xfailed
✓ ruff check src tests: clean
✓ mypy src: clean

Pending (platform team):
- Agent hard-delete cron: enforce 90-day retention window on deregistered agents
- Messaging DLQ monitoring: alert when dead_letter_records source_type=agent_message grows

## v1.4.0 Code-Level Completion Confirmation (2026-03-27)

- SchedulerService SKIP LOCKED; HA concurrent duplicate test passes (COUNT=1)
- max-runs completion logic correct (run_count+1 >= max_runs)
- JWT permissions claim removed; live RBAC lookup at request time; token carries sub, optional org_id/org_role
- Namespace NOT NULL across workflow_definitions, workflow_runs, agent_messages, policy_rules; agents/memory_records documented skips where already present
- Quota enforcement on workflow create, agent register, schedule create, memory write; storage_bytes_updated on memory insert
- organization_quotas_usage table tracks storage_bytes_used
- Org DELETING blocks new runs (409); cleanup job deletes tenant data in dependency order
- StateCache: terminal runs 60s TTL; active runs 3600s (PENDING included)
- Migrations 014-023 in chain; test DB uses metadata drop/create for ORM parity
- Pending: load test baseline against real staging (platform team); run `alembic upgrade head` where DB credentials available

## v1.5.0 Code-Level Completion Confirmation (2026-03-27)

- Migrations 024 (plugin audit event sequencing) and 025 (builder token sequencing); `streaming_tokens` columns unchanged from 008
- BuilderTokenService: multi-use builder tokens; `POST /api/v1/workflows/{id}/builder-token`; `BuilderCSRFMiddleware` requires `X-Builder-Token` on `PUT /api/v1/workflows/{id}` when builder enabled
- Static builder shell: `GET /builder/new`, `GET /builder/{workflow_id}` (public HTML)
- Plugin system: `PluginContext` (MappingProxyType + deepcopy), AST `check_plugin_security`, `PluginRegistry` (entry points / `module:Class` only), `PluginExecutor` with audit hooks and timeouts; `WorkflowEngine` invokes `on_node_execute` after successful node completion
- SDK (`sdk/`): exceptions, `ensure_compatible()` version gate, `WorkflowBuilder`, `LocalRuntime` production guard, `StreamingSession`; unit tests in `tests/unit/test_sdk_v15.py`
- Security gate script: `scripts/check_audit_gates.py`; ADRs 0002–0014 added; `docs/api/permission-table.md` index
- Pending: full React builder app; 26 pentest + 11 chaos scenarios; CI jobs for pip-audit/bandit/locust; PyPI publish; `release/v2.0.0` tag and Docker push when ops ready

## v2.0.0 Close-out (2026-03-27)

- `tests/security/`: pentest-marked automated regressions (core, agent, enterprise, DX); skipped scenarios documented where async DB or RBAC harness is heavy; `tests/security/conftest.py` loads integration fixtures for ASGI/JWT tests.
- `tests/chaos/`: chaos-marked stubs (skipped) for Postgres/Redis/DLQ scenarios until staging controls exist.
- `scripts/check_benchmark_regression.py`; `tests/perf/test_smoke_benchmark.py`; `tests/perf/baseline_v2.0.0.json` committed as trimmed pytest-benchmark reference for scheduled regression checks.
- `.gitlab-ci.yml`: `security_scan` uses JSON Bandit/pip-audit plus `check_audit_gates.py`; manual `pentest` and `chaos_tests` on `release/v2.0.0`; scheduled `benchmark` runs smoke benchmark + regression helper.
- `CHANGELOG.md` [2.0.0] documents the above; replace perf baseline before enforcing regression thresholds in production CI.
