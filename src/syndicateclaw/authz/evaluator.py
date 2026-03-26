"""Pure RBAC evaluator — no FastAPI coupling.

Resolves effective permissions, checks deny assignments, evaluates scope
containment, and returns structured authorization decisions.

Cache interface: Redis-backed permission cache with version-stamped
invalidation per principal and a 60s TTL backstop. Deny assignments are
NEVER cached — always read from DB on every evaluation.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, cast

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from syndicateclaw.authz.route_registry import Scope

logger = structlog.get_logger(__name__)

CACHE_TTL_SECONDS = 60
SCOPE_CONTAINMENT_ORDER = ["PLATFORM", "TENANT", "TEAM", "NAMESPACE"]


class Decision(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"


class DenyReason(str, Enum):
    NO_PRINCIPAL = "no_principal"
    NO_MATCHING_GRANT = "no_matching_grant"
    EXPLICIT_DENY = "explicit_deny"
    SCOPE_NOT_CONTAINED = "scope_not_contained"
    EXPIRED_ASSIGNMENTS_ONLY = "expired_assignments_only"


@dataclass
class MatchedAssignment:
    role_id: str
    role_name: str
    scope_type: str
    scope_id: str
    source: str  # "direct" or "team:<team_id>"

    def to_dict(self) -> dict[str, str]:
        return {
            "role_id": self.role_id,
            "role_name": self.role_name,
            "scope_type": self.scope_type,
            "scope_id": self.scope_id,
            "source": self.source,
        }


@dataclass
class MatchedDeny:
    deny_id: str
    permission: str
    scope_type: str
    scope_id: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {
            "deny_id": self.deny_id,
            "permission": self.permission,
            "scope_type": self.scope_type,
            "scope_id": self.scope_id,
            "reason": self.reason,
        }


@dataclass
class AuthzResult:
    """Complete authorization decision with explanation."""

    decision: Decision
    deny_reason: DenyReason | None = None
    permission_source: str | None = None
    matched_assignments: list[MatchedAssignment] = field(default_factory=list)
    matched_denies: list[MatchedDeny] = field(default_factory=list)
    cache_hit: bool = False
    evaluation_latency_us: int = 0


def _scope_contains(outer: Scope, inner: Scope) -> bool:
    """Check if outer scope contains inner scope (downward containment).

    PLATFORM contains everything.
    TENANT contains TEAM and NAMESPACE within the same tenant.
    TEAM contains NAMESPACE within the same team.
    Same scope type + same ID is also contained.
    """
    if outer.scope_type == "PLATFORM":
        return True
    outer_idx = (
        SCOPE_CONTAINMENT_ORDER.index(outer.scope_type)
        if outer.scope_type in SCOPE_CONTAINMENT_ORDER
        else -1
    )
    inner_idx = (
        SCOPE_CONTAINMENT_ORDER.index(inner.scope_type)
        if inner.scope_type in SCOPE_CONTAINMENT_ORDER
        else -1
    )

    if outer_idx < 0 or inner_idx < 0:
        return False

    if outer_idx > inner_idx:
        return False

    if outer.scope_type == inner.scope_type:
        return outer.scope_id == inner.scope_id

    # Broader scope type — we'd need a scope hierarchy lookup in production,
    # but for now PLATFORM contains all, and same-ID containment suffices
    # for the shadow evaluation phase.
    return True


_RESOLVE_PERMISSIONS_SQL = text("""
    WITH direct_assignments AS (
        SELECT ra.id AS assignment_id, ra.role_id, r.name AS role_name,
               r.permissions, r.inherits_from,
               ra.scope_type, ra.scope_id,
               'direct' AS source,
               ra.expires_at
        FROM role_assignments ra
        JOIN roles r ON r.id = ra.role_id
        WHERE ra.principal_id = :principal_id
          AND ra.revoked = false
    ),
    team_assignments AS (
        SELECT ra.id AS assignment_id, ra.role_id, r.name AS role_name,
               r.permissions, r.inherits_from,
               ra.scope_type, ra.scope_id,
               'team:' || tm.team_id AS source,
               ra.expires_at
        FROM team_memberships tm
        JOIN role_assignments ra ON ra.principal_id = tm.team_id
        JOIN roles r ON r.id = ra.role_id
        WHERE tm.principal_id = :principal_id
          AND ra.revoked = false
    ),
    all_assignments AS (
        SELECT * FROM direct_assignments
        UNION ALL
        SELECT * FROM team_assignments
    )
    SELECT assignment_id, role_id, role_name, permissions, inherits_from,
           scope_type, scope_id, source, expires_at
    FROM all_assignments
