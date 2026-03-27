from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from syndicateclaw.authz.evaluator import Decision, RBACEvaluator, resolve_principal_id
from syndicateclaw.authz.route_registry import Scope
from syndicateclaw.db.models import AgentMessage
from syndicateclaw.messaging.router import HopLimitExceededError, MessageRouter
from syndicateclaw.services.agent_service import AgentService
from syndicateclaw.services.subscription_service import SubscriptionService

logger = structlog.get_logger(__name__)


class BroadcastPermissionDeniedError(Exception):
    """Raised when actor lacks message:broadcast permission."""


class BroadcastCapExceededError(Exception):
    """Raised when broadcast subscriber cap is exceeded."""


class MessageNotFoundError(Exception):
    """Raised when a message cannot be found for actor."""


class MessageService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        agent_service: AgentService,
        subscription_service: SubscriptionService,
        router: MessageRouter,
        redis_client: Any | None,
    ) -> None:
        self._session_factory = session_factory
        self._agent_service = agent_service
        self._subscription_service = subscription_service
        self._router = router
        self._redis = redis_client

    async def _actor_has_permission(self, actor: str, permission: str) -> bool:
        async with self._session_factory() as session:
            principal_id = await resolve_principal_id(session, actor)
            evaluator = RBACEvaluator(session, redis_client=None)
            result = await evaluator.evaluate(
                principal_id=principal_id,
                permission=permission,
                resource_scope=Scope.platform(),
            )
            return result.decision == Decision.ALLOW

    async def _enforce_broadcast_rate_limit(self, actor: str) -> None:
        if self._redis is None:
            return
        now = time.time()
        key = f"syndicateclaw:message:broadcast:{actor}"
        pipe = self._redis.pipeline(transaction=True)
        cutoff = now - 60.0
        pipe.zremrangebyscore(key, "-inf", cutoff)
        pipe.zadd(key, {str(now): now})
        pipe.zcard(key)
        pipe.expire(key, 61)
        res = await pipe.execute()
        count = int(res[2])
        if count > 10:
            raise BroadcastPermissionDeniedError("broadcast rate limit exceeded")

    async def _resolve_recipient_id(self, recipient: str, namespace: str) -> str:
        if len(recipient) == 26 and recipient.isalnum() and recipient.upper() == recipient:
            return recipient
        agent = await self._agent_service.get_by_name(recipient, namespace)
        logger.warning(
            "message.name_routing_used",
            recipient_name=recipient,
            resolved_id=agent.id,
        )
        return agent.id

    async def send(
        self,
        *,
        actor: str,
        namespace: str,
        message_type: str,
        content: dict[str, Any],
        submitted_sender: str | None = None,
        recipient: str | None = None,
        topic: str | None = None,
        priority: str = "NORMAL",
        ttl_seconds: int = 3600,
        conversation_id: str | None = None,
        hop_count: int = 0,
        parent_message_id: str | None = None,
    ) -> list[AgentMessage]:
        sender = actor
        if submitted_sender is not None and submitted_sender != actor:
            logger.warning(
                "message.sender_override",
                actor=actor,
                submitted_sender=submitted_sender,
            )

        expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds)

        if message_type == "BROADCAST":
            if not await self._actor_has_permission(actor, "message:broadcast"):
                raise BroadcastPermissionDeniedError("message:broadcast permission required")
            await self._enforce_broadcast_rate_limit(actor)
            subscribers = await self._subscription_service.get_subscribers(
                "__broadcast__",
                namespace,
            )
            if len(subscribers) > 50:
                raise BroadcastCapExceededError("broadcast subscriber cap exceeded")

            rows: list[AgentMessage] = []
            async with self._session_factory() as session, session.begin():
                for sub in subscribers:
                    row = AgentMessage(
                        conversation_id=conversation_id or "",
                        sender=sender,
                        recipient=sub.id,
                        topic="__broadcast__",
                        message_type=message_type,
                        content=content,
                        namespace=namespace,
                        metadata_={"namespace": namespace},
                        priority=priority,
                        status="PENDING",
                        ttl_seconds=ttl_seconds,
                        hop_count=hop_count,
                        parent_message_id=parent_message_id,
                        expires_at=expires_at,
                    )
                    session.add(row)
                    await session.flush()
                    await self._router.route(row)
                    rows.append(row)
                for row in rows:
                    row.status = "DELIVERED"
            return rows

        recipient_id = None
        if recipient is not None:
            recipient_id = await self._resolve_recipient_id(recipient, namespace)

        async with self._session_factory() as session, session.begin():
            row = AgentMessage(
                conversation_id=conversation_id or "",
                sender=sender,
                recipient=recipient_id,
                topic=topic,
                message_type=message_type,
                content=content,
                namespace=namespace,
                metadata_={"namespace": namespace},
                priority=priority,
                status="PENDING",
                ttl_seconds=ttl_seconds,
                hop_count=hop_count,
                parent_message_id=parent_message_id,
                expires_at=expires_at,
            )
            session.add(row)
            await session.flush()
            await self._router.route(row)
            row.status = "DELIVERED" if recipient_id or topic else "PENDING"
            await session.flush()
            return [row]

    async def list_for_actor(self, actor: str, *, limit: int = 100) -> list[AgentMessage]:
        stmt: Select[tuple[AgentMessage]] = (
            select(AgentMessage)
            .where((AgentMessage.sender == actor) | (AgentMessage.recipient == actor))
            .order_by(AgentMessage.created_at.desc())
            .limit(limit)
        )
        async with self._session_factory() as session:
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_for_actor(self, actor: str, message_id: str) -> AgentMessage:
        async with self._session_factory() as session:
            row = await session.get(AgentMessage, message_id)
            if row is None:
                raise MessageNotFoundError("message not found")
            if row.sender != actor and row.recipient != actor:
                raise MessageNotFoundError("message not found")
            return row

    async def ack(self, actor: str, message_id: str) -> AgentMessage:
        async with self._session_factory() as session, session.begin():
            row = await session.get(AgentMessage, message_id)
            if row is None or row.recipient != actor:
                raise MessageNotFoundError("message not found")
            row.status = "ACKED"
            row.acked_at = datetime.now(UTC)
            await session.flush()
            return row

    async def reply(
        self,
        *,
        actor: str,
        message_id: str,
        content: dict[str, Any],
        message_type: str = "RESPONSE",
    ) -> list[AgentMessage]:
        parent = await self.get_for_actor(actor, message_id)
        recipient = parent.sender
        conversation_id = parent.conversation_id
        return await self.send(
            actor=actor,
            namespace=str(parent.metadata_.get("namespace", "default")),
            message_type=message_type,
            content=content,
            recipient=recipient,
            conversation_id=conversation_id,
            hop_count=parent.hop_count + 1,
            parent_message_id=parent.id,
        )

    async def pending_messages(self, *, limit: int = 100) -> list[AgentMessage]:
        stmt: Select[tuple[AgentMessage]] = (
            select(AgentMessage)
            .where(
                AgentMessage.status == "PENDING",
                AgentMessage.expires_at > datetime.now(UTC),
            )
            .order_by(AgentMessage.created_at.asc())
            .limit(limit)
        )
        async with self._session_factory() as session:
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def delivered_responses(self, *, limit: int = 200) -> list[AgentMessage]:
        stmt: Select[tuple[AgentMessage]] = (
            select(AgentMessage)
            .where(
                AgentMessage.message_type == "RESPONSE",
                AgentMessage.status == "DELIVERED",
                AgentMessage.expires_at > datetime.now(UTC),
            )
            .order_by(AgentMessage.created_at.asc())
            .limit(limit)
        )
        async with self._session_factory() as session:
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def mark_delivery_failed(self, message_id: str) -> None:
        async with self._session_factory() as session, session.begin():
            row = await session.get(AgentMessage, message_id)
            if row is None:
                return
            row.status = "FAILED"

    async def mark_delivered(self, message_id: str) -> None:
        async with self._session_factory() as session, session.begin():
            row = await session.get(AgentMessage, message_id)
            if row is None:
                return
            row.status = "DELIVERED"
            row.delivered_at = datetime.now(UTC)

    async def mark_response_consumed(self, message_id: str) -> None:
        async with self._session_factory() as session, session.begin():
            row = await session.get(AgentMessage, message_id)
            if row is None:
                return
            row.status = "ACKED"
            row.acked_at = datetime.now(UTC)

    async def relay(self, message: AgentMessage) -> list[AgentMessage]:
        payload = self._router.relay_payload(message)
        payload_namespace = str(message.metadata_.get("namespace", "default"))
        try:
            return await self.send(
                actor=message.sender,
                namespace=payload_namespace,
                message_type=message.message_type,
                content=message.content,
                recipient=message.recipient,
                topic=message.topic,
                priority=message.priority,
                ttl_seconds=message.ttl_seconds,
                conversation_id=message.conversation_id,
                hop_count=int(payload["hop_count"]),
                parent_message_id=message.id,
            )
        except HopLimitExceededError:
            raise
