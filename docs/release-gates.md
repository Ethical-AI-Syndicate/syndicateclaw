# SyndicateClaw Release Gates

Go/no-go criteria for three deployment profiles. Each gate builds on the previous one.

This document is an honest assessment of what the system enforces, what it does not, and what must be true before deploying into each profile.

---

## Gate 1: Single-Domain Production

**Profile**: One team, one trust boundary, controlled operators, no external tenants.

This is the deployment profile where the current system is credible.

### Mandatory Configuration

| Setting | Required Value | Why |
|---|---|---|
| `SYNDICATECLAW_ENVIRONMENT` | `production` | Disables anonymous auth fallback |
| `SYNDICATECLAW_RATE_LIMIT_STRICT` | `true` | Fails readiness when rate limiting unavailable |
| `SYNDICATECLAW_REQUIRE_ASYMMETRIC_SIGNING` | `true` | Refuses startup without Ed25519 key |
| `SYNDICATECLAW_ED25519_PRIVATE_KEY_PATH` | valid PEM path | Evidence integrity under partial compromise |
| `SYNDICATECLAW_SECRET_KEY` | 32+ char random value | HMAC + JWT signing base |

### Control Checklist

| Control | Status | Evidence |
|---|---|---|
| **Policy engine fail-closed** | PASS | `ToolExecutor._check_policy()` returns DENY when engine is None; `PolicyEngine.evaluate()` defaults to DENY when no rules match |
| **Mandatory decision ledger** | PASS | Tool execution blocked if ledger unavailable or write fails |
| **Sandbox enforcement on tool execution** | PASS | Pre/post-execution sandbox checks; `SandboxViolationError` on violation |
| **Memory access policy at read/search** | PASS | `_check_access_policy()` on DB reads and cache hits; unknown policies fail closed |
| **Cache isolation for protected records** | PASS | Non-default records never cached; cache hits policy-checked |
| **Self-approval prevention** | PASS | Service layer + API both reject `approver == requested_by` |
| **Approval authority separation** | PASS | `ApprovalAuthorityResolver` overrides client-supplied approvers; requester excluded |
| **Policy management RBAC** | PASS | Create/update/delete require `admin:`/`policy:`/`system:` prefix |
| **Concurrent run admission** | PASS | HTTP 429 when active runs >= `max_concurrent_runs` |
| **Per-actor rate limiting** | PASS | Sliding-window sustained + burst limits; Redis-backed |
| **DB-backed dead letter queue** | PASS | Persists across restarts; classified retries |
| **HMAC-signed audit events** | PASS | `integrity_signature` on event details |
| **HMAC-signed decision records** | PASS | `hmac:<signature>` in side_effects |
| **HMAC-signed evidence bundles** | PASS | `bundle_hash` + `bundle_hmac` on exports |
| **Ed25519 evidence signing** | PASS (when configured) | `SigningKeyPair` loaded at startup; enforced via config gate |
| **DB-backed API key lifecycle** | PASS | SHA-256 hashed; last_used tracking; expiration; revocation |
| **Anonymous auth locked down** | PASS | 401 in production; fallback only in dev/test |
| **Ownership-scoped list endpoints** | PASS | Workflows by owner, runs by initiator, approvals by assignee/requester |
| **State redaction on API responses** | PASS | Sensitive field patterns stripped; allowlist for internal fields |
| **Memory write guardrails** | PASS | Max value size, key/namespace length, nesting depth |
| **Readiness checks dependencies** | PASS | DB, Redis, policy engine, decision ledger, rate limiting status |
| **Input snapshots for replay** | PASS | Tool responses captured; content-hashed for divergence detection |
| **Version manifest capture** | PASS | Workflow/tool/policy versions frozen at run start |
| **Integrity verification jobs** | PASS | Hash verification, unlinked event detection, version drift |
| **Evidence bundle export** | PASS | Complete run artifacts with integrity hashes and HMAC |
| **EdDSA JWT signing** | PASS (when configured) | `jwt_algorithm=EdDSA` aligns auth crypto with evidence crypto |
| **Checkpoint HMAC signing** | PASS | `_persist_checkpoint()` signs; `replay()` verifies; tamper raises ValueError |
| **GET-by-ID ownership enforcement** | PASS | All resource endpoints return 404 for non-owners |
| **Namespace schema validation** | PASS (when configured) | Optional `NamespaceSchemaRegistry` validates structure on write/update |

