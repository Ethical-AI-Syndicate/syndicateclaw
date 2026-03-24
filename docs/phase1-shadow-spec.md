# Phase 1: Shadow Evaluator Specification

**Status:** Implementation-grade design document for Phase 1 shadow mode.  
**Prerequisite:** Phase 0 complete (staging-verified).

---

## 1. Objective

Run the RBAC evaluator on every authenticated API request **without enforcing** the result. Record enough detail to explain every RBAC decision, compare it with the legacy decision, and classify disagreements into a stable taxonomy.

### Non-goals for Phase 1

- No authorization enforcement (legacy system remains authoritative).
- No behavioral change visible to any client.
- No changes to legacy auth code paths.

---

## 2. Shadow Evaluation Record Schema

Every shadow evaluation produces one structured record. These are persisted to the database for querying and emitted as structured log events for real-time dashboards.

### Table: `shadow_evaluations`

| Column | Type | Description |
|---|---|---|
| `id` | ULID | Record identifier |
| `request_id` | text | Correlates to `X-Request-Id` header / middleware-assigned ID |
| `trace_id` | text | OpenTelemetry trace ID (nullable) |
| `timestamp` | timestamptz | Evaluation time |
| `route_name` | text | FastAPI route name (e.g. `create_workflow`) |
| `http_method` | text | GET, POST, PUT, DELETE |
| `path` | text | Full request path |
| `actor` | text | Actor string from `get_current_actor` |
| `principal_id` | text | Resolved principal ULID (null if resolution failed) |
| `team_context` | text | Value of `X-Team-Context` header (null if absent) |
| `team_context_valid` | bool | Whether the team context was validated against memberships |
| `required_permission` | text | Permission from route registry (null if route unregistered) |
| `resolved_scope_type` | text | PLATFORM, TENANT, TEAM, NAMESPACE (null if unresolved) |
| `resolved_scope_id` | text | Scope identifier (null if unresolved) |
| `rbac_decision` | text | `ALLOW` or `DENY` |
| `rbac_deny_reason` | text | Why RBAC denied (null if ALLOW) |
| `rbac_matched_assignments` | jsonb | Role assignments that contributed to the decision |
| `rbac_matched_denies` | jsonb | Deny assignments that triggered (empty array if none) |
| `rbac_permission_source` | text | Role name + scope that granted the permission (null if denied) |
| `legacy_decision` | text | `ALLOW` or `DENY` |
| `legacy_deny_reason` | text | Why legacy denied (null if ALLOW) |
| `agreement` | bool | True if rbac_decision == legacy_decision |
| `disagreement_type` | text | Taxonomy code (null if agreement) |
| `cache_hit` | bool | Whether permission resolution came from cache |
| `evaluation_latency_us` | int | Microseconds for the full RBAC evaluation |
| `created_at` | timestamptz | |

### Indexes

- `ix_shadow_evaluations_disagreement` on `(agreement, disagreement_type)` where `agreement = false`
- `ix_shadow_evaluations_timestamp` on `(timestamp)`
- `ix_shadow_evaluations_route` on `(route_name)`
- `ix_shadow_evaluations_actor` on `(actor)`

---

## 3. Disagreement Taxonomy

Every disagreement is classified into exactly one type. This taxonomy is stable — new types require spec amendment, not ad hoc addition.

| Code | Meaning | Investigation |
|---|---|---|
| `LEGACY_ALLOW_RBAC_DENY` | Legacy permitted, RBAC would have denied | RBAC model too restrictive, or legacy too permissive. Check role assignments and scope. |
| `LEGACY_DENY_RBAC_ALLOW` | Legacy denied, RBAC would have permitted | RBAC model too permissive, or legacy prefix-check too narrow. Check prefix vs role mapping. |
| `SCOPE_RESOLUTION_FAILED` | Could not determine the resource's owning scope | Missing `owning_scope_type` on resource, or resource not found. Fix creation path. |
| `TEAM_CONTEXT_MISSING` | Principal belongs to multiple teams, no `X-Team-Context` header | For list endpoints where actor scope is ambiguous. May need union behavior. |
| `TEAM_CONTEXT_INVALID` | `X-Team-Context` header present but not in principal's memberships | Client error or stale membership. |
| `ROUTE_UNREGISTERED` | Request hit a route not in the permission registry | New route added without RBAC mapping. Blocks Phase 1 completion. |
| `CACHE_ERROR_FALLBACK` | Redis cache error during permission resolution; fell back to DB | Transient. Monitor for sustained occurrences. |
| `PRINCIPAL_NOT_FOUND` | Actor string could not be resolved to a principal | Missing principal record. Seed script gap or new actor. |

---

## 4. RBAC Decision Explanation

Every shadow evaluation record must include enough detail to reconstruct why the RBAC engine reached its decision. This is not optional — a bare ALLOW/DENY without explanation makes the disagreement dashboard a symptom board.

### On ALLOW, record:

- `rbac_permission_source`: The role name and scope that granted the permission (e.g. `"operator @ PLATFORM:platform"`)
- `rbac_matched_assignments`: Array of `{role_id, role_name, scope_type, scope_id, source}` where source is `"direct"` or `"team:{team_id}"`

### On DENY, record:

