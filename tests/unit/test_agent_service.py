from __future__ import annotations

import typing
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from syndicateclaw.db.models import Agent
from syndicateclaw.services.agent_service import (
    AgentConflictError,
    AgentOwnershipError,
    AgentService,
)


@pytest.fixture()
async def engine(db_engine: AsyncEngine) -> typing.AsyncGenerator[AsyncEngine, None]:
    yield db_engine


@pytest.fixture()
async def agent_service(engine: AsyncEngine) -> AgentService:
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session, session.begin():
        await session.execute(delete(Agent))
    return AgentService(session_factory, heartbeat_timeout_seconds=60)


@pytest.mark.asyncio
async def test_register_agent(agent_service: AgentService) -> None:
    agent = await agent_service.register(
        name=f"agent-register-{datetime.now(UTC).timestamp()}",
        capabilities=["search"],
        namespace="default",
        metadata={"team": "ops"},
        actor="owner-a",
    )
    assert agent.status == "OFFLINE"
    assert agent.registered_by == "owner-a"


@pytest.mark.asyncio
async def test_duplicate_name_rejected(agent_service: AgentService) -> None:
    name = f"agent-dup-{datetime.now(UTC).timestamp()}"
    await agent_service.register(
        name=name,
        capabilities=["search"],
        namespace="same-ns",
        metadata={},
        actor="owner-a",
    )
    with pytest.raises(AgentConflictError):
        await agent_service.register(
            name=name,
            capabilities=["search"],
            namespace="same-ns",
            metadata={},
            actor="owner-b",
        )


@pytest.mark.asyncio
async def test_heartbeat_updates_status(agent_service: AgentService) -> None:
    agent = await agent_service.register(
        name=f"agent-heartbeat-{datetime.now(UTC).timestamp()}",
        capabilities=["ingest"],
        namespace="default",
        metadata={},
        actor="owner-a",
    )
    updated = await agent_service.heartbeat(agent.id, "owner-a")
    assert updated.status == "ONLINE"
    assert updated.heartbeat_at is not None


@pytest.mark.asyncio
async def test_heartbeat_requires_ownership(agent_service: AgentService) -> None:
    agent = await agent_service.register(
        name=f"agent-owner-{datetime.now(UTC).timestamp()}",
        capabilities=["ingest"],
        namespace="default",
        metadata={},
        actor="owner-a",
    )
    with pytest.raises(AgentOwnershipError):
        await agent_service.heartbeat(agent.id, "owner-b")


@pytest.mark.asyncio
async def test_stale_heartbeat_marks_offline(agent_service: AgentService) -> None:
    agent = await agent_service.register(
        name=f"agent-stale-{datetime.now(UTC).timestamp()}",
        capabilities=["ingest"],
        namespace="default",
        metadata={},
        actor="owner-a",
    )
    await agent_service.heartbeat(agent.id, "owner-a")

    stale_at = datetime.now(UTC) - timedelta(seconds=120)
    async with agent_service._session_factory() as session, session.begin():  # noqa: SLF001
        row = await session.get(Agent, agent.id)
        assert row is not None
        row.status = "ONLINE"
        row.heartbeat_at = stale_at

    updated_count = await agent_service.transition_stale_to_offline()
    assert updated_count >= 1

    refreshed = await agent_service.get(agent.id)
    assert refreshed.status == "OFFLINE"


@pytest.mark.asyncio
async def test_discover_by_capability(agent_service: AgentService) -> None:
    await agent_service.register(
        name=f"agent-cap-a-{datetime.now(UTC).timestamp()}",
        capabilities=["search"],
        namespace="cap-ns",
        metadata={},
        actor="owner-a",
    )
    await agent_service.register(
        name=f"agent-cap-b-{datetime.now(UTC).timestamp()}",
        capabilities=["compute"],
        namespace="cap-ns",
        metadata={},
        actor="owner-b",
    )

    rows = await agent_service.discover(namespace="cap-ns", capability="search")
    assert rows
    assert all("search" in row.capabilities for row in rows)


@pytest.mark.asyncio
async def test_unauthorized_agent_update(agent_service: AgentService) -> None:
    agent = await agent_service.register(
        name=f"agent-update-{datetime.now(UTC).timestamp()}",
        capabilities=["search"],
        namespace="default",
        metadata={},
        actor="owner-a",
    )
    with pytest.raises(AgentOwnershipError):
        await agent_service.update(agent.id, "owner-b", description="new")
