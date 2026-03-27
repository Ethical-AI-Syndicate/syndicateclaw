from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Select, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from syndicateclaw.authz.evaluator import Decision, RBACEvaluator, resolve_principal_id
from syndicateclaw.authz.route_registry import Scope
from syndicateclaw.db.models import Agent


class AgentNotFoundError(Exception):
    """Raised when the requested agent record does not exist."""


class AgentOwnershipError(Exception):
    """Raised when actor is neither owner nor agent admin."""


class AgentConflictError(Exception):
    """Raised on name+namespace uniqueness collisions."""


class AgentService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        heartbeat_timeout_seconds: int = 60,
    ) -> None:
        self._session_factory = session_factory
        self._heartbeat_timeout_seconds = heartbeat_timeout_seconds

    def _validate_metadata(self, metadata: dict[str, Any]) -> None:
        if len(metadata) > 64:
            raise ValueError("metadata supports at most 64 keys")
        encoded = json.dumps(metadata, separators=(",", ":")).encode("utf-8")
        if len(encoded) > 1024:
            raise ValueError("metadata payload must not exceed 1KB")

    async def register(
        self,
        *,
        name: str,
        capabilities: list[str],
        namespace: str,
        metadata: dict[str, Any],
        actor: str,
        description: str | None = None,
    ) -> Agent:
        self._validate_metadata(metadata)
        agent = Agent(
            name=name,
            description=description,
            namespace=namespace,
            capabilities=capabilities,
            metadata_=metadata,
            status="OFFLINE",
            registered_by=actor,
        )
        try:
            async with self._session_factory() as session, session.begin():
                session.add(agent)
                await session.flush()
                await session.refresh(agent)
        except IntegrityError as exc:
            raise AgentConflictError("agent name is already registered in this namespace") from exc
        return agent

    async def get(self, agent_id: str) -> Agent:
        async with self._session_factory() as session:
            agent = await session.get(Agent, agent_id)
            if agent is None:
                raise AgentNotFoundError("Agent not found")
            return agent

    async def get_by_name(self, name: str, namespace: str) -> Agent:
        async with self._session_factory() as session:
            result = await session.execute(
                select(Agent).where(Agent.name == name, Agent.namespace == namespace)
            )
            agent = result.scalar_one_or_none()
            if agent is None:
                raise AgentNotFoundError("Agent not found")
            return agent

    async def _actor_has_admin_permission(self, session: AsyncSession, actor: str) -> bool:
        principal_id = await resolve_principal_id(session, actor)
        evaluator = RBACEvaluator(session, redis_client=None)
        decision = await evaluator.evaluate(
            principal_id=principal_id,
            permission="agent:admin",
            resource_scope=Scope.platform(),
        )
        return decision.decision == Decision.ALLOW

    async def actor_has_admin_permission(self, actor: str) -> bool:
        async with self._session_factory() as session:
            return await self._actor_has_admin_permission(session, actor)

    async def _load_with_ownership(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        actor: str,
    ) -> Agent:
        agent = await session.get(Agent, agent_id)
        if agent is None:
            raise AgentNotFoundError("Agent not found")
        if agent.registered_by == actor:
            return agent
        if await self._actor_has_admin_permission(session, actor):
            return agent
        raise AgentOwnershipError("Actor does not own this agent")

    async def heartbeat(self, agent_id: str, actor: str) -> Agent:
        async with self._session_factory() as session, session.begin():
            agent = await self._load_with_ownership(session, agent_id=agent_id, actor=actor)
            agent.status = "ONLINE"
            agent.heartbeat_at = datetime.now(UTC)
            agent.deregistered_at = None
            await session.flush()
            await session.refresh(agent)
            return agent

    async def update(
        self,
        agent_id: str,
        actor: str,
        *,
        name: str | None = None,
        capabilities: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        description: str | None = None,
    ) -> Agent:
        if metadata is not None:
            self._validate_metadata(metadata)

        try:
            async with self._session_factory() as session, session.begin():
                agent = await self._load_with_ownership(session, agent_id=agent_id, actor=actor)
                if name is not None:
                    agent.name = name
                if capabilities is not None:
                    agent.capabilities = capabilities
                if metadata is not None:
                    agent.metadata_ = metadata
                if description is not None:
                    agent.description = description
                await session.flush()
                await session.refresh(agent)
                return agent
        except IntegrityError as exc:
            raise AgentConflictError("agent name is already registered in this namespace") from exc

    async def deregister(self, agent_id: str, actor: str) -> Agent:
        async with self._session_factory() as session, session.begin():
            agent = await self._load_with_ownership(session, agent_id=agent_id, actor=actor)
            agent.status = "OFFLINE"
            agent.deregistered_at = datetime.now(UTC)
            await session.flush()
            await session.refresh(agent)
            return agent

    async def transition_stale_to_offline(self) -> int:
        cutoff = datetime.now(UTC) - timedelta(seconds=self._heartbeat_timeout_seconds)
        async with self._session_factory() as session, session.begin():
            result = await session.execute(
                update(Agent)
                .where(
                    Agent.status == "ONLINE",
                    Agent.heartbeat_at.is_not(None),
                    Agent.heartbeat_at < cutoff,
                )
                .values(status="OFFLINE")
            )
            return int(result.rowcount or 0)

    async def discover(
        self,
        *,
        namespace: str | None = None,
        capability: str | None = None,
        status: str | None = None,
        name: str | None = None,
    ) -> list[Agent]:
        stmt: Select[tuple[Agent]] = select(Agent)
        if namespace is not None:
            stmt = stmt.where(Agent.namespace == namespace)
        if status is not None:
            stmt = stmt.where(Agent.status == status)
        if name is not None:
            stmt = stmt.where(Agent.name == name)
        if capability is not None:
            stmt = stmt.where(Agent.capabilities.contains([capability]))
        stmt = stmt.order_by(Agent.created_at.desc())
        async with self._session_factory() as session:
            rows = await session.execute(stmt)
            return list(rows.scalars().all())
