# Syndicate Claw Architecture

## System Overview

Syndicate Claw is the governed execution plane for AI Syndicate. It executes
workflow graphs, policy-gated tools, inference calls, runtime checkpoints, and
replay. It also emits the runtime evidence needed to reconstruct what happened.

When Gate receives a sensitive request, it can create a Claw approval task. The
request blocks until an approver acts; approval resumes the same Gate request
with the same correlation ID, and rejection terminates it cleanly with no
provider call.

In standalone deployments, Claw may use its own local policy, approval, and
audit services as the authority source. In enterprise deployments that install
Claw, ControlPlane Enterprise is the only authority source. Claw verifies
ControlPlane-issued authority before execution and emits correlated evidence
back to ControlPlane. ControlPlane does not execute Claw workflows or dispatch
Claw tools. Enterprise deployments may omit Claw and let Code execute locally;
that fallback is outside Claw and requires evidence reconciliation into
ControlPlane.

### Design Principles

| Principle | Over | Rationale |
|---|---|---|
| **Authority separation** | Convenience | ControlPlane authorizes; Claw executes |
| **Auditability** | Autonomy | Every action produces an audit event with actor attribution |
| **Explicitness** | Convenience | Tools must be registered by hand; no auto-discovery or plugin loading |
| **Replayability** | Speed | Checkpoints and append-only logs allow full run reconstruction |
| **Isolation** | Integration | Namespace-scoped memory, actor-scoped policies, owner-enforced workflows |

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                     API Gateway (FastAPI)                     │
│  ┌─────────┐ ┌──────────┐ ┌────────┐ ┌────────┐ ┌────────┐│
│  │Workflows│ │ Approvals│ │Memory  │ │ Policy │ │ Audit  ││
│  └────┬────┘ └────┬─────┘ └───┬────┘ └───┬────┘ └───┬────┘│
└───────┼───────────┼────────────┼──────────┼──────────┼──────┘
        │           │            │          │          │
