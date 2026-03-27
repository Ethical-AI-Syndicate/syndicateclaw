"""Organization CRUD, membership, quotas, and deletion lifecycle."""

from __future__ import annotations

import asyncio
import re
from typing import Any

import structlog
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from syndicateclaw.db.models import (
    Agent,
    MemoryRecord,
    Organization,
    WorkflowDefinition,
    WorkflowRun,
    WorkflowSchedule,
)

logger = structlog.get_logger(__name__)

DEFAULT_QUOTAS: dict[str, Any] = {
    "rate_limit_requests": 1000,
    "rate_limit_burst": 100,
    "max_agents": 50,
    "max_workflows": 200,
    "max_schedules": 100,
    "max_memory_records": 100000,
    "storage_limit_bytes": 10737418240,
}

_NS_RE = re.compile(r"[^a-z0-9\-]+")


def derive_namespace(name: str) -> str:
    s = name.lower().replace(" ", "-").replace("_", "-")
    return _NS_RE.sub("-", s).strip("-") or "org"


# Maps organization_members.rbac_role to coarse permission sets (merged with platform RBAC).
RBAC_ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "tenant_admin": frozenset({"admin:*", "org:manage", "org:read"}),
    "admin": frozenset({"org:manage", "org:read", "workflow:manage", "run:control"}),
    "operator": frozenset({"org:read", "workflow:create", "run:create", "run:read"}),
    "viewer": frozenset({"org:read", "workflow:read", "run:read"}),
}


class OrganizationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, org_id: str) -> Organization | None:
        return await self._session.get(Organization, org_id)

    async def get_actor_org(self, actor: str) -> Organization | None:
        chk = (
            await self._session.execute(
                text(
                    """
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = 'organization_members'
                    """
                )
            )
        ).first()
        if chk is None:
            return None
        row = (
            await self._session.execute(
                text(
                    """
                    SELECT o.id FROM organizations o
                    JOIN organization_members m ON m.organization_id = o.id
                    WHERE m.actor = :actor
                    LIMIT 1
                    """
                ),
                {"actor": actor},
            )
        ).first()
        if row is None:
            return None
        return await self.get_by_id(str(row[0]))

    async def resolve_actor_permissions(self, actor: str) -> set[str]:
        row = (
            await self._session.execute(
                text("SELECT rbac_role FROM organization_members WHERE actor = :actor LIMIT 1"),
                {"actor": actor},
            )
        ).first()
        perms: set[str] = set()
        if row is not None and row[0]:
            role = str(row[0])
            perms |= set(RBAC_ROLE_PERMISSIONS.get(role, frozenset()))
        return perms

    async def create_org(
        self,
        name: str,
        display_name: str,
        owner_actor: str,
        *,
        ulid_factory: type[ULID] = ULID,
    ) -> Organization:
        namespace = derive_namespace(name)
        org_id = str(ulid_factory())
        member_id = str(ulid_factory())
        org = Organization(
            id=org_id,
            name=name,
            display_name=display_name,
            owner_actor=owner_actor,
            namespace=namespace,
            status="ACTIVE",
            quotas=dict(DEFAULT_QUOTAS),
            settings={},
        )
        self._session.add(org)
        await self._session.flush()
        await self._session.execute(
            text(
                """
                INSERT INTO organization_quotas_usage
                    (organization_id, storage_bytes_used, updated_at)
                VALUES (:oid, 0, NOW())
                ON CONFLICT (organization_id) DO NOTHING
                """
            ),
            {"oid": org_id},
        )
        await self._session.execute(
            text(
                """
                INSERT INTO organization_members
                    (id, organization_id, actor, org_role, rbac_role, joined_at)
                VALUES
                    (:mid, :oid, :actor, 'OWNER', 'tenant_admin', NOW())
                """
            ),
            {"mid": member_id, "oid": org_id, "actor": owner_actor},
        )
        await self._session.flush()
        logger.info("organization.created", org_id=org_id, namespace=namespace)
        return org

    async def handle_org_deleting(self, org_id: str) -> None:
        org = await self.get_by_id(org_id)
        if org is None:
            return
        await self._session.execute(
            update(WorkflowSchedule)
            .where(
                WorkflowSchedule.namespace == org.namespace,
                WorkflowSchedule.status == "ACTIVE",
            )
            .values(status="PAUSED")
        )
        org.status = "DELETING"
        await self._session.flush()
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_run_org_cleanup_background(org_id))
        except RuntimeError:
            pass
        logger.info("organization.marked_deleting", org_id=org_id)


async def _run_org_cleanup_background(org_id: str) -> None:
    from syndicateclaw.tasks.org_cleanup import run_org_cleanup_once

    await run_org_cleanup_once(org_id)


async def count_workflows_for_org(session: AsyncSession, namespace: str) -> int:
    q = select(func.count()).select_from(WorkflowDefinition).where(
        WorkflowDefinition.namespace == namespace
    )
    return int((await session.execute(q)).scalar() or 0)


async def count_agents_for_org(session: AsyncSession, namespace: str) -> int:
    q = select(func.count()).select_from(Agent).where(Agent.namespace == namespace)
    return int((await session.execute(q)).scalar() or 0)


async def count_schedules_for_org(session: AsyncSession, namespace: str) -> int:
    q = select(func.count()).select_from(WorkflowSchedule).where(
        WorkflowSchedule.namespace == namespace
    )
    return int((await session.execute(q)).scalar() or 0)


async def count_memory_records_for_org(session: AsyncSession, namespace: str) -> int:
    q = select(func.count()).select_from(MemoryRecord).where(MemoryRecord.namespace == namespace)
    return int((await session.execute(q)).scalar() or 0)


async def get_storage_bytes_used(session: AsyncSession, org_id: str) -> int:
    row = (
        await session.execute(
            text(
                """
                SELECT storage_bytes_used FROM organization_quotas_usage
                WHERE organization_id = :oid
                """
            ),
            {"oid": org_id},
        )
    ).first()
    return int(row[0]) if row else 0


async def add_storage_bytes_used(session: AsyncSession, org_id: str, delta: int) -> None:
    await session.execute(
        text(
            """
            INSERT INTO organization_quotas_usage (organization_id, storage_bytes_used, updated_at)
            VALUES (:oid, :delta, NOW())
            ON CONFLICT (organization_id) DO UPDATE SET
              storage_bytes_used = organization_quotas_usage.storage_bytes_used + :delta,
              updated_at = NOW()
            """
        ),
        {"oid": org_id, "delta": delta},
    )


async def active_nonterminal_runs_for_namespace(session: AsyncSession, namespace: str) -> int:
    terminal = ("COMPLETED", "FAILED", "CANCELLED")
    q = (
        select(func.count())
        .select_from(WorkflowRun)
        .where(WorkflowRun.namespace == namespace, WorkflowRun.status.notin_(terminal))
    )
    return int((await session.execute(q)).scalar() or 0)