### Known Limitations (accepted for this gate)

| Limitation | Risk | Mitigation |
|---|---|---|
| RBAC is prefix-based, not role-hierarchy | Admin actors are convention, not enforced identity | Restrict admin-prefixed credentials to trusted operators |
| Rate limiting degrades open when Redis fails (unless strict) | Burst abuse during Redis outage | Enable `rate_limit_strict=true`; monitor Redis availability |
| Semantic memory validation partial | Structural schemas available but no anomaly detection | Namespace schema registry + confidence scores + trust decay provide defense-in-depth |

### Deployment Verification

```bash
# 1. Verify health probes
curl -f http://localhost:8000/healthz
curl -f http://localhost:8000/readyz

# 2. Verify rate limiting is active (readyz should show rate_limiting: ok)
curl -s http://localhost:8000/readyz | jq '.checks.rate_limiting'

# 3. Verify anonymous auth is blocked
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/v1/workflows/
# Expected: 401

# 4. Verify policy default-deny
# (attempt tool execution without ALLOW rule — should be denied)

# 5. Verify API key lifecycle
# (create key via admin, verify it works, revoke it, verify rejection)

# 6. Run integrity verification
# (execute a workflow, export evidence bundle, verify bundle_hmac)
```

### Gate Decision

**GO** if:
- All mandatory configuration is set
- All control checklist items pass
- Known limitations are documented and accepted by the deployment owner
- Readiness probe returns 200 with all checks OK

**NO-GO** if:
- Any mandatory configuration is missing or defaulted
- Policy engine or decision ledger is not initialized
- Anonymous auth is reachable
- Rate limiting is degraded without strict mode acknowledged

---

## Gate 2: Shared-Environment

**Profile**: Multiple teams sharing one deployment, distinct actors, no hard tenant isolation.

This gate requires everything from Gate 1, plus:

**Implementation progress**: Phase 0 (data model, migrations, seed) is complete. Shadow-mode evaluator (Phase 1) is the current active work. Gate 2 remains NO-GO until Phases 1–4 complete with all verification criteria met.

### Additional Requirements

| Requirement | Current Status | Work Needed |
|---|---|---|
| Full RBAC role hierarchy | NOT DONE — prefix-based only | Implement role model: viewer, operator, admin with permission composition |
| Ownership enforcement on all GET endpoints | **DONE** | All GET-by-ID endpoints now enforce actor ownership; non-owners receive 404 |
| Policy read/evaluate access scoping | NOT DONE — open to all authenticated actors | Scope policy visibility by team or namespace |
| Namespace-level access boundaries | PARTIAL — namespace is a grouping, not an access boundary | Enforce namespace-actor binding so teams cannot read/write other teams' namespaces |
| Audit log actor scoping | NOT DONE — any actor can query full audit trail | Filter audit queries by actor ownership or team membership |

### Control Checklist (in addition to Gate 1)

| Control | Status | Requirement |
|---|---|---|
| Role-based access control | NO-GO | Must implement viewer/operator/admin roles with permission sets |
| All read endpoints ownership-scoped | **PASS** | GET by ID verified for actor ownership |
| Namespace access boundaries | NO-GO | Memory namespaces must be bound to actors/teams |
| Audit visibility scoping | NO-GO | Audit queries must respect actor boundaries |
| Cross-team approval isolation | PARTIAL | Authority resolver uses risk-level defaults, not team-scoped authorities |

### Gate Decision

**Current status: NO-GO**

Individual resource visibility is now ownership-enforced (resolved). The remaining blockers are: full RBAC (beyond prefix-based), namespace access boundaries, policy visibility scoping, and audit log actor scoping.

---

## Gate 3: Multi-Tenant

**Profile**: Hard tenant isolation, potentially hostile tenants, regulatory or contractual data boundaries.

This gate requires everything from Gates 1 and 2, plus:

### Additional Requirements

