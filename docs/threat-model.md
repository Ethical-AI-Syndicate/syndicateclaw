# SyndicateClaw Threat Model

This document identifies assets, threat actors, and attack vectors for the SyndicateClaw platform using the STRIDE framework. Each threat includes implemented mitigations and residual risk.

---

## Assets

| Asset | Sensitivity | Location |
|---|---|---|
| **Workflow state** | HIGH — may contain PII, credentials, business logic | PostgreSQL `workflow_runs.state` (JSONB) |
| **Memory records** | HIGH — knowledge base, may contain PII | PostgreSQL `memory_records.value` (JSONB), Redis cache |
| **Audit log** | HIGH — compliance evidence, tamper-sensitive | PostgreSQL `audit_events` (append-only) |
| **Tool execution capabilities** | CRITICAL — tools can make HTTP requests, write data | In-process tool handlers, registered at startup |
| **Policy rules** | HIGH — misconfiguration grants unauthorized access | PostgreSQL `policy_rules` |
| **Approval requests** | MEDIUM — approval bypass could escalate privilege | PostgreSQL `approval_requests` |
| **JWT secret key** | CRITICAL — compromise allows full impersonation | Environment variable `SECRET_KEY` |
| **Database credentials** | CRITICAL — full data access | Environment variable `DATABASE_URL` |

---

## Threat Actors

| Actor | Access Level | Motivation |
|---|---|---|
| **Malicious user with valid credentials** | Authenticated API access | Data exfiltration, unauthorized tool execution, policy bypass |
| **Compromised tool/plugin** | Runs within the tool executor process | SSRF, data exfiltration, lateral movement |
| **Internal actor with elevated privileges** | Admin-level API key or JWT | Audit log tampering, policy rule manipulation, approval self-grant |
| **External attacker** | No credentials (network access only) | Credential theft, denial of service, exploitation of public endpoints |

---

## STRIDE Analysis

### 1. Spoofing

**Threat**: An attacker impersonates a legitimate actor to gain unauthorized access.

**Attack vectors**:
- Stolen or leaked JWT tokens
- Brute-forced API keys
- Replayed expired tokens

**Mitigations implemented**:
- JWT authentication with `python-jose` and HS256 signing (`syndicateclaw.security.auth`)
- API key verification via `X-API-Key` header (`verify_api_key()`)
- Token expiration (`exp` claim) enforced on decode
- Actor identity bound to every request via `get_current_actor` dependency
- All audit events include actor attribution

**Residual risk**:
- ~~HS256 is symmetric — server compromise exposes the signing key~~ **RESOLVED**: JWT signing now supports EdDSA (Ed25519) alongside HS256. When `jwt_algorithm=EdDSA` is configured with an Ed25519 key, JWT tokens are signed asymmetrically — the signing key can be isolated in a KMS/HSM while the public key is distributed for verification. HS256 remains as a fallback. Token verification tries EdDSA first when a public key is available.
- ~~API key store is currently a static dict~~ **RESOLVED**: `ApiKeyService` provides database-backed key management with SHA-256 hashing, `last_used_at` tracking, expiration, and revocation with actor attribution. The static dict fallback remains for backward compatibility but is superseded when the DB-backed service is active.
- Anonymous fallback is enabled in development mode. Must be disabled in production.

---

### 2. Tampering

**Threat**: An attacker modifies data in transit or at rest to alter system behavior.

**Attack vectors**:
- Modify workflow state to skip approval gates
- Alter audit events to hide malicious activity
- Tamper with policy rules to grant unauthorized access
- Modify checkpoint data to corrupt workflow replay

**Mitigations implemented**:
- **Append-only audit log**: `AuditEventRepository` has no `update()` or `delete()` methods — events can only be appended and queried.
- **Checkpoint verification**: Workflow state is JSON-serialized to `checkpoint_data`; replays restore from checkpoint.
- **Database transactions**: All mutations are wrapped in `session.begin()` with automatic rollback on failure.
- **JSONB storage**: Complex objects stored as JSONB columns prevent SQL injection in structured data.

