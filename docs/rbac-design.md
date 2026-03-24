# SyndicateClaw RBAC Design Specification

This document defines the role-based access control model for Gate 2 (shared-environment) and provides the foundation for Gate 3 (multi-tenant). It is a design artifact — no code should be written until this spec is reviewed and accepted.

---

## Design Constraints

1. The model must replace the current prefix-based convention (`admin:`, `policy:`, `system:`) with a structured, queryable system.
2. Existing Gate 1 enforcement (ownership checks, policy RBAC, self-approval prevention) must continue to work during migration.
3. The model must support Gate 2 (team-scoped isolation) without requiring infrastructure changes (no RLS, no separate databases).
4. The model must be extensible to Gate 3 (tenant isolation) without redesign.
5. Denial must always take precedence over grants (deny-wins).
6. No matching grant implies denial (fail-closed, consistent with existing policy engine behavior).

---

## 1. Principals

A **principal** is any entity that can authenticate and perform actions.

```
Principal
├── User            # Human actor with credentials (JWT or API key)
├── ServiceAccount  # System/agent identity (workflow engine, retention enforcer, etc.)
└── Team            # Group of principals sharing a scope boundary
```

### Principal properties

| Property | Type | Description |
|---|---|---|
| `id` | ULID | Unique identifier |
| `principal_type` | enum | `USER`, `SERVICE_ACCOUNT`, `TEAM` |
| `name` | string | Human-readable name (unique within type) |
| `tenant_id` | string? | Tenant affiliation (null for platform principals; required for Gate 3) |
| `enabled` | bool | Disabled principals cannot authenticate |
| `created_at` | datetime | |
| `updated_at` | datetime | |

### Team membership

Teams are flat (no nested teams). A principal can belong to multiple teams. Team membership is stored as a many-to-many relation.

| Column | Type |
|---|---|
| `principal_id` | FK → principals |
| `team_id` | FK → principals (where type=TEAM) |
| `granted_at` | datetime |
| `granted_by` | string |

**Rationale**: Nested teams create permission explosion and make audit trails ambiguous. Flat teams are simpler to reason about and enforce.

---

## 2. Roles

A **role** is a named collection of permissions. Roles exist at two levels:

- **Built-in roles**: defined by the platform, immutable, always available.
- **Custom roles**: defined by tenant/team administrators, scoped to their domain.

### Built-in role hierarchy

```
platform_admin
    └── tenant_admin
            └── admin
                    └── operator
                            └── viewer
```

Each role is a strict superset of the one below it. This means:
- `viewer` permissions are included in `operator`
- `operator` permissions are included in `admin`
- and so on

| Role | Intended Use | Inherits From |
|---|---|---|
| `viewer` | Read-only access to resources within scope | — |
| `operator` | Execute workflows, write memory, use tools | `viewer` |
| `admin` | Manage policies, tools, approvals, API keys within scope | `operator` |
| `tenant_admin` | Manage teams, roles, namespace bindings within tenant | `admin` |
| `platform_admin` | Cross-tenant operations, system configuration | `tenant_admin` |

### Role properties

| Property | Type | Description |
|---|---|---|
| `id` | ULID | |
| `name` | string | Unique within scope |
| `description` | string | |
| `built_in` | bool | Cannot be modified or deleted |
| `permissions` | list[Permission] | Explicit permission grants |
| `inherits_from` | string? | Parent role name (for hierarchy) |
| `scope_type` | enum | `PLATFORM`, `TENANT`, `TEAM` — where this role can be assigned |
| `created_by` | string | |

---

## 3. Permissions

A **permission** is a verb-resource pair representing a single capability. Permissions are the atomic unit of authorization.

### Permission vocabulary

Permissions follow the pattern: `<resource>:<action>`

| Permission | Description | Minimum Role |
|---|---|---|
| **Workflow** | | |
| `workflow:read` | View workflow definitions | `viewer` |
| `workflow:create` | Create workflow definitions | `operator` |
| `workflow:execute` | Start, pause, resume, cancel, replay runs | `operator` |
| `workflow:manage` | Delete workflows, modify others' workflows | `admin` |
| **Run** | | |
| `run:read` | View workflow runs and node executions | `viewer` |
| `run:create` | Start new runs | `operator` |
| `run:control` | Pause, resume, cancel runs | `operator` |
| `run:replay` | Replay completed/failed runs | `operator` |
| **Memory** | | |
| `memory:read` | Read memory records within accessible namespaces | `viewer` |
| `memory:write` | Create memory records | `operator` |
| `memory:update` | Modify existing records | `operator` |
| `memory:delete` | Soft-delete records | `operator` |
| `memory:manage` | Hard-delete, modify access policies | `admin` |
| **Policy** | | |
| `policy:read` | View policy rules | `viewer` |
| `policy:evaluate` | Trigger policy evaluation | `operator` |
| `policy:manage` | Create, update, disable policy rules | `admin` |
| **Tool** | | |
| `tool:read` | View tool definitions | `viewer` |
| `tool:execute` | Execute tools (still subject to policy engine) | `operator` |
| `tool:manage` | Register, update, disable tools | `admin` |
| **Approval** | | |
| `approval:read` | View approval requests | `viewer` |
| `approval:decide` | Approve or reject requests | `operator` |
| `approval:manage` | Override expired approvals, reassign | `admin` |
| **Audit** | | |
| `audit:read` | Query audit events within scope | `viewer` |
| `audit:export` | Export evidence bundles | `admin` |
| **Team** | | |
| `team:read` | View team membership | `viewer` |
| `team:manage` | Add/remove members, modify team properties | `tenant_admin` |
| **API Key** | | |
| `apikey:read` | List API keys (own only for viewer, all for admin) | `viewer` |
| `apikey:create` | Create new API keys | `admin` |
| `apikey:revoke` | Revoke existing keys | `admin` |
| **Namespace** | | |
| `namespace:bind` | Bind namespaces to teams | `tenant_admin` |
| `namespace:read` | View namespace bindings | `viewer` |
| **System** | | |
| `system:configure` | Modify runtime configuration | `platform_admin` |
| `system:impersonate` | Act as another principal (audit-logged) | `platform_admin` |