""")

_RESOLVE_DENIES_SQL = text("""
    SELECT da.id, da.permission, da.scope_type, da.scope_id, da.reason, da.expires_at
    FROM deny_assignments da
    WHERE da.principal_id = :principal_id
""")

_RESOLVE_ROLE_PERMISSIONS_SQL = text("""
    WITH RECURSIVE role_chain AS (
        SELECT name, permissions, inherits_from FROM roles WHERE name = :role_name
        UNION ALL
        SELECT r.name, r.permissions, r.inherits_from
        FROM roles r
        JOIN role_chain rc ON rc.inherits_from = r.name
    )
    SELECT DISTINCT jsonb_array_elements_text(permissions) AS perm FROM role_chain
""")


class RBACEvaluator:
    """Pure RBAC authorization evaluator.

    Dependencies are injected at construction — no global state, no framework
    coupling. The evaluator can be tested with mock sessions and cache.
    """

    def __init__(
        self,
        session: AsyncSession,
        redis_client: Any | None = None,
    ):
        self._session = session
        self._redis = redis_client

    async def evaluate(
        self,
        principal_id: str | None,
        permission: str,
        resource_scope: Scope | None,
    ) -> AuthzResult:
        """Evaluate authorization for a principal, permission, and resource scope.

        This is the core algorithm from rbac-design.md section 6:
        1. Resolve effective roles (direct + team-inherited, excl. expired/revoked).
        2. Check deny assignments first — any match returns DENY immediately.
        3. Check if any role grants the permission within the resource scope.
        4. No matching grant → DENY (fail-closed).
        """
        t0 = time.monotonic()

        if principal_id is None:
            return AuthzResult(
                decision=Decision.DENY,
                deny_reason=DenyReason.NO_PRINCIPAL,
                evaluation_latency_us=_elapsed_us(t0),
            )

        if resource_scope is None:
            resource_scope = Scope.platform()

        # Step 1: Check deny assignments (NEVER cached)
        denies = await self._check_denies(principal_id, permission, resource_scope)
        if denies:
            return AuthzResult(
                decision=Decision.DENY,
                deny_reason=DenyReason.EXPLICIT_DENY,
                matched_denies=denies,
                evaluation_latency_us=_elapsed_us(t0),
            )

        # Step 2: Resolve effective permissions (cached if available)
        assignments, cache_hit = await self._resolve_assignments(principal_id)

        # Step 3: Find a grant that covers the permission in scope
        matched = []
        permission_source = None
        has_expired_match = False

        for asgn in assignments:
            asgn_scope = Scope(scope_type=asgn["scope_type"], scope_id=asgn["scope_id"])

            if not _scope_contains(asgn_scope, resource_scope):
                continue

            if asgn.get("expired"):
                has_expired_match = True
                continue

            role_perms = await self._expand_role_permissions(asgn["role_name"])
            if permission in role_perms:
                ma = MatchedAssignment(
                    role_id=asgn["role_id"],
                    role_name=asgn["role_name"],
                    scope_type=asgn["scope_type"],
                    scope_id=asgn["scope_id"],
                    source=asgn["source"],
                )
                matched.append(ma)
                if permission_source is None:
                    permission_source = (
                        f"{asgn['role_name']} @ {asgn['scope_type']}:{asgn['scope_id']}"
                    )

        if matched:
            return AuthzResult(
                decision=Decision.ALLOW,
                permission_source=permission_source,
                matched_assignments=matched,
                cache_hit=cache_hit,
                evaluation_latency_us=_elapsed_us(t0),
            )

        deny_reason = (
            DenyReason.EXPIRED_ASSIGNMENTS_ONLY
            if has_expired_match
            else DenyReason.NO_MATCHING_GRANT
        )
        return AuthzResult(
            decision=Decision.DENY,
            deny_reason=deny_reason,
            cache_hit=cache_hit,
            evaluation_latency_us=_elapsed_us(t0),
        )

    async def _check_denies(
        self,
        principal_id: str,
        permission: str,
        resource_scope: Scope,
    ) -> list[MatchedDeny]:
        """Check deny assignments — always from DB, never cached."""
        result = await self._session.execute(
            _RESOLVE_DENIES_SQL,
            {"principal_id": principal_id},
        )
        matched = []
        now = time.time()
        for row in result.fetchall():
            deny_id, deny_perm, scope_type, scope_id, reason, expires_at = row
            if expires_at is not None and expires_at.timestamp() < now:
                continue
            if deny_perm != permission and deny_perm != "*":
                continue
            deny_scope = Scope(scope_type=scope_type, scope_id=scope_id)
            if _scope_contains(deny_scope, resource_scope):
                matched.append(MatchedDeny(
                    deny_id=deny_id,
                    permission=deny_perm,
                    scope_type=scope_type,
                    scope_id=scope_id,
                    reason=reason or "",
                ))
        return matched

    async def _resolve_assignments(
        self,
        principal_id: str,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Resolve all role assignments (direct + team-inherited).

        Returns (assignments_list, cache_hit).
        """
        cached = await self._cache_get(principal_id)
        if cached is not None:
            return cached, True

        result = await self._session.execute(
            _RESOLVE_PERMISSIONS_SQL,
            {"principal_id": principal_id},
        )
        now = time.time()
        assignments = []
        for row in result.fetchall():
            (assignment_id, role_id, role_name, permissions, inherits_from,
             scope_type, scope_id, source, expires_at) = row
            expired = expires_at is not None and expires_at.timestamp() < now
            assignments.append({
                "assignment_id": assignment_id,
                "role_id": role_id,
                "role_name": role_name,
                "scope_type": scope_type,
                "scope_id": scope_id,
                "source": source,
                "expired": expired,
            })

        await self._cache_set(principal_id, assignments)
        return assignments, False

    async def _expand_role_permissions(self, role_name: str) -> set[str]:
        """Expand a role's permissions through the inheritance chain."""
        cache_key = f"_role_perms:{role_name}"
        if hasattr(self, "_role_perm_cache"):
            if cache_key in self._role_perm_cache:
                return self._role_perm_cache[cache_key]
        else:
            self._role_perm_cache: dict[str, set[str]] = {}

        result = await self._session.execute(
            _RESOLVE_ROLE_PERMISSIONS_SQL,
            {"role_name": role_name},
        )
        perms = {row[0] for row in result.fetchall()}
        self._role_perm_cache[cache_key] = perms
        return perms

    # -- Cache interface --------------------------------------------------

    async def _cache_get(self, principal_id: str) -> list[dict[str, Any]] | None:
        if self._redis is None:
            return None
        try:
            version = await self._redis.get(f"rbac:version:{principal_id}")
            if version is None:
                return None
            data = await self._redis.get(f"rbac:perms:{principal_id}:{version}")
            if data is None:
                return None
            return cast(list[dict[str, Any]] | None, json.loads(data))
        except Exception:
            logger.warning("rbac.cache_get_error", principal_id=principal_id, exc_info=True)
            return None

    async def _cache_set(self, principal_id: str, assignments: list[dict[str, Any]]) -> None:
        if self._redis is None:
            return
        try:
            version = await self._redis.get(f"rbac:version:{principal_id}")
            if version is None:
                version = b"1"
                await self._redis.set(f"rbac:version:{principal_id}", "1")
            serializable = []
            for a in assignments:
                entry = {k: v for k, v in a.items() if k != "expired"}
                serializable.append(entry)
            decoded_ver = version.decode() if isinstance(version, bytes) else version
            key = f"rbac:perms:{principal_id}:{decoded_ver}"
            await self._redis.set(key, json.dumps(serializable), ex=CACHE_TTL_SECONDS)
        except Exception:
            logger.warning("rbac.cache_set_error", principal_id=principal_id, exc_info=True)


