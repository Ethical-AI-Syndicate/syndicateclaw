from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from syndicateclaw.api.dependencies import get_streaming_token_service
from syndicateclaw.api.routes.streaming import router as streaming_router
from syndicateclaw.streaming.connection_manager import connection_manager


class _FakeStreamingTokenService:
    async def validate_and_consume(self, token: str, run_id: str) -> str:
        if token == "bad-token":
            from syndicateclaw.services.streaming_token_service import InvalidTokenError

            raise InvalidTokenError("Token not found")
        return "actor"


@pytest.mark.asyncio
async def test_stream_run_sse_heartbeat_and_completion() -> None:
    app = FastAPI()
    app.include_router(streaming_router)
    app.dependency_overrides[get_streaming_token_service] = lambda: _FakeStreamingTokenService()

    async def producer() -> None:
        await asyncio.sleep(0.05)
        await connection_manager.broadcast(
            "run-1",
            {
                "type": "llm_complete",
                "usage": {"prompt_tokens": 1},
                "response": "sensitive",
                "timestamp": "2026-03-27T00:00:00Z",
            },
        )
        await connection_manager.broadcast("run-1", {"type": "run_complete"})

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        task = asyncio.create_task(producer())
        response = await client.get("/api/v1/runs/run-1/stream", params={"token": "ok-token"})
        await task

    assert response.status_code == 200
    assert "event: llm_complete" in response.text
    assert "response" not in response.text
    assert "event: run_complete" in response.text


@pytest.mark.asyncio
async def test_sse_streaming_token_required() -> None:
    app = FastAPI()
    app.include_router(streaming_router)
    app.dependency_overrides[get_streaming_token_service] = lambda: _FakeStreamingTokenService()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/api/v1/runs/run-1/stream",
            params={"token": "bad-token"},
        )

    assert response.status_code == 401