### Permission composition per role

```
viewer:
  workflow:read, run:read, memory:read, policy:read, tool:read,
  approval:read, audit:read, team:read, apikey:read, namespace:read

operator:  (inherits viewer)
  workflow:create, workflow:execute,
  run:create, run:control, run:replay,
  memory:write, memory:update, memory:delete,
  policy:evaluate, tool:execute, approval:decide

admin:  (inherits operator)
  workflow:manage, memory:manage, policy:manage, tool:manage,
  approval:manage, audit:export, apikey:create, apikey:revoke

tenant_admin:  (inherits admin)
  team:manage, namespace:bind

platform_admin:  (inherits tenant_admin)
  system:configure, system:impersonate
```

---

## 4. Resource Scopes

A **scope** defines the boundary within which a role assignment is effective. Every role assignment is a triple: `(principal, role, scope)`.

### Scope hierarchy

```
platform                          # global — visible to platform_admin only
└── tenant:<tenant_id>            # tenant boundary
    └── team:<team_id>            # team boundary
        └── namespace:<pattern>   # memory/resource namespace
```

### Scope resolution rules

1. A role granted at a **broader** scope applies to all narrower scopes within it.
   - `(alice, admin, tenant:acme)` → alice is admin for all teams and namespaces within tenant acme.
2. A role granted at a **narrower** scope does not grant access outside that scope.
   - `(bob, operator, team:alpha)` → bob can only operate within team alpha's resources.
3. **Scope inheritance is downward only.** Broader scopes grant access to narrower scopes, never the reverse.

### Scope binding

Resources are bound to scopes through ownership and namespace assignment:

| Resource | Scope Source |
|---|---|
| Workflow definitions | `owner` field → resolved to team via principal-team membership |
| Workflow runs | `initiated_by` field → resolved to team |
| Memory records | `namespace` field → resolved via namespace-team binding |
| Policy rules | `owner` field → resolved to team; global rules owned by `platform_admin` |
| Approval requests | Inherited from the workflow run's scope |
| Audit events | `actor` field → resolved to team; `resource_id` provides secondary scope |
| Tools | Global (platform-scoped); tool visibility can be restricted by policy |
| API keys | `actor` field → resolved to principal's team scope |

### Namespace-team binding

A new table `namespace_bindings` declares which teams own which namespaces:

| Column | Type | Description |
|---|---|---|
| `id` | ULID | |
| `namespace_pattern` | string | Exact or glob pattern (e.g., `"team-alpha:*"`) |
| `team_id` | FK → principals | The team that owns this namespace range |
| `access_level` | enum | `OWNER`, `READ_WRITE`, `READ_ONLY` |
| `granted_by` | string | Principal who created the binding |
| `created_at` | datetime | |

**Resolution**: When a principal attempts to access a memory namespace, the system:
1. Looks up the principal's team memberships.
2. Matches the namespace against all `namespace_bindings` for those teams.
3. If no binding matches, access is denied (fail-closed).
4. If a binding matches, the `access_level` determines allowed operations.

---

## 5. Role Assignments

A **role assignment** binds a principal to a role within a scope.

### Table: `role_assignments`

| Column | Type | Description |
|---|---|---|
| `id` | ULID | |
| `principal_id` | FK → principals | Who |
| `role_id` | FK → roles | What role |
| `scope_type` | enum | `PLATFORM`, `TENANT`, `TEAM`, `NAMESPACE` |
| `scope_id` | string | The specific scope identifier (tenant ID, team ID, namespace pattern) |
| `granted_by` | string | Who granted this assignment |
| `granted_at` | datetime | |
| `expires_at` | datetime? | Optional time-limited assignment |
| `revoked` | bool | Soft-revoke without deletion |
| `revoked_at` | datetime? | |
| `revoked_by` | string? | |

### Assignment rules

1. **Only principals with a role at the same or broader scope can grant roles.**
   - A `tenant_admin` at `tenant:acme` can assign `admin` at `team:alpha` (within acme).
   - An `admin` at `team:alpha` cannot assign `admin` at `team:beta`.
2. **No self-elevation.** A principal cannot assign themselves a role equal to or higher than their current role.
3. **Expired assignments are treated as absent.** The enforcement layer checks `expires_at` at evaluation time.
4. **Revoked assignments are treated as absent.** Revocation is preferred over deletion for audit.
5. **Team membership grants team-scoped role access.** If a team has a role assignment, all members of that team inherit that assignment.