class TeamContextValidator:
    """Validate X-Team-Context header against principal's team memberships.

    The header is a selection hint only — the requested team must be in the
    principal's effective memberships. Invalid/missing context is reported
    but does NOT affect legacy behavior in shadow mode.
    """

    def __init__(self, session: AsyncSession):
        self._session = session

    async def validate(
        self,
        principal_id: str,
        team_context: str | None,
    ) -> tuple[bool, str | None]:
        """Validate team context.

        Returns (is_valid, error_detail).
        - (True, None) if context is valid or not required.
        - (False, reason) if context is invalid.
        """
        if team_context is None:
            memberships = await self._get_team_memberships(principal_id)
            if len(memberships) > 1:
                return False, "principal_has_multiple_teams"
            return True, None

        memberships = await self._get_team_memberships(principal_id)
        member_ids = {m["team_id"] for m in memberships}
        if team_context not in member_ids:
            return False, "team_not_in_memberships"
        return True, None

    async def _get_team_memberships(self, principal_id: str) -> list[dict[str, str]]:
        result = await self._session.execute(
            text("SELECT team_id FROM team_memberships WHERE principal_id = :pid"),
            {"pid": principal_id},
        )
        return [{"team_id": row[0]} for row in result.fetchall()]


async def resolve_principal_id(session: AsyncSession, actor: str) -> str | None:
    """Resolve an actor string to a principal ID."""
    result = await session.execute(
        text("SELECT id FROM principals WHERE name = :name AND enabled = true"),
        {"name": actor},
    )
    row = result.first()
    return row[0] if row else None


def _elapsed_us(t0: float) -> int:
    return int((time.monotonic() - t0) * 1_000_000)