**Residual risk**:
- A database admin with direct access can still modify or delete audit rows. Consider using PostgreSQL row-level security or a dedicated append-only data store (e.g., AWS QLDB).
- ~~Checkpoint data is not cryptographically signed~~ **RESOLVED**: Checkpoints are now HMAC-SHA256 signed when a signing key is configured. The `_persist_checkpoint()` method wraps the serialized state in a `{"data": ..., "checkpoint_hmac": "<hex>"}` envelope. On replay, `_verify_checkpoint_hmac()` recomputes the HMAC and raises `ValueError` on mismatch, preventing tampered checkpoints from being loaded.

---

### 3. Repudiation

**Threat**: An actor performs an action and later denies it.

**Attack vectors**:
- Performing tool executions without audit trail
- Approving requests without decision logging
- Modifying policy rules without attribution

**Mitigations implemented**:
- **Full audit trail**: Every significant action emits an `AuditEvent` with `actor`, `event_type`, `resource_type`, `resource_id`, `action`, and `details`.
- **Approval audit chain**: Approval requests record `requested_by`, `decided_by`, `decided_at`, and `decision_reason`.
- **Policy decision logging**: Every policy evaluation produces a `PolicyDecision` record with the matched rule, actor, reason, and condition results.
- **OpenTelemetry integration**: `trace_id` and `span_id` on audit events enable distributed trace correlation.
- **Request ID tracking**: Every HTTP request is tagged with a ULID-based `X-Request-ID` for end-to-end tracing.

**Residual risk**:
- ~~Audit events are not digitally signed~~ **RESOLVED**: Audit event `details` are now HMAC-SHA256 signed using a key derived from the application secret. Decision records append `hmac:<signature>` to `side_effects`. Evidence bundles include a `bundle_hmac` field. An attacker with database-only access cannot fabricate valid signatures without the application secret.
- An attacker with both database and application secret access could still forge events. Consider migrating to asymmetric signing (RS256) for stronger repudiation resistance.

---

### 4. Information Disclosure

**Threat**: Sensitive data is exposed to unauthorized actors.

**Attack vectors**:
- Reading memory records across namespaces
- Extracting credentials from workflow state via API
- Leaking sensitive data through audit event details
- Redis cache exposing memory values

**Mitigations implemented**:
- **Namespace-scoped memory**: Memory reads and searches are scoped to a single namespace.
- **Access policies**: Each memory record has a named `access_policy` field (default `"default"`).
- **Audit redaction**: `ToolAuditConfig` supports `redact_fields` — a list of field paths to strip before logging tool inputs/outputs.
- **Soft delete lifecycle**: Deleted records transition through `MARKED_FOR_DELETION` before purge, preventing accidental exposure of "deleted" data during the retention window.

**Residual risk**:
- ~~Access policy enforcement is not yet fully implemented at the query layer~~ **RESOLVED**: Memory `access_policy` is now enforced at read and search time. Supported policies: `default` (any authenticated actor), `owner_only` (record actor only), `system_only` (system-prefixed actors), `restricted` (record actor only). Unknown policies fail closed (denied).
- ~~Workflow state JSONB is returned in full via API responses~~ **RESOLVED**: All workflow run API responses now pass through `WorkflowRunResponse.from_orm_redacted()` which applies schema-based redaction. Fields matching sensitive patterns (password, secret, token, api_key, credential, private_key, auth, ssn, credit_card, cvv) are replaced with `[REDACTED]`. Internal workflow fields (`_run_id`, `_started_at`, `_completed_at`, `_decision`) are allowlisted.
- Redis cache keys are predictable (`syndicateclaw:memory:{namespace}:{key}`). An attacker with Redis access can enumerate keys.
- ~~Cache bypass: the access policy check occurs after the DB read path but the Redis cache path returns records without checking access policy~~ **RESOLVED**: The cache is now actor-aware. Records with non-default access policies are never written to the Redis cache. Cache hits are checked against `_check_access_policy()` before being returned, so a protected record that somehow enters the cache is still denied to unauthorized actors.