---

## 6. Decision Semantics

### Authorization evaluation algorithm

For a request `(principal, permission, resource)`:

```
function authorize(principal, permission, resource) -> ALLOW | DENY:

    1. Resolve effective_roles = all role assignments for principal
       (direct + inherited through team membership)
       excluding expired and revoked assignments.

    2. Resolve resource_scope = the scope that owns this resource.
       (workflow.owner → team → tenant, or namespace → binding → team → tenant)

    3. For each role in effective_roles:
       a. If role.scope does not contain resource_scope → skip (out of scope).
       b. If role grants permission (directly or via inheritance) → mark ALLOW candidate.
       c. If any explicit DENY assignment exists for this principal+scope → return DENY.

    4. If at least one ALLOW candidate exists → return ALLOW.
    5. Otherwise → return DENY (implicit, fail-closed).
```

### Denial precedence

**Explicit DENY always wins.** If any role assignment carries a deny flag for a specific permission within a scope, that denial overrides all grants, regardless of role level. Any matching deny at any containing scope returns DENY immediately, regardless of grant specificity or role level. There is no "most specific scope wins" override for denies — a deny at tenant scope blocks a grant at team scope, and a deny at team scope blocks a grant at namespace scope. Implementers must not invent specificity-based deny resolution.

This supports use cases like:
- Temporarily revoking a specific permission without removing the role.
- Blocking a principal from a specific namespace while keeping their team role.

### Deny assignments (optional extension)

A **deny assignment** is a role assignment with a `deny` flag. It carries a specific permission or permission set and overrides any grants.

| Column | Type |
|---|---|
| `id` | ULID |
| `principal_id` | FK → principals |
| `permission` | string |
| `scope_type` | enum |
| `scope_id` | string |
| `reason` | string |
| `granted_by` | string |
| `expires_at` | datetime? |

Deny assignments are checked before grant evaluation. If a matching deny exists, authorization returns DENY immediately.

---

## 7. Migration from Prefix-Based Convention

The current system uses string prefix conventions (`admin:`, `policy:`, `system:`) for authorization checks. Migration must be backward-compatible.

### Migration strategy

**Phase 1: Shadow mode** (no behavioral change)
- Deploy the principal, role, role_assignment, and namespace_binding tables.
- Populate principals from existing actors (API keys, JWT subjects).
- Create built-in roles with the permission sets defined above.
- Create role assignments that match current prefix-based behavior:
  - `admin:*` actors → `admin` role at platform scope.
  - `policy:*` actors → custom role with `policy:manage` at platform scope.
  - `system:*` actors → `platform_admin` role.
- Log authorization decisions from both old and new systems; alert on disagreement.

**Phase 2: Dual enforcement**
- Wire the RBAC evaluator into `get_current_actor` or a new `authorize` dependency.
- Route handlers call `authorize(actor, permission, resource)` in addition to prefix checks.
- If both systems agree, proceed. If they disagree, log and use the old system's decision.
- Run for one release cycle to validate.

**Phase 3: Cutover**
- Remove all `_require_policy_admin()` / `startswith("admin:")` / `startswith("system:")` checks.
- Replace with `authorize()` calls.
- The prefix convention becomes a naming convention only, with no enforcement meaning.

**Phase 4: Cleanup**
- Remove the `POLICY_ADMIN_PREFIXES` constant and `_require_policy_admin()` function.
- Update documentation to reference roles instead of prefixes.

---

## 8. Enforcement Points

Every API endpoint must map to a required permission. The enforcement dependency resolves authorization before the handler executes.

### Endpoint → permission mapping

