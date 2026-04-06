from __future__ import annotations

import typing
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from ulid import ULID

from syndicateclaw.db.models import AgentMessage, WorkflowDefinition, WorkflowRun
from syndicateclaw.orchestrator.engine import ExecutionContext, WaitForAgentResponseError
from syndicateclaw.orchestrator.handlers import agent_send_handler
from syndicateclaw.tasks.agent_response_resume import resume_waiting_runs_once


class _MessageServiceStub:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def send(self, **kwargs: Any) -> list[Any]:
        self.calls.append(kwargs)

        class _Row:
            id = "01MSGT00000000000000000000"

        return [_Row()]


@pytest.fixture()
async def engine(db_engine: AsyncEngine) -> typing.AsyncGenerator[AsyncEngine, None]:
    yield db_engine


@pytest.mark.asyncio
async def test_agent_node_sends_message() -> None:
    state: dict[str, Any] = {}
    stub = _MessageServiceStub()
    ctx = ExecutionContext(
        run_id="run-1",
        node_id="delegate",
        config={
            "recipient_id": "01AGENT00000000000000000000",
            "message_type": "REQUEST",
            "content": {"query": "{{ state.input }}"},
            "response_key": "agent_result",
        },
        message_service=stub,
    )
    state["input"] = "hello"

    result = await agent_send_handler(state, ctx)
    assert result.output_state["agent_result"]["message_id"] == "01MSGT00000000000000000000"
    assert stub.calls


@pytest.mark.asyncio
async def test_agent_node_waits_for_response() -> None:
    state: dict[str, Any] = {}
    stub = _MessageServiceStub()
    ctx = ExecutionContext(
        run_id="run-2",
        node_id="delegate",
        config={
            "recipient_id": "01AGENT00000000000000000000",
            "message_type": "REQUEST",
            "content": {"query": "q"},
            "wait_for_response": True,
            "response_key": "agent_result",
            "response_timeout_seconds": 300,
        },
        message_service=stub,
    )

    with pytest.raises(WaitForAgentResponseError):
        await agent_send_handler(state, ctx)
    assert "_waiting_agent_response" in state


@pytest.mark.asyncio
async def test_agent_node_timeout(engine: AsyncEngine) -> None:
    sf = async_sessionmaker(engine, expire_on_commit=False)
    async with sf() as session, session.begin():
        await session.execute(delete(AgentMessage))
        wf = WorkflowDefinition(
            name=f"wf-timeout-{ULID()}",
            version="1",
            nodes=[],
            edges=[],
            namespace="default",
        )
        session.add(wf)
        await session.flush()
        run = WorkflowRun(
            workflow_id=wf.id,
            workflow_version="1",
            status="WAITING_AGENT_RESPONSE",
            namespace="default",
            state={
                "_waiting_agent_response": {
                    "conversation_id": "conv-timeout",
                    "response_key": "agent_result",
                    "requested_at": (datetime.now(UTC) - timedelta(seconds=400)).isoformat(),
                    "timeout_seconds": 300,
                }
            },
        )
        session.add(run)

    class _NoResponseService:
        async def delivered_responses(self, *, limit: int = 200) -> list[Any]:
            _ = limit
            return []

        async def mark_response_consumed(self, message_id: str) -> None:
            _ = message_id

    resumed = await resume_waiting_runs_once(sf, _NoResponseService())
    assert resumed == 0

    async with sf() as session:
        refreshed = await session.get(WorkflowRun, run.id)
        assert refreshed is not None
        assert refreshed.status == "FAILED"
        assert refreshed.error == "WAITING_AGENT_RESPONSE_TIMEOUT"


@pytest.mark.asyncio
async def test_agent_node_capability_routing() -> None:
    state: dict[str, Any] = {}
    stub = _MessageServiceStub()
    ctx = ExecutionContext(
        run_id="run-3",
        node_id="delegate",
        config={
            "message_type": "REQUEST",
            "content": {"query": "q"},
            "fallback_strategy": "queue",
            "capability": "research",
            "response_key": "agent_result",
        },
        message_service=stub,
    )

    result = await agent_send_handler(state, ctx)
    assert result.output_state["agent_result"]["conversation_id"]
    assert stub.calls[0]["topic"] == "capability:research"


@pytest.mark.asyncio
async def test_agent_node_full_drain_fallback() -> None:
    state: dict[str, Any] = {}
    stub = _MessageServiceStub()
    ctx = ExecutionContext(
        run_id="run-4",
        node_id="delegate",
        config={
            "message_type": "REQUEST",
            "content": {"query": "q"},
            "fallback_strategy": "broadcast",
            "response_key": "agent_result",
        },
        message_service=stub,
    )

    result = await agent_send_handler(state, ctx)
    assert result.output_state["agent_result"]["message_id"]
    assert stub.calls[0]["message_type"] == "BROADCAST"