---

### 5. Denial of Service

**Threat**: An attacker exhausts system resources to make the platform unavailable.

**Attack vectors**:
- Launching many concurrent workflow runs
- Creating deeply nested sub-workflows
- Flooding the audit log with events
- Triggering expensive tool executions repeatedly

**Mitigations implemented**:
- **Max concurrent runs**: `Settings.max_concurrent_runs` (default 100) limits parallel workflow executions.
- **Max workflow depth**: `Settings.max_workflow_depth` (default 10) prevents infinite sub-workflow nesting.
- **Tool timeouts**: Every tool has a `timeout_seconds` (default 30s) enforced via `asyncio.wait_for()`.
- **Database connection pooling**: `pool_size=10`, `max_overflow=20` with `pool_pre_ping=True` prevents connection exhaustion.
- **Query pagination**: All list endpoints enforce `limit` (max 200-500) with offset pagination.

**Residual risk**:
- ~~No rate limiting middleware is currently implemented~~ **RESOLVED**: Redis-backed per-actor rate limiting is now enforced via `RateLimitMiddleware`. Configurable sustained rate (`rate_limit_requests` per `rate_limit_window_seconds`) and burst limit (`rate_limit_burst` per 1-second sub-window). Exceeded limits return HTTP 429 with `Retry-After` and `X-RateLimit-*` headers. Health/docs paths are exempt. Degrades open if Redis is unavailable.
- Audit log writes are unbounded — a high-throughput attack could fill disk. Consider log rotation or partitioning.
- ~~The dead letter queue is an in-memory asyncio.Queue~~ **RESOLVED**: The dead letter queue is now database-backed (PostgreSQL `dead_letter_records` table), surviving process restarts. Errors are classified as transient (3 retries) or permanent (0 retries).

---

### 6. Elevation of Privilege

**Threat**: An actor gains access to resources or capabilities beyond their authorization level.

**Attack vectors**:
- Executing HIGH/CRITICAL risk tools without approval
- Self-approving requests (approver is also requester)
- Modifying policy rules to grant themselves ALLOW
- Registering a malicious tool that escalates privileges

**Mitigations implemented**:
- **Policy-gated tool execution**: `ToolExecutor` checks the policy engine before every invocation. `DENY` and `REQUIRE_APPROVAL` effects block execution.
- **Assignee enforcement**: Approval decisions are restricted to actors listed in `assigned_to`. An actor not in the list receives `PermissionError`.
- **Risk classification**: Tools declare their `ToolRiskLevel` (LOW, MEDIUM, HIGH, CRITICAL) and `required_permissions`.
- **Owner enforcement**: Workflows and policy rules record their `owner` for audit attribution.
- **No auto-loading**: Tools cannot be registered except through explicit startup code, preventing runtime injection.

**Residual risk**:
- ~~RBAC is not yet implemented~~ **PARTIALLY RESOLVED**: Policy management endpoints (create, update, delete) now require actors with `admin:`, `policy:`, or `system:` prefix. Read/list/evaluate endpoints remain open to any authenticated actor. A full role hierarchy beyond prefix-based checks is not yet implemented.
- **Update**: RBAC Phase 0 schema is deployed. Shadow-mode evaluation is active. Full enforcement is blocked on Phase 3 (intersection enforcement) completing with zero disagreements for 7+ days. Until cutover, prefix-based RBAC remains the authoritative access control mechanism.
- ~~Self-approval is only prevented by the assigned_to list~~ **RESOLVED**: Self-approval is now explicitly prohibited. The `ApprovalService._decide()` method and the API `approve` endpoint both reject requests where `approver == requested_by` with a `PermissionError` / HTTP 403.
- ~~Policy rule creation is accessible to any authenticated actor~~ **RESOLVED**: Policy rule creation, update, and deletion require an admin-prefixed actor. Unauthorized actors receive HTTP 403.
- ~~Residual: the `assigned_to` list on approval requests is still set by the requester~~ **RESOLVED**: An `ApprovalAuthorityResolver` now determines eligible approvers based on tool risk level and policy rules. The requester is always excluded from the resolved set. Client-supplied `assigned_to` lists are overridden when the resolver is active. Resolution order: policy-defined approvers → risk-level defaults → admin fallback.