| Endpoint | Method | Required Permission | Scope Source |
|---|---|---|---|
| **Workflows** | | | |
| `/api/v1/workflows/` | POST | `workflow:create` | actor's team |
| `/api/v1/workflows/` | GET | `workflow:read` | actor's teams |
| `/api/v1/workflows/{id}` | GET | `workflow:read` | workflow.owner's team |
| `/api/v1/workflows/{id}/runs` | POST | `run:create` | workflow.owner's team |
| `/api/v1/workflows/runs` | GET | `run:read` | actor's teams |
| `/api/v1/workflows/runs/{id}` | GET | `run:read` | run.initiated_by's team |
| `/api/v1/workflows/runs/{id}/pause` | POST | `run:control` | run.initiated_by's team |
| `/api/v1/workflows/runs/{id}/resume` | POST | `run:control` | run.initiated_by's team |
| `/api/v1/workflows/runs/{id}/cancel` | POST | `run:control` | run.initiated_by's team |
| `/api/v1/workflows/runs/{id}/replay` | POST | `run:replay` | run.initiated_by's team |
| `/api/v1/workflows/runs/{id}/nodes` | GET | `run:read` | run.initiated_by's team |
| `/api/v1/workflows/runs/{id}/timeline` | GET | `audit:read` | run.initiated_by's team |
| **Memory** | | | |
| `/api/v1/memory/` | POST | `memory:write` | namespace binding |
| `/api/v1/memory/{ns}/{key}` | GET | `memory:read` | namespace binding |
| `/api/v1/memory/{ns}` | GET | `memory:read` | namespace binding |
| `/api/v1/memory/{id}` | PUT | `memory:update` | namespace binding |
| `/api/v1/memory/{id}` | DELETE | `memory:delete` | namespace binding |
| `/api/v1/memory/{id}/lineage` | GET | `memory:read` | namespace binding |
| **Policies** | | | |
| `/api/v1/policies/` | POST | `policy:manage` | policy.owner's team |
| `/api/v1/policies/` | GET | `policy:read` | actor's teams |
| `/api/v1/policies/{id}` | GET | `policy:read` | policy.owner's team |
| `/api/v1/policies/{id}` | PUT | `policy:manage` | policy.owner's team |
| `/api/v1/policies/{id}` | DELETE | `policy:manage` | policy.owner's team |
| `/api/v1/policies/evaluate` | POST | `policy:evaluate` | inferred from request |
| **Tools** | | | |
| `/api/v1/tools/` | GET | `tool:read` | platform |
| `/api/v1/tools/{name}` | GET | `tool:read` | platform |
| `/api/v1/tools/{name}/execute` | POST | `tool:execute` | platform (+ policy engine) |
| **Approvals** | | | |
| `/api/v1/approvals/` | GET | `approval:read` | actor's teams |
| `/api/v1/approvals/{id}` | GET | `approval:read` | approval scope |
| `/api/v1/approvals/{id}/approve` | POST | `approval:decide` | approval scope |
| `/api/v1/approvals/{id}/reject` | POST | `approval:decide` | approval scope |
| `/api/v1/approvals/runs/{id}` | GET | `approval:read` | run scope |
| **Audit** | | | |
| `/api/v1/audit/` | GET | `audit:read` | actor's teams |
| `/api/v1/audit/trace/{id}` | GET | `audit:read` | trace scope |
| `/api/v1/audit/runs/{id}/timeline` | GET | `audit:read` | run scope |

### Enforcement dependency

```python
async def require_permission(
    permission: str,
    resource_scope: Scope | None = None,
) -> Callable:
    """FastAPI dependency that checks RBAC before handler execution.

    Usage:
        @router.get("/")
        async def list_workflows(
            actor: str = Depends(get_current_actor),
            _auth: None = Depends(require_permission("workflow:read")),
        ):
    """
```

The dependency:
1. Resolves the principal from the actor identity.
2. Loads effective role assignments (direct + team-inherited, excluding expired/revoked).
3. Checks deny assignments first — if any match, returns 403.
4. Checks if any effective role grants the required permission within the resource scope.
5. If no grant matches, returns 403.
6. Logs the authorization decision to the audit trail.

---

## 9. Audit Visibility Scoping

Once RBAC is in place, audit queries must respect scope boundaries:

1. **Viewer/Operator/Admin** at team scope: can only see audit events where `actor` is a member of their team, or `resource_id` belongs to a resource owned by their team.
2. **Tenant Admin**: can see all audit events within their tenant.
3. **Platform Admin**: can see all audit events.

The audit query endpoints must accept the authorization context and filter results accordingly. This is not a UI concern — it must be enforced at the query layer.

### Implementation approach

Resource scope metadata (`resource_scope_type`, `resource_scope_id`) is **denormalized into audit event rows at write time**. This eliminates polymorphic resource lookups during audit queries. The audit service resolves the target resource's owning scope when the event is created and stores it alongside the event.

The `scope_filter` on `AuditEventRepository.query()` restricts results based on the principal's effective scope, querying denormalized columns directly:
- `actor_principal_id = principal_id` (self-generated events), OR
- `resource_scope_type` / `resource_scope_id` matches one of the principal's accessible scopes.
- Events with NULL `resource_scope_type` (system-level events, unresolvable resources) are visible only to the generating actor and `platform_admin`.

Both conditions are OR-joined: you can see events you created OR events affecting resources within your scope. This is a single indexed scan, not a polymorphic join.

---

## 10. Interaction with Existing Controls

### Policy engine

The RBAC model does not replace the policy engine. They operate at different layers:

| Layer | System | Question Answered |
|---|---|---|
| **Identity** | RBAC | "Is this principal allowed to attempt this action?" |
| **Governance** | Policy Engine | "Given that the principal is allowed, should this specific action be permitted?" |

A request must pass both checks:
1. RBAC: does the principal have the required permission in scope? (fail → 403)
2. Policy: does the policy engine allow this specific resource action? (fail → ToolDeniedError / REQUIRE_APPROVAL)

### Approval authority resolver

The `ApprovalAuthorityResolver` currently uses risk-level defaults. With RBAC, it should also consider:
- Only principals with `approval:decide` permission in the relevant scope.
- Team-scoped authority: approvers must be in a team with visibility to the workflow/tool being approved.

### Ownership checks

The current ownership checks (`wf.owner == actor`, `run.initiated_by == actor`) become a subset of scope-based authorization. Once RBAC is active:
- Ownership is still recorded for provenance.
- Access is determined by scope membership, not direct identity comparison.
- An admin in the same team can access another member's workflows.

---

## 11. Data Model Summary

### New tables