| Requirement | Current Status | Work Needed |
|---|---|---|
| PostgreSQL Row-Level Security | NOT DONE | Add RLS policies scoped to tenant/actor on all tables |
| Asymmetric JWT (RS256/EdDSA) | **DONE** | EdDSA (Ed25519) JWT signing supported via PyJWT; configure `jwt_algorithm=EdDSA` |
| Per-tenant signing keys | NOT DONE | Each tenant needs isolated signing keys for evidence non-repudiation |
| Tenant-scoped Redis | NOT DONE — shared keyspace | Partition Redis by tenant prefix or use separate instances |
| Checkpoint cryptographic signing | **DONE** | Checkpoints HMAC-SHA256 signed; verified on replay |
| API key tenant binding | NOT DONE | API keys must be tenant-scoped with cross-tenant verification blocked |
| Network/egress isolation per tenant | NOT DONE — sandbox policy is per-tool, not per-tenant | Add tenant-level egress rules |
| Audit log tenant isolation | NOT DONE | Per-tenant audit partitioning or RLS-enforced visibility |
| Semantic content validation | **PARTIAL** | Namespace schema registry for structural validation; anomaly detection still needed |

### Control Checklist (in addition to Gates 1+2)

| Control | Status | Requirement |
|---|---|---|
| Database row-level security | NO-GO | RLS policies on all 14 tables |
| Asymmetric JWT signing | **PASS** | EdDSA with Ed25519 key |
| Tenant-scoped signing | NO-GO | Isolated evidence signing keys per tenant |
| Checkpoint integrity | **PASS** | HMAC-SHA256 on checkpoint data |
| Redis tenant isolation | NO-GO | Separate keyspaces or instances |
| Semantic memory validation | PARTIAL | Structural schemas available; anomaly detection needed |

### Gate Decision

**Current status: NO-GO**

The system does not enforce tenant boundaries at the infrastructure layer. All data resides in a single PostgreSQL database without RLS, Redis is shared, and there is no tenant-scoped key management.

---

## Summary Matrix

| Control Domain | Gate 1 (Single Domain) | Gate 2 (Shared Env) | Gate 3 (Multi-Tenant) |
|---|---|---|---|
| Policy enforcement | GO | GO | GO |
| Tool execution controls | GO | GO | GO |
| Audit/evidence integrity | GO | GO | NO-GO (needs per-tenant signing) |
| Memory access control | GO | NO-GO (needs namespace ACLs) | NO-GO |
| Authentication | GO | NO-GO (needs full RBAC) | PARTIAL (EdDSA done; needs per-tenant keys) |
| Rate limiting | GO | GO | GO |
| Approval governance | GO | PARTIAL (needs team scoping) | NO-GO |
| Data isolation | GO (single domain) | PARTIAL (GET scoped; needs namespace ACLs) | NO-GO (needs RLS) |
| Evidence non-repudiation | GO (Ed25519 enforced) | GO | NO-GO (needs tenant keys) |
| Operational readiness | GO | GO | GO |

---

## Evidence Artifacts for Audit

For a Gate 1 deployment, the following artifacts constitute the evidence chain:

1. **Per-run evidence bundle** (`RunExporter.export_run()`) containing:
   - Run metadata and version manifest
   - All node/tool executions
   - All decision records (HMAC-signed)
   - All input snapshots (content-hashed)
   - All approval requests and decisions
   - All audit events (HMAC-signed details)
   - Bundle-level SHA-256 hash + HMAC signature
   - Optional Ed25519 bundle signature

2. **Decision ledger** queryable by run_id or trace_id

3. **Integrity verification** scheduled jobs:
   - Decision record hash verification
   - Snapshot content hash verification
   - Unlinked audit event detection
   - Version/policy drift detection

4. **Dead letter queue** with classified failures and resolution tracking

5. **Structured logs** with actor attribution, request IDs, and OpenTelemetry trace correlation

### Reviewer Questions This System Can Answer

| Question | Where to Find Answer |
|---|---|
| Who initiated this workflow run? | `workflow_runs.initiated_by` |
| What policy was evaluated before tool execution? | `decision_records` for the run |
| Were all tool executions policy-gated? | Decision records are mandatory; missing = execution blocked |
| Who approved this action? | `approval_requests.decided_by` |
| Could the requester have approved their own request? | No — enforced at service + API layer |
| Has the audit trail been tampered with? | Verify `integrity_signature` on event details + bundle HMAC |
| What version of tools/policies were active during this run? | `workflow_runs.version_manifest` |
| What external inputs were used? | `input_snapshots` with content hashes |
| Did the system degrade during this run? | Dead letter records + readiness probe history |
| What was the rate of API requests by this actor? | Rate limit Redis keys + `rate_limit.exceeded` log events |