┌───────▼───────────▼────────────▼──────────▼──────────▼──────┐
│                   Service Layer                              │
│  ┌──────────────┐ ┌─────────┐ ┌────────┐ ┌───────────────┐ │
│  │  Workflow     │ │Approval │ │Memory  │ │  Policy       │ │
│  │  Engine       │ │Service  │ │Service │ │  Engine       │ │
│  └──────┬───────┘ └─────────┘ └────────┘ └───────────────┘ │
│         │                                                    │
│  ┌──────▼───────┐ ┌─────────────────────┐                  │
│  │Tool Registry │ │ Tool Executor       │                  │
│  │              │ │ (policy-gated)      │                  │
│  └──────────────┘ └─────────────────────┘                  │
└──────────────────────────┬───────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────┐
│                    Persistence Layer                          │
│  ┌──────────┐  ┌───────────┐  ┌─────────────┐              │
│  │PostgreSQL│  │   Redis    │  │ Audit Log   │              │
│  │(state)   │  │  (cache)   │  │(append-only)│              │
│  └──────────┘  └───────────┘  └─────────────┘              │
└──────────────────────────────────────────────────────────────┘
```

---

## Deployment Modes

| Mode | Authority Source | Execution Source | Evidence Destination |
|---|---|---|---|
| Standalone | Claw local policy, approval, and audit services | Claw | Claw local audit store |
| Enterprise with Claw | ControlPlane Enterprise | Claw | ControlPlane Enterprise ledger, with local Claw audit retained for replay |
| Enterprise without Claw | ControlPlane Enterprise | Code local execution fallback | ControlPlane Enterprise ledger, with local Code evidence reconciled for replay |

Enterprise mode with Claw requires a fail-closed authority adapter. If ControlPlane
permit validation, approval binding, revocation checks, or evidence writes fail,
Claw must not continue the governed execution step.

---

## Component Descriptions

### API Gateway

The API layer is a FastAPI application (`syndicateclaw.api.main`) exposing six route groups under `/api/v1/`:

| Route Group | Prefix | Purpose |
|---|---|---|
| Workflows | `/api/v1/workflows` | CRUD for workflow definitions and run lifecycle |
| Approvals | `/api/v1/approvals` | Human-in-the-loop approval gates |
| Memory | `/api/v1/memory` | Namespaced key-value memory with provenance |
| Policies | `/api/v1/policies` | CRUD and evaluation of policy rules |
| Tools | `/api/v1/tools` | Tool listing, detail, and ad-hoc execution |
| Audit | `/api/v1/audit` | Query audit events, traces, and run timelines |

Three system endpoints sit outside the versioned prefix:

- `GET /healthz` — liveness probe returning `{"status": "ok", "version": "0.1.0"}` (process is running)
- `GET /readyz` — readiness probe checking database, Redis, policy engine, decision ledger, and rate limiting availability. Returns 200 with per-check status when healthy, 503 with `{"status": "degraded", ...}` when any dependency is unavailable. Rate limiting reports "degraded (fail-open)" when Redis is down unless `rate_limit_strict=true`, in which case it fails readiness.
- `GET /api/v1/info` — application metadata (title, version, Python version, docs URL)

**Middleware stack** (applied in order):

1. **RequestIDMiddleware** — attaches a ULID-based `X-Request-ID` to every request/response; binds it to structlog context vars for correlated logging.
2. **RateLimitMiddleware** — Redis-backed per-actor sliding-window rate limiter. Enforces sustained (`rate_limit_requests` per `rate_limit_window_seconds`) and burst (`rate_limit_burst` per 1s) limits. Returns HTTP 429 with `Retry-After` and `X-RateLimit-*` headers. Skips health/docs paths. Degrades open if Redis is unavailable.
3. **AuditMiddleware** — logs method, path, status code, duration, and actor for every HTTP request; writes audit events to the audit service.
4. **CORSMiddleware** — conditionally added when `cors_origins` is configured.

**Authentication** is handled via the `get_current_actor` dependency which supports:

- **JWT Bearer tokens** — decoded with PyJWT, supporting RS256 via OIDC JWKS, HS256 (symmetric), and EdDSA/Ed25519 (asymmetric). When an Ed25519 public key is available, EdDSA is tried first, then configured OIDC JWKS validation, then HS256 fallback. Must contain a `sub` claim.
- **API key header** (`X-API-Key`) — looked up against a key-actor mapping
- Falls back to `"anonymous"` only when `SYNDICATECLAW_ENVIRONMENT` is set to `development`/`dev`/`test`/`testing`. Production environments return HTTP 401 if no credentials are provided.

**Ownership scoping**: All endpoints enforce actor ownership. List endpoints: workflow lists return only workflows owned by the actor, run lists return only runs initiated by the actor, approval lists return only approvals assigned to or requested by the actor. GET-by-ID endpoints: `get_workflow` checks `owner == actor`, `get_run`/`pause`/`resume`/`cancel`/`replay` check `initiated_by == actor`, `get_approval` checks actor is in `assigned_to` or is `requested_by`. Memory `update`/`delete`/`lineage` enforce access policy. Non-matching actors receive HTTP 404 (information hiding).

### Workflow Orchestrator

The `WorkflowEngine` (`syndicateclaw.orchestrator.engine`) executes graph-based workflows defined as `WorkflowDefinition` models containing nodes and edges.

**Key characteristics:**

- **Graph traversal**: Starts at the `START` node and walks edges until reaching an `END` node or a terminal status (FAILED, PAUSED, WAITING_APPROVAL, CANCELLED).
- **Safe condition evaluator**: Edge conditions and decision nodes use a custom recursive-descent parser (`_ConditionParser`) instead of `eval()`. Supports comparison operators (`==`, `!=`, `>`, `<`, `>=`, `<=`), boolean logic (`and`, `or`, `not`), list membership (`in`), and state references (`state.field_name`).
- **Retry policies**: Each node can declare a `RetryPolicy` with `max_attempts`, `backoff_seconds`, and `backoff_multiplier` for exponential backoff.
- **Checkpoints**: Workflow state is serialized to JSON and stored as `checkpoint_data` on the run. When a signing key is configured, checkpoints are HMAC-SHA256 signed — the data is wrapped in a `{"data": ..., "checkpoint_hmac": "<hex>"}` envelope. On replay, the HMAC is verified before loading; tampered checkpoints raise `ValueError`. Checkpoint nodes trigger explicit saves; the engine can restore from the last checkpoint for replay.
- **Lifecycle management**: Supports `execute`, `resume`, `replay`, `pause`, and `cancel` operations.

**Node types:** `START`, `END`, `ACTION`, `DECISION`, `APPROVAL`, `CHECKPOINT`

**Built-in handlers** (`syndicateclaw.orchestrator.handlers`):

| Handler | Purpose |
|---|---|
| `start` | Initializes run metadata (`_started_at`, `_run_id`) |
| `end` | Finalizes the run (`_completed_at`) |
| `checkpoint` | Persists current state as a recoverable checkpoint |
| `approval` | Creates an `ApprovalRequest` and raises `WaitForApprovalError` |
| `llm` | Placeholder for LLM integration (annotates state) |
| `decision` | Evaluates a condition expression and routes to `true_node`/`false_node` |

**Run statuses:** `PENDING` → `RUNNING` → `COMPLETED` | `FAILED` | `PAUSED` | `WAITING_APPROVAL` | `CANCELLED`

**State redaction**: All API responses returning `WorkflowRunResponse` pass through `from_orm_redacted()`, which applies schema-based redaction via `syndicateclaw.security.redaction`. Fields matching sensitive patterns (password, secret, token, api_key, credential, private_key, auth, ssn, credit_card, cvv) are replaced with `[REDACTED]`. Internal workflow fields (`_run_id`, `_started_at`, `_completed_at`, `_decision`) are allowlisted. Custom patterns can be added at call sites.

### Tool Framework

The tool system is split into three components:

**ToolRegistry** (`syndicateclaw.tools.registry`):
- Central dictionary of `ToolDefinition` objects (metadata + async handler).
- Explicit registration only — `register(tool, handler)` must be called at startup. No dynamic plugin discovery or auto-loading.
- Supports listing by risk level, unregistration, and membership checks.

**ToolExecutor** (`syndicateclaw.tools.executor`):
- Orchestrates the full tool execution pipeline: lookup → schema validation → **sandbox enforcement** → policy check → **mandatory decision ledger record** → execute with timeout → response sandbox check → output validation → **input snapshot capture** → audit.
- **Fail-closed policy gate**: calls `PolicyEngine.evaluate()` before execution. Returns `DENY` if the policy engine is `None` (no permissive fallback). If the decision is `DENY`, raises `ToolDeniedError`. If `REQUIRE_APPROVAL`, raises `ApprovalRequiredError`.
- **Mandatory decision ledger**: Tool execution cannot complete without a `DecisionRecord` being emitted. If the ledger is unavailable or the write fails, execution is denied.
- **Sandbox enforcement**: `ToolSandboxPolicy` (allowed domains, protocols, payload limits, network/filesystem/subprocess flags) is enforced before and after execution. Violations raise `SandboxViolationError`.
- **Input snapshotting**: Tool responses are captured as `InputSnapshot` records for deterministic replay.
- Timeout enforcement via `asyncio.wait_for()` with per-tool `timeout_seconds`.
- Custom exceptions: `ToolNotFoundError`, `ToolDeniedError`, `ApprovalRequiredError`, `ToolExecutionError`, `ToolTimeoutError`, `SandboxViolationError`.

**Built-in tools** (`syndicateclaw.tools.builtin`):

| Tool | Risk | Description |
|---|---|---|
| `http_request` | MEDIUM | HTTP client with SSRF protection (blocks RFC 1918, loopback, link-local) |
| `memory_write` | LOW | Write a key-value pair to a namespace |
| `memory_read` | LOW | Read a value by namespace and key |

### Memory Service

The `MemoryService` (`syndicateclaw.memory.service`) manages three types of memory:

- **Episodic** — event-specific records tied to workflow executions
- **Semantic** — general knowledge extracted or summarized from events
- **Structured** — schema-conforming records for lookup

**Features:**

- **Provenance tracking**: Every record carries a `MemoryLineage` with `parent_ids`, `workflow_run_id`, `node_execution_id`, `tool_name`, and `derivation_method`. Updates append the current record ID to the parent chain.
- **Confidence scores**: Float between 0.0 and 1.0, validated on write and update.
- **Namespace isolation**: Records are grouped by namespace; searches are scoped to a single namespace.
- **Redis caching**: Read-through cache with configurable TTL. Cache is invalidated on write, update, and delete. Gracefully degrades if Redis is unavailable. **Actor-aware**: records with non-default access policies are never cached; cache hits are checked against `_check_access_policy()` before return.
- **Soft delete**: Records transition through `ACTIVE` → `MARKED_FOR_DELETION` → `DELETED`. Soft-deleted records are excluded from reads and searches.
- **Retention enforcement**: `RetentionEnforcer` runs periodic sweeps to purge expired and soft-deleted records.
- **Write guardrails**: Memory writes are validated against configurable limits: max value size (`memory_max_value_bytes`, default 1MB), max key length (`memory_max_key_length`, default 256), max namespace length (`memory_max_namespace_length`, default 128), and max nesting depth (default 20). Updates to the `value` field are also size-checked. Deeply nested structures are rejected to prevent processing abuse.
- **Namespace schema validation**: An optional `NamespaceSchemaRegistry` enables per-namespace structural validation on write and update. Schemas declare required fields, field type constraints, max field count, and whether extra fields are allowed. Namespace matching supports exact match and prefix-glob (e.g., `"agent:*"`). No-op when no schema is registered for the namespace.
- **Access policy enforcement**: Each record carries a named `access_policy` enforced at read and search time. Supported policies: `default` (any authenticated actor), `owner_only` (record actor only), `system_only` (system-prefixed actors), `restricted` (record actor only). Unknown policy values fail closed (denied). Records the actor cannot access are silently excluded from search results.

### Policy Engine

The `PolicyEngine` (`syndicateclaw.policy.engine`) implements a **fail-closed** authorization model:

- **Default DENY**: If no matching rule is found, the decision is `DENY` with reason "No matching policy rule found".
- **Rule matching**: Rules are loaded by `resource_type`, filtered by `fnmatch` glob pattern against `resource_id`, and sorted by `priority` (descending). First match wins.
- **Condition evaluation**: Each rule can have conditions that check dot-path fields against expected values using operators: `eq`, `neq`, `in`, `not_in`, `gt`, `lt`, `gte`, `lte`, `matches` (regex).
- **Effects**: `ALLOW`, `DENY`, `REQUIRE_APPROVAL`.
- **Decision persistence**: Every evaluation produces a `PolicyDecision` record stored in the database with full condition evaluation results.
- **Audit integration**: All rule CRUD and evaluations emit audit events.
- **RBAC on management**: Policy rule creation, update, and deletion require actors with `admin:`, `policy:`, or `system:` prefix. Unauthorized actors receive HTTP 403. Read, list, and evaluate operations remain open to any authenticated actor.

**RBAC rollout status**: The RBAC data model (principals, roles, assignments, namespace bindings) is deployed. Route-level enforcement is controlled by `SYNDICATECLAW_RBAC_ENFORCEMENT_ENABLED` (default: `true`). When enforcement is disabled (`false`), RBAC still runs in shadow mode and emits disagreement telemetry for rollout validation. See `docs/rbac-design.md` and `docs/rbac-implementation-plan.md` for the full design and rollout plan.

### Approval Service

The `ApprovalService` (`syndicateclaw.approval.service`) provides human-in-the-loop gates:

- **Request lifecycle**: `PENDING` → `APPROVED` | `REJECTED` | `EXPIRED`
- **Assignee enforcement**: Only actors listed in `assigned_to` can approve or reject.
- **Self-approval prevention**: The requester (`requested_by`) cannot approve their own request. Both the service layer and API endpoint enforce this with `PermissionError` / HTTP 403.
- **Authority-resolved approvers**: When configured, an `ApprovalAuthorityResolver` determines eligible approvers based on tool risk level and policy rules, overriding any client-supplied `assigned_to` list. The requester is always excluded. Resolution order: policy-defined approvers → risk-level defaults (by `ToolRiskLevel`) → admin fallback. This prevents the "colluding approver" governance loophole.
- **Expiration**: Requests have an `expires_at` deadline. `expire_stale()` sweeps and auto-expires overdue requests.
- **Notification callbacks**: Optional async callback invoked when a request is created (for Slack, email, etc.).
- **Audit trail**: Every state transition emits an audit event.

### Audit Service

The `AuditService` (`syndicateclaw.audit.service`) maintains an **append-only** event log:

- **Append-only repository**: The `AuditEventRepository` only supports `append` and `query` — no update or delete methods.
- **HMAC-signed events**: When a signing key is configured (derived from the application secret via `syndicateclaw.security.signing`), audit event `details` are signed with HMAC-SHA256. Decision records append `hmac:<signature>` to `side_effects`. Evidence bundles include a `bundle_hmac` field. Verification is constant-time.
- **Event structure**: Each `AuditEvent` carries `event_type`, `actor`, `resource_type`, `resource_id`, `action`, `details` (JSONB with optional `integrity_signature`), and optional `trace_id`/`span_id` for OpenTelemetry correlation.
- **Query capabilities**: Filter by event type, actor, resource, time range; retrieve by trace ID or resource.
- **Database-backed dead letter queue**: `DeadLetterQueue` persists failed events to the `dead_letter_records` PostgreSQL table with error classification (transient/permanent), bounded retries, manual resolution tracking, and actor attribution. Survives process restarts.
- **Event bus**: In-process `EventBus` singleton for pub/sub notification of audit events to subscribers.
- **OpenTelemetry**: `setup_tracing()` configures a global `TracerProvider` with OTLP gRPC export and console export.

### Channel Connectors

The `channels` package defines a `ChannelConnector` protocol for inbound/outbound messaging:

- **WebhookChannel**: Outbound HTTP delivery with SSRF protection, exponential backoff retry (tenacity), and configurable auth headers.
- **ConsoleChannel**: Local development channel that logs messages via structlog.

### Security

**Authentication** (`syndicateclaw.security.auth`, `syndicateclaw.security.api_keys`):
- JWT creation and verification using PyJWT with support for both HS256 (symmetric) and EdDSA/Ed25519 (asymmetric). Configure `jwt_algorithm=EdDSA` to use Ed25519 signing; the same key pair used for evidence signing can serve JWT signing, aligning auth and evidence crypto boundaries.
- Tokens carry `sub` (actor), `permissions`, `iat`, and `exp` claims.
- **DB-backed API key lifecycle** (`ApiKeyService`): keys are SHA-256 hashed before storage (raw key returned exactly once at creation). Supports creation with optional expiration, verification with `last_used_at` tracking, revocation with actor attribution, and listing without exposing hashes. Falls back to the static key mapping if the DB-backed service is not initialized.

**Integrity Signing** (`syndicateclaw.security.signing`):
- **HMAC-SHA256** (symmetric): Signing key derived from the application secret via HKDF-like derivation using a dedicated context prefix, avoiding key reuse with JWT signing. `sign_payload()` / `verify_signature()` for arbitrary dict payloads; `sign_record()` / `verify_record()` for adding/checking `integrity_signature` fields. Constant-time comparison via `hmac.compare_digest()`.
- **Ed25519** (asymmetric): `SigningKeyPair` generates or loads Ed25519 key pairs for non-repudiation. Private key signs, public key verifies. `Ed25519Verifier` provides a verify-only instance from a public key PEM. Key pairs can be persisted as PEM and the private key isolated to a KMS/HSM. **Enforceable gate**: setting `SYNDICATECLAW_REQUIRE_ASYMMETRIC_SIGNING=true` causes the system to refuse startup without a configured Ed25519 private key (`SYNDICATECLAW_ED25519_PRIVATE_KEY_PATH`).

**State Redaction** (`syndicateclaw.security.redaction`):
- Schema-based redaction of sensitive fields in workflow state before API responses.
- Built-in patterns: password, secret, token, api_key, credential, private_key, auth, ssn, credit_card, cvv.
- Supports extra patterns and field-level allowlists.
- Deep-copies state to avoid mutation; handles nested dicts and lists.

**SSRF Protection** (`syndicateclaw.security.ssrf`):
- Validates URLs by resolving DNS and checking all returned addresses against blocked networks.
- Blocked ranges: `127.0.0.0/8`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `169.254.0.0/16`, `::1/128`, `fd00::/8`.
- Rejects non-HTTP(S) schemes and missing hostnames.
- Raises `SSRFError` with descriptive reason.

### Persistence Layer

**PostgreSQL** (via SQLAlchemy async + asyncpg):
- 14 database tables: `workflow_definitions`, `workflow_runs`, `node_executions`, `tools`, `tool_executions`, `memory_records`, `policy_rules`, `policy_decisions`, `approval_requests`, `audit_events`, `decision_records`, `input_snapshots`, `dead_letter_records`, `api_keys`.
- All tables use ULID primary keys (text), JSONB columns for flexible data, and `created_at`/`updated_at` timestamps.
- Connection pooling: `pool_size=10`, `max_overflow=20`, `pool_pre_ping=True`.
- Migrations managed by Alembic.

**Redis** (via `redis.asyncio` with hiredis):
- Read-through cache for memory records keyed as `syndicateclaw:memory:{namespace}:{key}`.
- Graceful degradation: all Redis operations are wrapped in try/except; failures log warnings but do not block requests.

---

## Data Flow

### Request Flow

1. Client sends HTTP request with JWT/API key.
2. `RequestIDMiddleware` assigns/propagates `X-Request-ID` (ULID).
3. `AuditMiddleware` records the request start time.
4. Route handler resolves `get_current_actor` dependency (JWT → API key → anonymous).
5. Handler executes business logic through service layer.
6. `AuditMiddleware` logs the response status, duration, and actor.
7. Response returned with `X-Request-ID` header.

### Workflow Execution Lifecycle

```
  POST /api/v1/workflows/{id}/runs
           │
           ▼
  WorkflowRun created (PENDING)
           │
           ▼
  WorkflowEngine.execute()
           │
           ▼
  Find START node → execute handler
           │
           ▼
  ┌──── Resolve next node via edges ◄─────────────────┐
  │        │                                           │
  │        ▼                                           │
  │   Execute node handler                             │
  │     │          │           │                       │
  │     │     on failure   on approval                 │
  │     │     retry per    raise WaitForApprovalError  │
  │     │     RetryPolicy  → WAITING_APPROVAL          │
  │     │          │                                   │
  │     ▼          ▼                                   │
  │   success   max retries → FAILED                   │
  │     │                                              │
  │     ├── checkpoint? → persist state                │
  │     │                                              │
  │     ├── END node? → COMPLETED                      │
  │     │                                              │
  │     └── resolve next edge ─────────────────────────┘
  │
  └── No more edges → COMPLETED