| Table | Purpose |
|---|---|
| `principals` | User, service account, and team identities |
| `team_memberships` | Many-to-many principal ↔ team |
| `roles` | Built-in and custom role definitions |
| `role_permissions` | Permissions granted by each role |
| `role_assignments` | Principal → role → scope bindings |
| `deny_assignments` | Explicit permission denials |
| `namespace_bindings` | Namespace → team ownership |

### Modified tables

| Table | Change |
|---|---|
| `workflow_definitions` | `owner` becomes FK → principals (migration: create principal for each existing owner string) |
| `workflow_runs` | `initiated_by` becomes FK → principals |
| `memory_records` | `actor` becomes FK → principals |
| `approval_requests` | `requested_by`, `decided_by`, `assigned_to` reference principals |
| `audit_events` | `actor` becomes FK → principals. Add `real_actor`, `impersonation_session_id`, `resource_scope_type`, `resource_scope_id`. Scope columns are denormalized from the target resource at write time to avoid polymorphic joins during audit visibility queries. |
| `api_keys` | `actor` becomes FK → principals |

### Migration notes

- All existing actor strings (e.g., `"dev-agent"`, `"admin:ops"`) are migrated to `principals` rows.
- FK migrations are backward-compatible: the string columns are retained as `actor_legacy` during transition, with the FK column added alongside.
- A data migration script populates principal rows and FK values from existing string data.

---

## 12. Design Decisions (resolved)

The following five questions were identified during initial design and have been resolved with binding decisions. These decisions constrain the implementation and must not be revisited without re-review.

---

### Decision 1: Cross-team namespace sharing

**Question**: Should teams be able to share namespaces? If team A grants `READ_ONLY` access to team B on namespace `"shared:*"`, does that create a transitive visibility chain for audit events?

**Decision**: Cross-team namespace sharing is allowed, but only as an explicit binding. It is never transitive.

**Rules**:

1. A team can grant another team `READ_ONLY` or `READ_WRITE` access to a namespace it owns, via a `namespace_binding` row where `team_id` is the grantee and `granted_by` is a `tenant_admin` or `admin` of the owning team.
2. Sharing does not propagate. If team A shares `ns:data` with team B, and team B has its own share with team C on a different namespace, team C gains zero visibility into `ns:data`. There is no transitive closure.
3. Audit visibility does not follow sharing. A `READ_ONLY` binding on a namespace grants the ability to read memory records within that namespace. It does **not** grant visibility into audit events generated by the owning team's members while accessing that namespace. Audit visibility is governed solely by role scope (section 9), not namespace bindings.
4. The `access_level` on a namespace binding controls data operations only:

| `access_level` | `memory:read` | `memory:write` | `memory:update` | `memory:delete` |
|---|---|---|---|---|
| `OWNER` | yes | yes | yes | yes |
| `READ_WRITE` | yes | yes | yes | no |
| `READ_ONLY` | yes | no | no | no |

**Rationale**: Transitive sharing creates unpredictable visibility expansion. Every access boundary must be explicitly granted and independently auditable. If a future use case demands transitive sharing, it should be modeled as a distinct mechanism (e.g., "federation") with its own review.

---

### Decision 2: Service account model

**Question**: How are service accounts scoped? Should they bypass RBAC?

**Decision**: Service accounts are regular principals. They receive explicit role assignments. There is no RBAC bypass.

**Rules**:

1. Service accounts have `principal_type = SERVICE_ACCOUNT`. They authenticate via API key (no JWT).
2. Service accounts receive role assignments like any other principal. The workflow engine (`system:engine`), retention enforcer (`system:retention`), and DLQ processor (`system:dlq`) each get the minimum permissions they need:

| Service Account | Role | Scope | Permissions Needed |
|---|---|---|---|
| `system:engine` | `operator` | `platform` | `workflow:execute`, `run:create`, `run:control`, `tool:execute`, `memory:read`, `memory:write` |
| `system:retention` | custom: `retention_worker` | `platform` | `memory:delete`, `memory:manage` |
| `system:dlq` | custom: `dlq_worker` | `platform` | `audit:read` (to read failed events for retry) |

3. There is exactly one narrow exception: **process bootstrap**. During application startup (the `lifespan` function), before the RBAC system is initialized, the application registers tools and creates built-in roles using direct database access. This is not an RBAC bypass — it is pre-RBAC initialization. Once the lifespan completes and the app accepts requests, all actions go through RBAC.
4. No runtime action by any service account bypasses RBAC evaluation. If a service account lacks a required permission, the action fails with 403 like any other principal.
5. **Gate 3 caveat**: The current platform-scoped service account model is sufficient for Gates 1 and 2, where all tenants share a trust domain. For Gate 3 (multi-tenant isolation), service accounts must become tenant-scoped or operate within tenant-bound execution contexts. A platform-scoped `system:engine` that can access all tenants' data is incompatible with hard tenant isolation. This will require either per-tenant service accounts or a tenant context parameter on all internal service calls. That redesign is explicitly deferred to Gate 3 planning.

**Rationale**: A hidden bypass class undermines the entire model. If the system's own components cannot operate under its own authorization model, the model is incomplete. The bootstrap exception is narrow, auditable (it runs once at startup), and does not affect request-time authorization.

---

### Decision 3: Custom role composability

