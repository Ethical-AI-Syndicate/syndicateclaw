"""Static route-to-permission registry for RBAC shadow evaluation.

Every protected API route must have an entry here. The shadow evaluator
uses this registry to determine the required permission and resource scope
for each request. Routes not in this registry trigger a ROUTE_UNREGISTERED
disagreement, which blocks Phase 1 completion.

Scope resolvers are pure async callables: (request, db_session) -> Scope | None.
They must not have side effects. A None return signals scope resolution failure.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from starlette.requests import Request


@dataclass(frozen=True)
class Scope:
    """Resolved resource scope for authorization."""

    scope_type: str  # PLATFORM, TENANT, TEAM, NAMESPACE
    scope_id: str

    PLATFORM = None  # sentinel; use Scope.platform() instead

    @classmethod
    def platform(cls) -> Scope:
        return cls(scope_type="PLATFORM", scope_id="platform")


@dataclass(frozen=True)
class RouteAuthzSpec:
    """Authorization specification for a single API route.

    Attributes:
        permission: Required RBAC permission (e.g. "workflow:create").
        scope_resolver: Async callable that resolves the resource scope from
            the request and a database session. Returns None if scope cannot
            be determined.
        legacy_check: Describes how the legacy system authorizes this route.
            Used by the shadow middleware to replicate legacy decisions.
        owner_field: Which DB column holds the resource owner (for legacy
            ownership checks). None if the route has no ownership guard.
        notes: Free-text implementation notes for reviewers.
    """

    permission: str
    scope_resolver: str = "platform"
    legacy_check: str = "authenticated_only"
    owner_field: str | None = None
    notes: str = ""


# ---------------------------------------------------------------------------
# Scope resolvers
# ---------------------------------------------------------------------------
# Each resolver is a module-level async function: (Request, AsyncSession) -> Scope | None
# The registry references them by string name; the shadow middleware looks them
# up via SCOPE_RESOLVERS[name].

async def resolve_platform(request: Request, session: AsyncSession) -> Scope | None:
    """All platform-scoped resources (tools, system endpoints)."""
    return Scope.platform()


async def resolve_workflow_by_id(request: Request, session: AsyncSession) -> Scope | None:
    """Resolve scope from a workflow's owning_scope columns."""
    wf_id = request.path_params.get("workflow_id")
    if not wf_id:
        return None
    result = await session.execute(
        text("SELECT owning_scope_type, owning_scope_id FROM workflow_definitions WHERE id = :id"),
        {"id": wf_id},
    )
    row = result.first()
    if row is None or row[0] is None:
        return None
    return Scope(scope_type=row[0], scope_id=row[1])


async def resolve_run_by_id(request: Request, session: AsyncSession) -> Scope | None:
    """Resolve scope from a workflow run's owning_scope columns."""
    run_id = request.path_params.get("run_id")
    if not run_id:
        return None
    result = await session.execute(
        text("SELECT owning_scope_type, owning_scope_id FROM workflow_runs WHERE id = :id"),
        {"id": run_id},
    )
    row = result.first()
    if row is None or row[0] is None:
        return None
    return Scope(scope_type=row[0], scope_id=row[1])


async def resolve_workflow_for_run_start(request: Request, session: AsyncSession) -> Scope | None:
    """Resolve scope from the parent workflow when starting a run."""
    wf_id = request.path_params.get("workflow_id")
    if not wf_id:
        return None
    return await resolve_workflow_by_id(request, session)


async def resolve_actor_scope(request: Request, session: AsyncSession) -> Scope | None:
    """For list endpoints scoped to the actor's teams.

    Returns PLATFORM scope — the evaluator checks whether the principal
    has the permission at any scope. Actual row filtering happens in the handler.
    """
    return Scope.platform()


