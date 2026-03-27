from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from syndicateclaw.api.dependencies import (
    get_current_actor,
    get_message_service,
    get_subscription_service,
)
from syndicateclaw.services.agent_service import AgentOwnershipError
from syndicateclaw.services.message_service import (
    BroadcastCapExceededError,
    BroadcastPermissionDeniedError,
    MessageNotFoundError,
)

router = APIRouter(tags=["messages"])

DEP_CURRENT_ACTOR = Depends(get_current_actor)
DEP_MESSAGE_SERVICE = Depends(get_message_service)
DEP_SUBSCRIPTION_SERVICE = Depends(get_subscription_service)
Q_NAMESPACE = Query("default")
Q_TOPIC = Query(None)
Q_AGENT_ID = Query(None)


class SendMessageRequest(BaseModel):
    recipient: str | None = None
    topic: str | None = None
    message_type: str = "DIRECT"
    content: dict[str, Any] = Field(default_factory=dict)
    sender: str | None = None
    namespace: str = "default"
    priority: str = "NORMAL"
    ttl_seconds: int = 3600


class ReplyMessageRequest(BaseModel):
    content: dict[str, Any] = Field(default_factory=dict)
    message_type: str = "RESPONSE"


class MessageResponse(BaseModel):
    model_config = {"from_attributes": True, "populate_by_name": True}

    id: str
    conversation_id: str
    sender: str
    recipient: str | None
    topic: str | None
    message_type: str
    content: dict[str, Any]
    metadata: dict[str, Any] = Field(alias="metadata_")
    priority: str
    status: str
    ttl_seconds: int
    hop_count: int
    parent_message_id: str | None
    expires_at: datetime | None
    delivered_at: datetime | None
    acked_at: datetime | None
    created_at: datetime
    updated_at: datetime


@router.post(
    "/api/v1/messages",
    response_model=list[MessageResponse],
    status_code=status.HTTP_201_CREATED,
)
async def send_message(
    body: SendMessageRequest,
    actor: str = DEP_CURRENT_ACTOR,
    message_service: Any = DEP_MESSAGE_SERVICE,
) -> list[Any]:
    try:
        rows = await message_service.send(
            actor=actor,
            namespace=body.namespace,
            message_type=body.message_type,
            content=body.content,
            submitted_sender=body.sender,
            recipient=body.recipient,
            topic=body.topic,
            priority=body.priority,
            ttl_seconds=body.ttl_seconds,
        )
        return list(rows)
    except BroadcastPermissionDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except BroadcastCapExceededError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/api/v1/messages", response_model=list[MessageResponse])
async def list_messages(
    actor: str = DEP_CURRENT_ACTOR,
    message_service: Any = DEP_MESSAGE_SERVICE,
) -> list[Any]:
    rows = await message_service.list_for_actor(actor)
    return list(rows)


@router.get("/api/v1/messages/{message_id}", response_model=MessageResponse)
async def get_message(
    message_id: str,
    actor: str = DEP_CURRENT_ACTOR,
    message_service: Any = DEP_MESSAGE_SERVICE,
) -> Any:
    try:
        return await message_service.get_for_actor(actor, message_id)
    except MessageNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/api/v1/messages/{message_id}/ack", response_model=MessageResponse)
async def ack_message(
    message_id: str,
    actor: str = DEP_CURRENT_ACTOR,
    message_service: Any = DEP_MESSAGE_SERVICE,
) -> Any:
    try:
        return await message_service.ack(actor, message_id)
    except MessageNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/api/v1/messages/{message_id}/reply", response_model=list[MessageResponse])
async def reply_message(
    message_id: str,
    body: ReplyMessageRequest,
    actor: str = DEP_CURRENT_ACTOR,
    message_service: Any = DEP_MESSAGE_SERVICE,
) -> list[Any]:
    try:
        rows = await message_service.reply(
            actor=actor,
            message_id=message_id,
            content=body.content,
            message_type=body.message_type,
        )
        return list(rows)
    except MessageNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/api/v1/topics/{topic}/subscribe")
async def subscribe_topic(
    topic: str,
    namespace: str = Q_NAMESPACE,
    agent_id: str | None = Q_AGENT_ID,
    actor: str = DEP_CURRENT_ACTOR,
    subscription_service: Any = DEP_SUBSCRIPTION_SERVICE,
) -> dict[str, str]:
    if agent_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="agent_id is required")
    try:
        await subscription_service.subscribe(agent_id, topic, namespace, actor)
    except AgentOwnershipError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return {"status": "subscribed", "topic": topic, "agent_id": agent_id}


@router.delete("/api/v1/topics/{topic}/subscribe")
async def unsubscribe_topic(
    topic: str,
    agent_id: str | None = Q_AGENT_ID,
    actor: str = DEP_CURRENT_ACTOR,
    subscription_service: Any = DEP_SUBSCRIPTION_SERVICE,
) -> dict[str, str]:
    if agent_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="agent_id is required")
    try:
        await subscription_service.unsubscribe(agent_id, topic, actor)
    except AgentOwnershipError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return {"status": "unsubscribed", "topic": topic, "agent_id": agent_id}


@router.get("/api/v1/topics")
async def list_topics(
    namespace: str = Q_NAMESPACE,
    actor: str = DEP_CURRENT_ACTOR,
    subscription_service: Any = DEP_SUBSCRIPTION_SERVICE,
) -> dict[str, Any]:
    _ = actor
    topics = await subscription_service.list_topics(namespace)
    return {"topics": topics, "count": len(topics)}