**Question**: Should custom roles be composable as explicit permission sets, or must they inherit from a built-in role?

**Decision**: Custom roles are permission-set based. They do not use the built-in inheritance chain.

**Rules**:

1. Built-in roles (`viewer`, `operator`, `admin`, `tenant_admin`, `platform_admin`) remain hierarchical. Their permission sets are fixed and cannot be modified.
2. Custom roles declare an explicit set of permissions. They do not inherit from built-in roles.
3. Custom roles may optionally declare a `display_base` field (e.g., `"based_on": "operator"`) for UI convenience (showing what built-in role is closest). This field has **zero enforcement effect** — it is metadata only.
4. Custom roles are scoped: a custom role created at `team:alpha` scope can only be assigned within `team:alpha` or narrower scopes.
5. Custom roles cannot include `system:configure` or `system:impersonate` permissions. These are reserved for `platform_admin`.
6. The permission set is stored as a JSON array on the `roles` table. Role evaluation resolves to this explicit list, not to inheritance traversal.

**Example**:

```json
{
  "name": "ml-operator",
  "built_in": false,
  "scope_type": "TEAM",
  "display_base": "operator",
  "permissions": [
    "tool:read",
    "tool:execute",
    "memory:read",
    "memory:write",
    "memory:update",
    "run:read",
    "policy:read"
  ]
}
```

**Rationale**: Inheritance-only custom roles force everything into the `viewer < operator < admin` line, which cannot express constrained blends. Permission-set roles are more verbose but completely unambiguous in evaluation. The `display_base` metadata preserves UX clarity without creating enforcement coupling.

---

### Decision 4: Role resolution caching

**Question**: What is the caching strategy for role resolution?

**Decision**: Cache effective permissions per principal, keyed by principal ID and a version stamp. Invalidation is event-driven with a short TTL backstop.

**Rules**:

1. **Cache key**: `rbac:perms:{principal_id}:{version}`
2. **Cache value**: A JSON object mapping `scope_id → set[permission]` for all scopes the principal has access to. This includes resolved permissions from direct assignments, team-inherited assignments, and built-in role hierarchy expansion.
3. **Version stamp**: A monotonically increasing integer stored in Redis at key `rbac:version:{principal_id}`. Incremented on any event that affects the principal's permissions.
4. **Invalidation events** (each increments the version stamp for affected principals):
   - Role assignment created, updated, or revoked → version bump for the assignee principal.
   - Team membership added or removed → version bump for the affected principal.
   - Role definition changed (permissions modified) → version bump for **all principals** holding that role.
   - Namespace binding created, updated, or removed → version bump for all members of the affected team.
5. **TTL backstop**: Cached entries expire after **60 seconds** regardless of version. This is a safety net, not the primary invalidation mechanism.
6. **Cache miss behavior**: On miss, resolve permissions from the database, populate cache, and proceed. Cache population is not in the critical path for correctness — a stale or missing cache only affects latency.
7. **Deny assignments are never cached.** They are always evaluated from the database on every request. This prevents a stale cache from silently overriding an active deny.

**Rationale**: Event-driven invalidation ensures near-instant permission updates (e.g., revoking access takes effect immediately, not after TTL). The short TTL backstop prevents permanent staleness if an invalidation event is lost. Deny-from-database ensures that the most security-critical decisions are never stale.

---

### Decision 5: Impersonation audit schema

**Question**: How does impersonation interact with audit?

**Decision**: Impersonation is a first-class auditable session with structured fields on every derived event.

**Schema — `impersonation_sessions` table**:

| Column | Type | Description |
|---|---|---|
| `id` | ULID | Session identifier |
| `real_principal_id` | FK → principals | The platform_admin who is impersonating |
| `effective_principal_id` | FK → principals | The principal being impersonated |
| `reason` | text | Required: why this impersonation is happening |
| `approval_reference` | text | Optional: ticket ID, incident number, or approval request ID |
| `started_at` | datetime | Session start |
| `ended_at` | datetime? | Null while active; set on explicit end or timeout |
| `max_duration_seconds` | int | Hard cap (default: 3600). Session auto-expires. |
| `permissions_restricted` | JSON? | Optional subset of effective principal's permissions. If set, impersonator operates with *fewer* permissions than the effective principal, not more. |

**Rules**:

1. Only principals with `system:impersonate` permission (i.e., `platform_admin`) can start an impersonation session.
2. `reason` is mandatory and non-empty. An impersonation without justification is rejected.
3. Every audit event emitted during an active impersonation session carries two additional fields:

| Field | Value |
|---|---|
| `impersonation_session_id` | The session ULID |
| `real_actor` | The `real_principal_id` from the session |

The existing `actor` field on audit events is set to the **effective** principal (the one being impersonated), so that downstream systems see the action as if the original principal performed it. The `real_actor` field provides the true attribution for forensic review.

4. Impersonation sessions appear in the audit trail as `IMPERSONATION_STARTED` and `IMPERSONATION_ENDED` events, both attributed to the `real_actor`.
5. Impersonation does not grant permissions the effective principal does not have. The impersonator operates with the effective principal's permissions (or a restricted subset), never their own `platform_admin` permissions. This prevents using impersonation as a privilege escalation vector.
6. Active impersonation sessions are listed in the readiness probe payload (`/readyz`) under a `"active_impersonations"` count, so operators have visibility into ongoing sessions.