async def resolve_memory_namespace(request: Request, session: AsyncSession) -> Scope | None:
    """Resolve scope from memory namespace via namespace_bindings."""
    namespace = request.path_params.get("namespace")
    if not namespace:
        return Scope.platform()
    result = await session.execute(
        text("""
            SELECT nb.team_id FROM namespace_bindings nb
            JOIN principals p ON p.id = nb.team_id
            WHERE :ns LIKE REPLACE(nb.namespace_pattern, '*', '%')
            ORDER BY LENGTH(nb.namespace_pattern) DESC
            LIMIT 1
        """),
        {"ns": namespace},
    )
    row = result.first()
    if row is None:
        return Scope.platform()
    return Scope(scope_type="TEAM", scope_id=row[0])


async def resolve_memory_record_by_id(request: Request, session: AsyncSession) -> Scope | None:
    """Resolve scope from a memory record's owning_scope columns."""
    record_id = request.path_params.get("record_id")
    if not record_id:
        return None
    result = await session.execute(
        text("SELECT owning_scope_type, owning_scope_id FROM memory_records WHERE id = :id"),
        {"id": record_id},
    )
    row = result.first()
    if row is None or row[0] is None:
        return None
    return Scope(scope_type=row[0], scope_id=row[1])


async def resolve_policy_by_id(request: Request, session: AsyncSession) -> Scope | None:
    """Resolve scope from a policy rule's owning_scope columns."""
    rule_id = request.path_params.get("rule_id")
    if not rule_id:
        return None
    result = await session.execute(
        text("SELECT owning_scope_type, owning_scope_id FROM policy_rules WHERE id = :id"),
        {"id": rule_id},
    )
    row = result.first()
    if row is None or row[0] is None:
        return None
    return Scope(scope_type=row[0], scope_id=row[1])


async def resolve_approval_by_id(request: Request, session: AsyncSession) -> Scope | None:
    """Resolve scope from an approval request's owning_scope columns."""
    approval_id = request.path_params.get("approval_id")
    if not approval_id:
        return None
    result = await session.execute(
        text("SELECT owning_scope_type, owning_scope_id FROM approval_requests WHERE id = :id"),
        {"id": approval_id},
    )
    row = result.first()
    if row is None or row[0] is None:
        return None
    return Scope(scope_type=row[0], scope_id=row[1])


async def resolve_approval_run(request: Request, session: AsyncSession) -> Scope | None:
    """Resolve scope from the run referenced in an approval query."""
    run_id = request.path_params.get("run_id")
    if not run_id:
        return None
    result = await session.execute(
        text("SELECT owning_scope_type, owning_scope_id FROM workflow_runs WHERE id = :id"),
        {"id": run_id},
    )
    row = result.first()
    if row is None or row[0] is None:
        return None
    return Scope(scope_type=row[0], scope_id=row[1])


async def resolve_audit_trace(request: Request, session: AsyncSession) -> Scope | None:
    """Audit trace queries — use platform scope; row-level filtering is separate."""
    return Scope.platform()


# ---------------------------------------------------------------------------
# Resolver lookup table
# ---------------------------------------------------------------------------

SCOPE_RESOLVERS = {
    "platform": resolve_platform,
    "workflow_by_id": resolve_workflow_by_id,
    "run_by_id": resolve_run_by_id,
    "workflow_for_run_start": resolve_workflow_for_run_start,
    "actor_scope": resolve_actor_scope,
    "memory_namespace": resolve_memory_namespace,
    "memory_record_by_id": resolve_memory_record_by_id,
    "policy_by_id": resolve_policy_by_id,
    "approval_by_id": resolve_approval_by_id,
    "approval_run": resolve_approval_run,
    "audit_trace": resolve_audit_trace,
}

# ---------------------------------------------------------------------------
# Route permission map
# ---------------------------------------------------------------------------
# Key: (http_method, route_path) where route_path uses FastAPI's path template syntax.
# Value: RouteAuthzSpec defining the required permission and scope resolution.
#
# This map must cover every protected route. Unregistered routes trigger
# ROUTE_UNREGISTERED in shadow mode.