---

## SSRF Protection

Server-Side Request Forgery is mitigated at two layers:

### `syndicateclaw.security.ssrf.validate_url()`

- Rejects non-HTTP(S) schemes.
- Blocks hostnames that resolve to private/internal IPs.
- Resolves DNS before checking to defend against DNS rebinding.
- Blocked networks: `127.0.0.0/8`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `169.254.0.0/16`, `::1/128`, `fd00::/8`.
- Raises `SSRFError` with the specific reason.

### `syndicateclaw.tools.builtin.http_request_handler()`

- Validates the URL hostname via `_is_private_ip()` before making the request.
- Additional blocked ranges include `0.0.0.0/8`, `fe80::/10`, `fc00::/7`.
- Response body is truncated to 100,000 characters to prevent memory exhaustion.

### `syndicateclaw.channels.webhook.WebhookChannel`

- Validates the base URL on construction and each derived URL on send.
- Blocks localhost, raw private IPs, and common private IP prefixes.

**Residual risk**:
- DNS rebinding with very short TTLs could bypass the single-resolution check. Consider pinning DNS results or using a custom resolver.
- IPv6-mapped IPv4 addresses (e.g., `::ffff:127.0.0.1`) should be tested for coverage.

---

## Memory Poisoning

An attacker could inject false knowledge into the memory service to manipulate downstream agent decisions.

**Mitigations implemented**:

| Control | Description |
|---|---|
| **Confidence scores** | Every record has a `confidence` float (0.0–1.0), validated on write. Downstream consumers can filter low-confidence records. |
| **Provenance tracking** | `MemoryLineage` records `parent_ids`, `workflow_run_id`, `node_execution_id`, `tool_name`, and `derivation_method`. Lineage can be traversed via `GET /api/v1/memory/{record_id}/lineage`. |
| **TTL/retention** | Records expire via `ttl_seconds` / `expires_at`. `RetentionEnforcer` purges expired records on schedule. |
| **Soft delete** | Records are not immediately purged — `MARKED_FOR_DELETION` status preserves audit trail. |
| **Namespace isolation** | Memory is scoped by namespace; cross-namespace reads require knowing the namespace. |
| **Actor attribution** | Every write records the `actor` and `source` that created the record. |

**Residual risk**:
- A compromised agent with write access to a namespace can inject records with confidence 1.0, though write guardrails now limit the damage surface.
- ~~There is no content validation or anomaly detection on memory values~~ **MOSTLY RESOLVED**: Write guardrails enforce max value size (1MB default), max key/namespace length, and max nesting depth (20 levels). Additionally, an optional `NamespaceSchemaRegistry` enables per-namespace structural validation: required fields, field type checking, max field count, and extra field restrictions. This covers structural integrity; semantic content validation (anomaly detection, truthfulness) remains unimplemented.

---

## Cross-Tenant Isolation

While SyndicateClaw does not yet implement multi-tenancy at the infrastructure level, several isolation mechanisms exist:

| Mechanism | Scope |
|---|---|
| **Namespace-based memory isolation** | Memory reads/writes/searches are scoped to a single namespace. Cross-namespace access requires explicitly specifying another namespace. |
| **Actor-scoped policy evaluation** | Policy decisions include the `actor` field. Rules can have conditions that match on actor identity. |
| **Workflow owner enforcement** | `WorkflowDefinition.owner` and `WorkflowRun.initiated_by` track ownership and initiation. |
| **Approval assignee restriction** | Only actors in `assigned_to` can approve/reject requests. |

**Residual risk**:
- All data resides in a single PostgreSQL database. Row-level security is not enforced at the database layer.
- ~~API endpoints do not filter results by actor ownership~~ **RESOLVED**: All endpoints are now ownership-scoped. List endpoints: workflow lists filter by `owner == actor`, run lists filter by `initiated_by == actor`, approval lists filter by `assigned_to.contains(actor) OR requested_by == actor`. GET-by-ID endpoints: `get_workflow` verifies `owner == actor`, `get_run`/`pause`/`resume`/`cancel`/`replay` verify `initiated_by == actor`, `get_approval` verifies actor is in `assigned_to` or is `requested_by`, memory `update`/`delete`/`lineage` enforce `_check_access_policy`. Non-matching actors receive HTTP 404.
- A shared Redis instance means cache keys from different namespaces are co-located.

---

## Recommendations

1. ~~**Replace static API key store**~~ **DONE**: `ApiKeyService` provides DB-backed key management with SHA-256 hashing, `last_used_at` tracking, expiration, and revocation with actor attribution.
2. ~~**Implement rate limiting** middleware~~ **DONE**: Redis-backed per-actor sliding-window rate limiter (`RateLimitMiddleware`) with configurable sustained and burst thresholds. Returns 429 with `Retry-After` headers.
3. ~~**Add RBAC**~~ **PARTIALLY DONE**: Policy management endpoints now require admin-prefixed actors. Full role hierarchy (viewer, operator, admin) across all endpoints is still needed.
4. ~~**Sign audit events** cryptographically to prevent fabrication~~ **DONE**: Audit event details, decision records, and evidence bundles are HMAC-SHA256 signed. Additionally, Ed25519 asymmetric signing (`SigningKeyPair`, `Ed25519Verifier`) is available for non-repudiation when the private key is isolated (KMS/HSM).
5. ~~**Enforce access policies** at the memory query layer~~ **DONE**: `MemoryService._check_access_policy()` enforces `default`, `owner_only`, `system_only`, and `restricted` policies on read and search paths. Unknown policies fail closed.
6. **Disable anonymous fallback** in production via environment configuration.
7. ~~**Migrate to RS256** for JWT signing to support key rotation without shared secrets~~ **DONE**: JWT signing now supports EdDSA (Ed25519) asymmetric signing via PyJWT. Configure `jwt_algorithm=EdDSA` with an Ed25519 private key. Token verification tries EdDSA first when a public key is available, with HS256 fallback.
8. **Add row-level security** in PostgreSQL for multi-tenant deployments.
9. ~~**Persist the dead letter queue**~~ **DONE**: Dead letter queue is now backed by the `dead_letter_records` PostgreSQL table with error classification, retry limits, and manual resolution tracking.
10. ~~**Implement content validation** on memory writes~~ **MOSTLY DONE**: Write guardrails enforce max value size, max key/namespace length, and max nesting depth. Optional per-namespace schema validation is now available via `NamespaceSchemaRegistry`. Semantic validation (anomaly detection, truthfulness) is still needed.
11. ~~**Add actor/ownership filtering** on list endpoints to prevent cross-actor data leakage~~ **DONE**: Workflow list filters by `owner`, run list filters by `initiated_by`, and approval list filters by `assigned_to`/`requested_by`.
12. ~~**Lock down anonymous auth fallback** so it cannot be enabled outside explicit dev mode~~ **DONE**: Anonymous fallback only activates when `SYNDICATECLAW_ENVIRONMENT` is set to `development`, `dev`, `test`, or `testing`. Production environments return HTTP 401.