**Rationale**: Burying impersonation in free-text `details` fields makes forensic analysis unreliable. Structured fields ensure every impersonated action is machine-queryable. The `real_actor` / `effective_actor` separation preserves downstream log analysis while maintaining full attribution. The permission restriction option allows scoped impersonation for debugging without granting full access.

---

## 13. Additional Rules

The following rules were identified during review as necessary to prevent implementation ambiguity. They are binding.

---

### Rule A: Canonical owning scope on resource creation

**Problem**: Several scope sources rely on resolving an owner or initiator to a team membership. If a principal belongs to multiple teams, or their team membership changes after resource creation, scope resolution becomes non-deterministic.

**Rule**: Every resource records a **canonical owning scope** at creation time. This scope is immutable for the lifetime of the resource.

**Implementation**:

1. Add column `owning_scope_type` (enum: `PLATFORM`, `TENANT`, `TEAM`) and `owning_scope_id` (string) to: `workflow_definitions`, `workflow_runs`, `memory_records`, `approval_requests`, `policy_rules`.
2. At creation time, the owning scope is resolved from the creating principal's context:
   - If the principal belongs to exactly one team → scope is that team.
   - If the principal belongs to multiple teams → the request must include an `X-Team-Context` header specifying which team scope to use. If omitted, the request is rejected with 400. The header is a **selection hint only** — the system verifies the requested team is in the principal's current effective memberships. A principal cannot claim a team they do not belong to. Invalid or unrecognized team IDs are rejected with 400, never silently defaulted.
   - If the principal belongs to no team → scope is the principal's tenant (or platform for platform-scoped principals).
3. Authorization checks use the resource's `owning_scope_id`, not the current team membership of the owner. If the owner later leaves the team, the resource remains accessible to other team members.
4. Resources can be transferred between scopes by a `tenant_admin` or `platform_admin` via a dedicated transfer API. Transfers are audited.

**Rationale**: Recomputing ownership from current memberships creates authorization drift. A principal who creates a workflow, changes teams, and then the original team loses access to the workflow is a real failure mode. Canonical scope prevents this.

---

### Rule B: Namespace binding conflict resolution

**Problem**: Namespace bindings use exact and glob patterns. Overlapping patterns can create conflicting access grants.

**Rule**: Conflicts are resolved deterministically. If resolution is ambiguous, the binding is rejected at write time.

**Resolution order** (most specific wins):

1. **Exact match** beats any glob. `"team-alpha:metrics"` beats `"team-alpha:*"`.
2. **Longer prefix** beats shorter prefix. `"team-alpha:metrics:*"` beats `"team-alpha:*"`.
3. **At equal specificity, the existing binding wins.** A new binding that would create an ambiguous overlap with an existing binding at the same specificity level is rejected with a 409 Conflict response. The operator must explicitly remove or narrow the existing binding first.

**Write-time validation**:

When creating a namespace binding, the system checks all existing bindings for the same team and all bindings from other teams that overlap the pattern:

- If the new binding is strictly more specific than all overlapping bindings → allowed.
- If the new binding is strictly less specific than an existing binding for the **same team** → allowed (the more specific binding takes precedence at resolution time).
- If the new binding overlaps an existing binding from a **different team** at equal specificity → rejected (409).
- If the new binding is an exact duplicate → rejected (409).

**Read-time resolution**:

When resolving namespace access for a principal:

1. Collect all namespace bindings for the principal's teams.
2. Match the target namespace against all binding patterns.
3. Select the most specific match (exact > longer glob > shorter glob).
4. If multiple bindings match at the same specificity level for different teams, and the principal is in both teams, use the **highest access level** among them.

**Rationale**: Without deterministic conflict resolution, namespace authorization becomes order-dependent and unstable. Rejecting ambiguous bindings at write time is safer than inventing runtime resolution rules that operators cannot predict.

---

### Rule C: Audit visibility rules for shared resources

**Problem**: The original spec defined audit visibility as "events where actor is in your team OR resource belongs to your team." This is too broad — shared resources may reveal more actor behavior than intended.

**Rule**: Audit visibility is determined by three criteria, evaluated in order. The principal sees events matching **any** of these:

1. **Self-generated events**: Events where `actor` is the querying principal. Every principal can always see their own audit trail.
2. **Resource-scoped events**: Events where the `resource_id` refers to a resource whose `owning_scope_id` matches a scope the principal has `audit:read` permission in. This means you can see events affecting resources your team owns, regardless of which actor generated them.
3. **Elevated visibility**: Principals with `audit:read` at `tenant` scope see all events within their tenant. Principals with `audit:read` at `platform` scope see all events.

**What this explicitly excludes**:

- A `viewer` or `operator` in team A **cannot** see events generated by a team B member, even if that team B member was acting on a shared namespace — unless the event affects a resource owned by team A.
- Namespace sharing (`READ_ONLY` / `READ_WRITE` bindings) does **not** expand audit visibility. A team that receives a `READ_ONLY` binding on another team's namespace can read memory records, but cannot see audit events about those records unless they generated the events themselves.
- Team membership alone does not grant visibility into all teammate activity. A `viewer` sees their own events plus events affecting team-owned resources. They do not see a teammate's tool execution events unless those events affected a team resource.

