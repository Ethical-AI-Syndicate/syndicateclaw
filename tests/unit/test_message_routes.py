from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from syndicateclaw.api.dependencies import (
    get_current_actor,
    get_message_service,
    get_subscription_service,
)
from syndicateclaw.api.routes.messages import router
from syndicateclaw.services.message_service import (
    BroadcastPermissionDeniedError,
    MessageNotFoundError,
)


class _MessageServiceStub:
    async def send(self, **kwargs: Any) -> list[dict[str, Any]]:
        if kwargs.get("message_type") == "BROADCAST":
            raise BroadcastPermissionDeniedError("message:broadcast permission required")
        return [
            {
                "id": "01TESTMESSAGE00000000000000",
                "conversation_id": "conv-1",
                "sender": kwargs["actor"],
                "recipient": kwargs.get("recipient"),
                "topic": kwargs.get("topic"),
                "message_type": kwargs["message_type"],
                "content": kwargs["content"],
                "metadata_": {"namespace": kwargs["namespace"]},
                "priority": kwargs.get("priority", "NORMAL"),
                "status": "DELIVERED",
                "ttl_seconds": kwargs.get("ttl_seconds", 3600),
                "hop_count": kwargs.get("hop_count", 0),
                "parent_message_id": kwargs.get("parent_message_id"),
                "expires_at": datetime.now(UTC),
                "delivered_at": datetime.now(UTC),
                "acked_at": None,
                "created_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
            }
        ]

    async def list_for_actor(self, actor: str) -> list[dict[str, Any]]:
        _ = actor
        return []

    async def get_for_actor(self, actor: str, message_id: str) -> dict[str, Any]:
        _ = actor
        if message_id == "missing":
            raise MessageNotFoundError("message not found")
        return {
            "id": message_id,
            "conversation_id": "conv-1",
            "sender": "actor-a",
            "recipient": "actor-b",
            "topic": None,
            "message_type": "DIRECT",
            "content": {"body": "ok"},
            "metadata_": {"namespace": "default"},
            "priority": "NORMAL",
            "status": "DELIVERED",
            "ttl_seconds": 3600,
            "hop_count": 0,
            "parent_message_id": None,
            "expires_at": datetime.now(UTC),
            "delivered_at": datetime.now(UTC),
            "acked_at": None,
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }

    async def ack(self, actor: str, message_id: str) -> dict[str, Any]:
        return await self.get_for_actor(actor, message_id)

    async def reply(self, **kwargs: Any) -> list[dict[str, Any]]:
        return await self.send(
            actor=kwargs["actor"],
            namespace="default",
            message_type=kwargs["message_type"],
            content=kwargs["content"],
            recipient="actor-b",
        )


class _SubscriptionServiceStub:
    async def subscribe(self, agent_id: str, topic: str, namespace: str, actor: str) -> None:
        _ = (agent_id, topic, namespace, actor)

    async def unsubscribe(self, agent_id: str, topic: str, actor: str) -> None:
        _ = (agent_id, topic, actor)

    async def list_topics(self, namespace: str) -> list[str]:
        _ = namespace
        return ["__broadcast__"]


@pytest.fixture()
def message_client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_actor] = lambda: "actor-a"
    app.dependency_overrides[get_message_service] = lambda: _MessageServiceStub()
    app.dependency_overrides[get_subscription_service] = lambda: _SubscriptionServiceStub()
    return TestClient(app)


def test_send_direct_message_route(message_client: TestClient) -> None:
    response = message_client.post(
        "/api/v1/messages",
        json={
            "recipient": "actor-b",
            "message_type": "DIRECT",
            "content": {"body": "hello"},
            "sender": "fake",
        },
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload[0]["sender"] == "actor-a"


def test_broadcast_requires_permission_route(message_client: TestClient) -> None:
    response = message_client.post(
        "/api/v1/messages",
        json={"message_type": "BROADCAST", "content": {"body": "all"}},
    )
    assert response.status_code == 403


def test_topic_subscription_route(message_client: TestClient) -> None:
    response = message_client.post("/api/v1/topics/topic.alpha/subscribe?agent_id=01AGENT")
    assert response.status_code == 200
    assert response.json()["status"] == "subscribed"


def test_get_message_not_found_route(message_client: TestClient) -> None:
    response = message_client.get("/api/v1/messages/missing")
    assert response.status_code == 404