```

### Tool Execution Pipeline

```
  ToolExecutor.execute(tool_name, input, context)
           │
           ▼
  Registry lookup → ToolNotFoundError if missing
           │
           ▼
  Input schema validation → ValueError if invalid
           │
           ▼
  Sandbox enforcement → SandboxViolationError if policy violated
           │
           ▼
  PolicyEngine.evaluate() ──┬── DENY → record decision → ToolDeniedError
      (DENY if None)        ├── REQUIRE_APPROVAL → record decision → ApprovalRequiredError
                            └── ALLOW ──▼
                                        │
                              Record decision (MANDATORY)
                              → ToolDeniedError if ledger unavailable
                                        │
                                 Execute handler with timeout
                                  │          │          │
                               success    timeout    exception
                                  │          │          │
                                  ▼          ▼          ▼
                            Response     TIMED_OUT    FAILED
                            sandbox      audit event  audit event
                            check
                              │
                              ▼
                         Validate output → capture input snapshot
                              │
                              ▼
                         COMPLETED audit event → return output
```

---

## Design Decisions

### Safe Expression Evaluator Instead of `eval()`

Edge conditions and decision nodes use a custom recursive-descent parser that only supports a controlled grammar (`state.field == value`, boolean operators, list membership). This eliminates code injection risks from workflow definitions.

### Append-Only Audit Log

The `AuditEventRepository` intentionally lacks update and delete methods. This provides tamper resistance for compliance evidence. High-volume deployments should consider range-partitioning the `audit_events` table by `created_at`.

### Fail-Closed Policy Engine

The default decision when no policy rule matches is `DENY`. This ensures that newly introduced tools or resources are blocked until an explicit `ALLOW` rule is created, preventing accidental exposure.

### Explicit Tool Registration

Tools must be registered at startup via `ToolRegistry.register()`. There is no plugin directory scanning or dynamic imports. This prevents supply-chain attacks where a malicious package could auto-register a tool.

### ULID for Identifiers

All primary keys use ULIDs (Universally Unique Lexicographically Sortable Identifiers) via `python-ulid`. ULIDs are time-sortable, making them efficient for range queries on `created_at` without an additional index, and eliminating the need for sequential integer IDs that leak information about record counts.

### Soft Delete for Memory

Memory records use a three-state lifecycle (`ACTIVE` → `MARKED_FOR_DELETION` → `DELETED`) rather than immediate hard delete. This preserves audit trail integrity and allows recovery within the retention window.

### Graceful Redis Degradation

All Redis operations (cache reads, writes, invalidation) are wrapped in exception handlers that log warnings and continue. The system operates correctly without Redis, falling back to database-only reads with no caching.
