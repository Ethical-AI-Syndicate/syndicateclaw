"""Background cleanup when an organization is in DELETING state."""

from __future__ import annotations

import structlog
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from syndicateclaw.db.models import (
    Agent,
    AgentMessage,
    MemoryRecord,
    Organization,
    WorkflowDefinition,
    WorkflowRun,
    WorkflowSchedule,
)

logger = structlog.get_logger(__name__)


async def run_org_cleanup_once(org_id: str) -> None:
    """When the org is DELETING and all runs are terminal, remove tenant data then mark DELETED."""
    from syndicateclaw.config import Settings
    from syndicateclaw.db.base import get_engine, get_session_factory

    settings = Settings()
    engine = get_engine(settings.database_url)
    session_factory: async_sessionmaker[AsyncSession] = get_session_factory(engine)
    async with session_factory() as session, session.begin():
        await _cleanup_with_session(session, org_id)


async def _cleanup_with_session(session: AsyncSession, org_id: str) -> None:
    org = await session.get(Organization, org_id)
    if org is None or org.status != "DELETING":
        return
    ns = org.namespace
    active = (
        await session.execute(
            text(
                """
                SELECT COUNT(*) FROM workflow_runs
                WHERE namespace = :ns AND status NOT IN ('COMPLETED','FAILED','CANCELLED')
                """
            ),
            {"ns": ns},
        )
    ).scalar()
    if int(active or 0) > 0:
        logger.info("org_cleanup.waiting_runs", org_id=org_id, active=active)
        return

    await session.execute(delete(WorkflowRun).where(WorkflowRun.namespace == ns))
    await session.execute(delete(WorkflowDefinition).where(WorkflowDefinition.namespace == ns))
    await session.execute(delete(Agent).where(Agent.namespace == ns))
    await session.execute(delete(MemoryRecord).where(MemoryRecord.namespace == ns))
    await session.execute(delete(AgentMessage).where(AgentMessage.namespace == ns))
    await session.execute(delete(WorkflowSchedule).where(WorkflowSchedule.namespace == ns))
    await session.execute(
        text("DELETE FROM organization_members WHERE organization_id = :oid"),
        {"oid": org_id},
    )
    await session.execute(
        text("DELETE FROM organization_quotas_usage WHERE organization_id = :oid"), {"oid": org_id}
    )
    org.status = "DELETED"
    await session.flush()
    logger.info("org_cleanup.completed", org_id=org_id)


async def run_org_cleanup_with_session(session: AsyncSession, org_id: str) -> None:
    """Entry point for tests and in-request cleanup (single transaction)."""
    await _cleanup_with_session(session, org_id)