ROUTE_PERMISSION_MAP: dict[tuple[str, str], RouteAuthzSpec] = {
    # ── Workflows ──────────────────────────────────────────────────────
    ("POST", "/api/v1/workflows/"): RouteAuthzSpec(
        permission="workflow:create",
        scope_resolver="platform",
        legacy_check="authenticated_only",
        notes="Scope is set to PLATFORM at creation time.",
    ),
    ("GET", "/api/v1/workflows/"): RouteAuthzSpec(
        permission="workflow:read",
        scope_resolver="actor_scope",
        legacy_check="ownership_filter",
        owner_field="owner",
        notes="Legacy filters to owner==actor. RBAC: viewer+ at any scope.",
    ),
    ("GET", "/api/v1/workflows/{workflow_id}"): RouteAuthzSpec(
        permission="workflow:read",
        scope_resolver="workflow_by_id",
        legacy_check="ownership_check",
        owner_field="owner",
        notes="Legacy: 404 if owner set and != actor.",
    ),
    ("POST", "/api/v1/workflows/{workflow_id}/runs"): RouteAuthzSpec(
        permission="run:create",
        scope_resolver="workflow_for_run_start",
        legacy_check="authenticated_only",
        notes="Concurrency limit also checked.",
    ),

    # ── Workflow Runs ──────────────────────────────────────────────────
    ("GET", "/api/v1/workflows/runs"): RouteAuthzSpec(
        permission="run:read",
        scope_resolver="actor_scope",
        legacy_check="ownership_filter",
        owner_field="initiated_by",
        notes="Legacy filters to initiated_by==actor.",
    ),
    ("GET", "/api/v1/workflows/runs/{run_id}"): RouteAuthzSpec(
        permission="run:read",
        scope_resolver="run_by_id",
        legacy_check="ownership_check",
        owner_field="initiated_by",
        notes="Legacy: 404 if initiated_by set and != actor.",
    ),
    ("POST", "/api/v1/workflows/runs/{run_id}/pause"): RouteAuthzSpec(
        permission="run:control",
        scope_resolver="run_by_id",
        legacy_check="ownership_check",
        owner_field="initiated_by",
    ),
    ("POST", "/api/v1/workflows/runs/{run_id}/resume"): RouteAuthzSpec(
        permission="run:control",
        scope_resolver="run_by_id",
        legacy_check="ownership_check",
        owner_field="initiated_by",
    ),
    ("POST", "/api/v1/workflows/runs/{run_id}/cancel"): RouteAuthzSpec(
        permission="run:control",
        scope_resolver="run_by_id",
        legacy_check="ownership_check",
        owner_field="initiated_by",
    ),
    ("POST", "/api/v1/workflows/runs/{run_id}/replay"): RouteAuthzSpec(
        permission="run:replay",
        scope_resolver="run_by_id",
        legacy_check="ownership_check",
        owner_field="initiated_by",
    ),
    ("GET", "/api/v1/workflows/runs/{run_id}/nodes"): RouteAuthzSpec(
        permission="run:read",
        scope_resolver="run_by_id",
        legacy_check="authenticated_only",
        notes="Legacy has NO ownership check — scope gap.",
    ),
    ("GET", "/api/v1/workflows/runs/{run_id}/timeline"): RouteAuthzSpec(
        permission="audit:read",
        scope_resolver="run_by_id",
        legacy_check="authenticated_only",
        notes="Legacy has NO ownership check — scope gap.",
    ),

    # ── Memory ─────────────────────────────────────────────────────────
    ("POST", "/api/v1/memory/"): RouteAuthzSpec(
        permission="memory:write",
        scope_resolver="platform",
        legacy_check="authenticated_only",
        notes="Namespace scope resolved from request body, not path.",
    ),
    ("GET", "/api/v1/memory/{namespace}/{key}"): RouteAuthzSpec(
        permission="memory:read",
        scope_resolver="memory_namespace",
        legacy_check="access_policy",
        notes="Legacy: MemoryService._check_access_policy.",
    ),
    ("GET", "/api/v1/memory/{namespace}"): RouteAuthzSpec(
        permission="memory:read",
        scope_resolver="memory_namespace",
        legacy_check="access_policy",
        notes="Legacy: per-row access_policy filter on search.",
    ),
    ("PUT", "/api/v1/memory/{record_id}"): RouteAuthzSpec(
        permission="memory:write",
        scope_resolver="memory_record_by_id",
        legacy_check="access_policy",
    ),
    ("DELETE", "/api/v1/memory/{record_id}"): RouteAuthzSpec(
        permission="memory:delete",
        scope_resolver="memory_record_by_id",
        legacy_check="access_policy",
    ),
    ("GET", "/api/v1/memory/{record_id}/lineage"): RouteAuthzSpec(
        permission="memory:read",
        scope_resolver="memory_record_by_id",
        legacy_check="access_policy",
    ),

    # ── Policies ───────────────────────────────────────────────────────
    ("POST", "/api/v1/policies/"): RouteAuthzSpec(
        permission="policy:manage",
        scope_resolver="platform",
        legacy_check="prefix_admin",
        notes="Legacy: _require_policy_admin (admin:/policy:/system: prefix).",
    ),
    ("GET", "/api/v1/policies/"): RouteAuthzSpec(
        permission="policy:read",
        scope_resolver="actor_scope",
        legacy_check="authenticated_only",
        notes="Legacy: no admin filter, lists all rules.",
    ),
    ("GET", "/api/v1/policies/{rule_id}"): RouteAuthzSpec(
        permission="policy:read",
        scope_resolver="policy_by_id",
        legacy_check="authenticated_only",
        notes="Legacy: no owner/admin check.",
    ),
    ("PUT", "/api/v1/policies/{rule_id}"): RouteAuthzSpec(
        permission="policy:manage",
        scope_resolver="policy_by_id",
        legacy_check="prefix_admin",
    ),
    ("DELETE", "/api/v1/policies/{rule_id}"): RouteAuthzSpec(
        permission="policy:manage",
        scope_resolver="policy_by_id",
        legacy_check="prefix_admin",
    ),
    ("POST", "/api/v1/policies/evaluate"): RouteAuthzSpec(
        permission="policy:evaluate",
        scope_resolver="platform",
        legacy_check="authenticated_only",
        notes="Body carries actor/resource for evaluation; no admin check.",
    ),

    # ── Inference / providers (Gate 1 absent; ProviderService runs 2–4) ──
    ("POST", "/api/v1/inference/chat"): RouteAuthzSpec(
        permission="inference:invoke_chat",
        scope_resolver="platform",
        legacy_check="authenticated_only",
    ),
    ("POST", "/api/v1/inference/embedding"): RouteAuthzSpec(
        permission="inference:invoke_embedding",
        scope_resolver="platform",
        legacy_check="authenticated_only",
    ),
    ("POST", "/api/v1/inference/chat/stream"): RouteAuthzSpec(
        permission="inference:invoke_chat",
        scope_resolver="platform",
        legacy_check="authenticated_only",
    ),
    ("GET", "/api/v1/providers/"): RouteAuthzSpec(
        permission="provider:read",
        scope_resolver="platform",
        legacy_check="authenticated_only",
    ),
    ("POST", "/api/v1/providers/catalog/sync-models-dev"): RouteAuthzSpec(
        permission="catalog:sync_models_dev",
        scope_resolver="platform",
        legacy_check="authenticated_only",
        notes="Pull models.dev JSON (SSRF-hardened); merge into ModelCatalog only.",
    ),

    # ── Tools ──────────────────────────────────────────────────────────
    ("GET", "/api/v1/tools/"): RouteAuthzSpec(
        permission="tool:read",
        scope_resolver="platform",
        legacy_check="authenticated_only",
    ),
    ("GET", "/api/v1/tools/{tool_name}"): RouteAuthzSpec(
        permission="tool:read",
        scope_resolver="platform",
        legacy_check="authenticated_only",
    ),
    ("POST", "/api/v1/tools/{tool_name}/execute"): RouteAuthzSpec(
        permission="tool:execute",
        scope_resolver="platform",
        legacy_check="authenticated_only",
        notes="Legacy: executor may 403 via ToolDeniedError (policy engine, not auth).",
    ),

    # ── Approvals ──────────────────────────────────────────────────────
    ("GET", "/api/v1/approvals/"): RouteAuthzSpec(
        permission="approval:read",
        scope_resolver="actor_scope",
        legacy_check="approval_visibility",
        notes="Legacy: SQL filter to assigned_to or requested_by.",
    ),
    ("GET", "/api/v1/approvals/{approval_id}"): RouteAuthzSpec(
        permission="approval:read",
        scope_resolver="approval_by_id",
        legacy_check="approval_visibility",
        notes="Legacy: 404 if not requester and not in assigned_to.",
    ),
    ("POST", "/api/v1/approvals/{approval_id}/approve"): RouteAuthzSpec(
        permission="approval:decide",
        scope_resolver="approval_by_id",
        legacy_check="approval_assignee",
        notes="Legacy: 403 if self-approval or not in assignee list.",
    ),
    ("POST", "/api/v1/approvals/{approval_id}/reject"): RouteAuthzSpec(
        permission="approval:decide",
        scope_resolver="approval_by_id",
        legacy_check="authenticated_only",
        notes="Legacy: no assignee check on reject, only pending check.",
    ),
    ("GET", "/api/v1/approvals/runs/{run_id}"): RouteAuthzSpec(
        permission="approval:read",
        scope_resolver="approval_run",
        legacy_check="approval_visibility",
    ),

    # ── Audit ──────────────────────────────────────────────────────────
    ("GET", "/api/v1/audit/"): RouteAuthzSpec(
        permission="audit:read",
        scope_resolver="actor_scope",
        legacy_check="authenticated_only",
        notes="Legacy: no row-level restriction by caller actor.",
    ),
    ("GET", "/api/v1/audit/trace/{trace_id}"): RouteAuthzSpec(
        permission="audit:read",
        scope_resolver="audit_trace",
        legacy_check="authenticated_only",
    ),
    ("GET", "/api/v1/audit/runs/{run_id}/timeline"): RouteAuthzSpec(
        permission="audit:read",
        scope_resolver="run_by_id",
        legacy_check="authenticated_only",
        notes="Legacy: no run ownership check.",
    ),
}

# Public routes that skip shadow evaluation entirely.
PUBLIC_ROUTES: set[tuple[str, str]] = {
    ("GET", "/healthz"),
    ("GET", "/readyz"),
    ("GET", "/api/v1/info"),
}


def get_route_spec(method: str, path_template: str) -> RouteAuthzSpec | None:
    """Look up the authorization spec for a route.

    Returns None if the route is not registered (triggers ROUTE_UNREGISTERED).
    """
    return ROUTE_PERMISSION_MAP.get((method.upper(), path_template))


def is_public_route(method: str, path_template: str) -> bool:
    """Check if a route is public (no auth required)."""
    return (method.upper(), path_template) in PUBLIC_ROUTES


def get_scope_resolver(
    name: str,
) -> Callable[[Request, AsyncSession], Coroutine[Any, Any, Scope | None]]:
    """Return the scope resolver function by name.

    Raises KeyError if the resolver is not registered.
    """
    return SCOPE_RESOLVERS[name]


def get_all_registered_routes() -> list[tuple[str, str]]:
    """Return all registered route keys for validation against app routes."""
    return list(ROUTE_PERMISSION_MAP.keys())