**Admin/tenant_admin visibility**: A principal with `admin` role at team scope sees all events affecting team-owned resources (same as `viewer` for resource-scoped events, but broader because `admin` role includes `audit:export`). A `tenant_admin` sees all events within the tenant. This follows from normal scope resolution — no special audit-specific rules are needed.

**Rationale**: Broad "any teammate's events" visibility creates information leakage channels that are hard to audit and harder to explain. Resource-scoped visibility is predictable: you see what happens to things you own. Self-visibility is a baseline right. Elevated visibility is role-gated. This is the tightest model that remains operationally useful.

---

## 14. Decision Examples

Concrete scenarios to validate the model against.

### Example 1: Cross-team memory access

- Team Alpha owns namespace `"alpha:data"`.
- Team Beta has a `READ_ONLY` namespace binding on `"alpha:data"`.
- User `bob` is a member of Team Beta with role `operator` at team scope.

**bob reads `alpha:data/sensor-1`**: Allowed. Bob has `memory:read` (from `operator` role), and Team Beta has `READ_ONLY` on `alpha:data`.

**bob writes `alpha:data/new-record`**: Denied. `READ_ONLY` does not grant `memory:write` on this namespace, regardless of bob's role permissions.

**bob queries audit events for `alpha:data/sensor-1`**: Bob sees only audit events he generated himself (self-visibility). He does not see events generated by Team Alpha members accessing the same record, because the resource's `owning_scope_id` is Team Alpha, and bob does not have `audit:read` in Team Alpha's scope.

### Example 2: Multi-team principal

- User `carol` is a member of Team Alpha and Team Beta.
- Carol creates a workflow. The request includes `X-Team-Context: team-alpha`.
- The workflow's `owning_scope_id` is set to `team:alpha`.

**Team Beta member `dave` tries to read carol's workflow**: Denied (404). The workflow is owned by Team Alpha. Dave is not in Team Alpha.

**Carol later leaves Team Alpha**: The workflow remains accessible to other Team Alpha members. Carol loses access to it (her team membership no longer includes Team Alpha, and the canonical scope is `team:alpha`).

### Example 3: Service account execution

- The workflow engine runs as `system:engine` with `operator` role at platform scope.
- A workflow run triggers a tool execution.

**RBAC check**: Does `system:engine` have `tool:execute` at the relevant scope? Yes — platform scope covers all narrower scopes. Allowed.

**Policy check**: The policy engine evaluates the tool-specific rules (risk level, conditions). This is independent of RBAC. The policy engine may still deny the execution.

**Audit**: The tool execution audit event records `actor = system:engine`. No impersonation — the engine acts as itself.

### Example 4: Impersonation

- Platform admin `root-admin` needs to debug an issue affecting user `alice` in Team Alpha.
- `root-admin` starts an impersonation session: `effective_principal = alice`, `reason = "Investigating workflow failure INC-4521"`.

**During impersonation**: `root-admin` executes API calls. Each call is authorized against alice's permissions (operator in Team Alpha), not root-admin's platform_admin permissions. Audit events record `actor = alice`, `real_actor = root-admin`, `impersonation_session_id = <session>`.

**root-admin tries to modify a policy rule (requires admin)**: Denied. Alice is an operator, not an admin. Impersonation does not escalate — it constrains.

### Example 5: Deny assignment

- User `eve` has `operator` role at `team:gamma` scope (grants `tool:execute`).
- A deny assignment exists: `(eve, tool:execute, team:gamma)` with reason "Under investigation - INC-9001".

**eve attempts to execute a tool**: Denied (403). The deny assignment is checked before role grants. The deny wins regardless of eve's role.

**eve reads a workflow**: Allowed. The deny is specific to `tool:execute`. Other permissions from eve's `operator` role are unaffected.

---

## 15. Success Criteria

The RBAC implementation is complete when:

1. All prefix-based authorization checks are removed from route handlers.
2. Every endpoint enforces permissions via the `require_permission` dependency.
3. Namespace access is mediated by `namespace_bindings`, not convention.
4. Audit queries respect scope boundaries per Rule C (self-generated + resource-scoped + elevated).
5. A principal in team A cannot see, modify, or execute resources owned by team B (unless explicitly granted cross-team access via namespace binding).
6. Cross-team namespace sharing does not expand audit visibility (Decision 1).
7. Service accounts operate under RBAC with explicit role assignments — no bypass paths (Decision 2).
8. Custom roles resolve to explicit permission sets, not inheritance chains (Decision 3).
9. Role resolution cache invalidates within one request cycle of any permission-affecting event (Decision 4).
10. Deny assignments are never served from cache (Decision 4, rule 7).
11. Impersonation sessions are first-class audit records with structured `real_actor` / `effective_actor` fields (Decision 5).
12. Every resource carries a canonical `owning_scope_id` set at creation time (Rule A).
13. Namespace binding conflicts are rejected at write time, not resolved at read time (Rule B).
14. Role assignments are audited (creation, modification, revocation).
15. The shadow mode migration has run for at least one release cycle with zero disagreements between old and new authorization systems.
16. Gate 2 control checklist items all pass.
