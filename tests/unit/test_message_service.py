from __future__ import annotations

import os

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from syndicateclaw.db.models import Agent, AgentMessage, DeadLetterRecord, TopicSubscription
from syndicateclaw.messaging.router import HopLimitExceededError, MessageRouter
from syndicateclaw.services.agent_service import AgentService
from syndicateclaw.services.message_service import (
    BroadcastCapExceededError,
    BroadcastPermissionDeniedError,
    MessageService,
)
from syndicateclaw.services.subscription_service import SubscriptionService


@pytest.fixture()
async def engine() -> AsyncEngine:
    url = os.environ.get(
        "SYNDICATECLAW_DATABASE_URL",
        "postgresql+asyncpg://syndicateclaw:syndicateclaw@127.0.0.1:5432/syndicateclaw_test",
    )
    db_engine = create_async_engine(url)
    try:
        yield db_engine
    finally:
        await db_engine.dispose()


@pytest.fixture()
async def message_service(engine: AsyncEngine) -> MessageService:
    sf = async_sessionmaker(engine, expire_on_commit=False)
    async with sf() as session, session.begin():
        await session.execute(delete(AgentMessage))
        await session.execute(delete(TopicSubscription))
        await session.execute(delete(Agent))
        await session.execute(delete(DeadLetterRecord))

    agent_service = AgentService(sf)
    subscription_service = SubscriptionService(sf, agent_service=agent_service)
    router = MessageRouter(sf, max_hops=10)
    return MessageService(
        sf,
        agent_service=agent_service,
        subscription_service=subscription_service,
        router=router,
        redis_client=None,
    )


async def _register_agent(
    message_service: MessageService,
    name: str,
    owner: str,
    *,
    online: bool = True,
) -> Agent:
    agent = await message_service._agent_service.register(  # noqa: SLF001
        name=name,
        capabilities=["chat"],
        namespace="default",
        metadata={},
        actor=owner,
    )
    if online:
        await message_service._agent_service.heartbeat(agent.id, owner)  # noqa: SLF001
    return agent


@pytest.mark.asyncio
async def test_send_direct_message_sender_enforced(message_service: MessageService) -> None:
    recipient = await _register_agent(message_service, "receiver-a", "owner-a")

    rows = await message_service.send(
        actor="owner-a",
        namespace="default",
        message_type="DIRECT",
        content={"body": "hello"},
        recipient=recipient.id,
        submitted_sender="fake",
    )

    assert len(rows) == 1
    assert rows[0].sender == "owner-a"


@pytest.mark.asyncio
async def test_broadcast_requires_permission(message_service: MessageService) -> None:
    with pytest.raises(BroadcastPermissionDeniedError):
        await message_service.send(
            actor="member-actor",
            namespace="default",
            message_type="BROADCAST",
            content={"body": "all"},
        )


@pytest.mark.asyncio
async def test_broadcast_recipient_cap(
    message_service: MessageService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _allow(*_args: object, **_kwargs: object) -> bool:
        return True

    monkeypatch.setattr(message_service, "_actor_has_permission", _allow)

    for i in range(51):
        agent = await _register_agent(message_service, f"agent-{i}", "owner-a")
        await message_service._subscription_service.subscribe(  # noqa: SLF001
            agent.id,
            "__broadcast__",
            "default",
            "owner-a",
        )

    with pytest.raises(BroadcastCapExceededError):
        await message_service.send(
            actor="owner-a",
            namespace="default",
            message_type="BROADCAST",
            content={"body": "all"},
        )


@pytest.mark.asyncio
async def test_topic_subscription(
    message_service: MessageService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _allow(*_args: object, **_kwargs: object) -> bool:
        return True

    monkeypatch.setattr(message_service, "_actor_has_permission", _allow)

    subscribed = await _register_agent(message_service, "subscribed", "owner-a")
    await _register_agent(message_service, "not-subscribed", "owner-a")

    await message_service._subscription_service.subscribe(  # noqa: SLF001
        subscribed.id,
        "__broadcast__",
        "default",
        "owner-a",
    )

    rows = await message_service.send(
        actor="owner-a",
        namespace="default",
        message_type="BROADCAST",
        content={"body": "hello world"},
    )
    assert len(rows) == 1
    assert rows[0].recipient == subscribed.id


@pytest.mark.asyncio
async def test_hop_limit_enforced(message_service: MessageService) -> None:
    recipient = await _register_agent(message_service, "receiver-hop", "owner-a")

    with pytest.raises(HopLimitExceededError):
        await message_service.send(
            actor="owner-a",
            namespace="default",
            message_type="DIRECT",
            content={"body": "relay"},
            recipient=recipient.id,
            hop_count=10,
        )

    sf = message_service._session_factory  # noqa: SLF001
    async with sf() as session:
        result = await session.execute(select(DeadLetterRecord))
        rows = list(result.scalars().all())
        assert rows
        assert rows[0].event_type == "agent_message"


@pytest.mark.asyncio
async def test_circular_loop_terminated(message_service: MessageService) -> None:
    agent_a = await _register_agent(message_service, "agent-a", "owner-a")
    agent_b = await _register_agent(message_service, "agent-b", "owner-b")

    message = (
        await message_service.send(
            actor="owner-a",
            namespace="default",
            message_type="RELAY",
            content={"payload": "x"},
            recipient=agent_b.id,
            hop_count=9,
        )
    )[0]

    with pytest.raises(HopLimitExceededError):
        await message_service.send(
            actor="owner-b",
            namespace="default",
            message_type="RELAY",
            content=message.content,
            recipient=agent_a.id,
            hop_count=10,
            parent_message_id=message.id,
            conversation_id=message.conversation_id,
        )


@pytest.mark.asyncio
async def test_message_name_resolution_warns(message_service: MessageService) -> None:
    await _register_agent(message_service, "named-agent", "owner-a")
    rows = await message_service.send(
        actor="owner-a",
        namespace="default",
        message_type="DIRECT",
        content={"body": "name route"},
        recipient="named-agent",
    )
    assert rows[0].recipient is not None


@pytest.mark.asyncio
async def test_subscription_list_topics(message_service: MessageService) -> None:
    agent = await _register_agent(message_service, "topic-agent", "owner-a")
    await message_service._subscription_service.subscribe(  # noqa: SLF001
        agent.id,
        "topic.alpha",
        "default",
        "owner-a",
    )
    topics = await message_service._subscription_service.list_topics("default")  # noqa: SLF001
    assert "topic.alpha" in topics