- `rbac_deny_reason`: One of:
  - `"no_principal"` — actor could not be resolved
  - `"no_matching_grant"` — principal has no role granting this permission in scope
  - `"explicit_deny"` — a deny assignment matched
  - `"scope_not_contained"` — principal has the permission but not in the resource's scope
  - `"expired_assignments_only"` — all matching assignments are expired
- `rbac_matched_denies`: Array of `{deny_id, permission, scope_type, scope_id, reason}`

---

## 5. Legacy Decision Capture

The legacy system's decision is captured by observing what the current code path would do:

| Legacy mechanism | How captured |
|---|---|
| `_require_policy_admin(actor)` | Check `actor.startswith(prefix)` for `POLICY_ADMIN_PREFIXES` |
| Ownership check (`wf.owner == actor`) | Look up resource, compare owner/initiator fields |
| Memory `access_policy` | Invoke `_check_access_policy` logic |
| Approval assignee check | Check `assigned_to` / `requested_by` membership |
| No explicit check (auth only) | Legacy decision is `ALLOW` (any authenticated actor passes) |

The legacy check is performed **in the shadow middleware** by replicating the check logic without calling the actual handler guard. This avoids double-execution and side effects.

---

## 6. Performance Constraints

| Metric | Target | Enforcement |
|---|---|---|
| p99 evaluation latency | < 10ms | Measured per-request; alert if exceeded for 5 min sustained |
| p50 evaluation latency | < 2ms | Measured per-request |
| Cache hit rate | > 80% after warm-up | Alert if < 60% sustained 15 min |
| Shadow record write | Async (must not block response) | Write via background task or async queue |

Shadow evaluation must never add observable latency to the response. The evaluation runs concurrently with the handler or as a post-response task.

---

## 7. Metrics and Dashboards

### Counters (Redis / OpenTelemetry)

| Metric | Key | Incremented on |
|---|---|---|
| **Expected evaluations** | `rbac.shadow.expected` | Every authenticated non-public request entering middleware |
| **Persisted evaluations** | `rbac.shadow.persisted` | After successful DB write of shadow record |
| **Dropped evaluations** | `rbac.shadow.dropped` | Evaluation or persistence failed |
| Total evaluations | `rbac.shadow.total` | Every shadow evaluation completed |
| Agreements | `rbac.shadow.agree` | `agreement = true` |
| Disagreements | `rbac.shadow.disagree` | `agreement = false` |
| By disagreement type | `rbac.shadow.disagree.{type}` | Per taxonomy code |
| RBAC stricter | `rbac.shadow.rbac_stricter` | `LEGACY_ALLOW_RBAC_DENY` |
| Legacy stricter | `rbac.shadow.legacy_stricter` | `LEGACY_DENY_RBAC_ALLOW` |
| Cache hits | `rbac.shadow.cache_hit` | Permission resolved from cache |
| Cache misses | `rbac.shadow.cache_miss` | Permission resolved from DB |
| Unregistered routes | `rbac.shadow.unregistered` | Route not in registry |
| Principal not found | `rbac.shadow.no_principal` | Actor → principal resolution failed |

### Evaluation Completeness

The most important operational metric is **evaluation completeness**: are we recording every evaluation, or silently dropping them?

```
completeness = rbac.shadow.persisted / rbac.shadow.expected
missing      = rbac.shadow.expected - rbac.shadow.persisted - rbac.shadow.dropped
```

- `expected` is incremented **before** evaluation starts (in the middleware dispatch).
- `persisted` is incremented **only after** the shadow record is committed to the database.
- `dropped` is incremented on any evaluation or persistence failure.
- `missing = expected - persisted - dropped` indicates silent failures — records that were neither persisted nor explicitly dropped.

If `expected != persisted + dropped` over any 5-minute window, the shadow system is unreliable and its data cannot be trusted for Phase 1 completion criteria.

### Alerts

| Alert | Condition | Severity |
|---|---|---|
| **`rbac.shadow.completeness_gap`** | **`expected - persisted - dropped > 0` over 5 min** | **P1** |
| `rbac.shadow.disagreement_detected` | Any disagreement | P2 |
| `rbac.shadow.unregistered_route` | Unregistered route hit | P2 (blocks completion) |
| `rbac.shadow.drop_rate_high` | `dropped / expected > 5%` sustained 15 min | P2 |
| `rbac.shadow.latency_p99_high` | p99 > 10ms sustained 5 min | P3 |
| `rbac.shadow.cache_rate_low` | Hit rate < 60% sustained 15 min | P3 |
| `rbac.shadow.principal_missing` | Principal not found | P3 |

---

## 8. Phase 1 Completion Criteria

All must be true before proceeding to Phase 2:

1. Every protected API route is registered in the route permission map.
2. Shadow evaluator runs on every authenticated request.
3. **Evaluation completeness: `persisted / expected >= 99.9%` for 7 consecutive days.** Any gap indicates silent record loss and blocks Phase 1 completion.
4. Zero `ROUTE_UNREGISTERED` disagreements in production for 7 days.
5. Disagreement taxonomy is stable (no new types added in last 7 days).
6. All disagreements are investigated and classified as either:
   - Model flaw (requires RBAC rule change), or
   - Wiring flaw (requires code fix), or
   - Expected divergence (documented and accepted).
7. p99 evaluation latency under 10ms for 7 consecutive days.
8. Shadow dashboard is live and populated with real traffic data.
9. Transitional scaffolding count (V9) is tracked and trending.
10. New audit rows continue to populate `actor_principal_id` and scope fields.
