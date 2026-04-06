from __future__ import annotations

from sqlalchemy import Select, delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from syndicateclaw.db.models import Agent, TopicSubscription
from syndicateclaw.services.agent_service import (
    AgentNotFoundError,
    AgentOwnershipError,
    AgentService,
)


class SubscriptionService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        agent_service: AgentService,
    ) -> None:
        self._session_factory = session_factory
        self._agent_service = agent_service

    async def _ensure_owner_or_admin(self, agent: Agent, actor: str) -> None:
        if agent.registered_by == actor:
            return
        if await self._agent_service.actor_has_admin_permission(actor):
            return
        raise AgentOwnershipError("Actor does not own this agent")

    async def subscribe(
        self,
        agent_id: str,
        topic: str,
        namespace: str,
        actor: str,
    ) -> TopicSubscription:
        agent = await self._agent_service.get(agent_id)
        await self._ensure_owner_or_admin(agent, actor)
        async with self._session_factory() as session, session.begin():
            existing = await session.execute(
                select(TopicSubscription).where(
                    TopicSubscription.agent_id == agent_id,
                    TopicSubscription.topic == topic,
                )
            )
            sub = existing.scalar_one_or_none()
            if sub is None:
                sub = TopicSubscription(agent_id=agent_id, topic=topic, namespace=namespace)
                session.add(sub)
                await session.flush()
            return sub

    async def unsubscribe(self, agent_id: str, topic: str, actor: str) -> None:
        agent = await self._agent_service.get(agent_id)
        await self._ensure_owner_or_admin(agent, actor)
        async with self._session_factory() as session, session.begin():
            await session.execute(
                delete(TopicSubscription).where(
                    TopicSubscription.agent_id == agent_id,
                    TopicSubscription.topic == topic,
                )
            )

    async def get_subscribers(self, topic: str, namespace: str) -> list[Agent]:
        stmt: Select[tuple[Agent]] = (
            select(Agent)
            .join(TopicSubscription, TopicSubscription.agent_id == Agent.id)
            .where(
                TopicSubscription.topic == topic,
                TopicSubscription.namespace == namespace,
                Agent.status == "ONLINE",
            )
            .order_by(Agent.created_at.asc())
        )
        async with self._session_factory() as session:
            rows = await session.execute(stmt)
            return list(rows.scalars().all())

    async def list_topics(self, namespace: str) -> list[str]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(TopicSubscription.topic)
                .where(TopicSubscription.namespace == namespace)
                .distinct()
                .order_by(TopicSubscription.topic.asc())
            )
            return [str(topic) for topic in result.scalars().all()]

    async def get_agent_or_404(self, agent_id: str) -> Agent:
        try:
            return await self._agent_service.get(agent_id)
        except AgentNotFoundError as exc:
            raise AgentNotFoundError("Agent not found") from exc
