from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from syndicateclaw.models import PolicyEffect, Tool, ToolRiskLevel, ToolSandboxPolicy
from syndicateclaw.orchestrator.engine import ExecutionContext
from syndicateclaw.orchestrator.handlers import llm_handler
from syndicateclaw.tools.registry import ToolRegistry


@dataclass
class _Decision:
    effect: PolicyEffect


def _tool_schema() -> Tool:
    return Tool(
        name="sum",
        version="1.0.0",
        description="sum tool",
        input_schema={"type": "object", "required": ["a", "b"], "properties": {}},
        output_schema={"type": "object", "properties": {}},
        owner="test",
        risk_level=ToolRiskLevel.LOW,
        timeout_seconds=5,
        side_effects=[],
        sandbox_policy=ToolSandboxPolicy(),
    )


@pytest.mark.asyncio
async def test_llm_tool_call_requires_opt_in() -> None:
    provider = AsyncMock()
    provider.infer_chat.return_value = SimpleNamespace(
        content="ok",
        model_id="m1",
        tool_calls=[{"name": "sum", "arguments": {"a": 1, "b": 2}}],
    )
    tool_executor = AsyncMock()

    context = ExecutionContext(
        run_id="run-1",
        node_id="node-1",
        config={"prompt": "hello"},
        provider_service=provider,
        tool_executor=tool_executor,
    )

    await llm_handler({}, context)
    tool_executor.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_llm_tool_call_passes_policy_gate() -> None:
    provider = AsyncMock()
    provider.infer_chat.return_value = SimpleNamespace(
        content="ok",
        model_id="m1",
        tool_calls=[{"name": "sum", "arguments": {"a": 1, "b": 2}}],
    )

    registry = ToolRegistry()

    async def handler(payload: dict[str, int]) -> dict[str, int]:
        return {"value": payload["a"] + payload["b"]}

    registry.register(_tool_schema(), handler)

    policy_engine = AsyncMock()
    policy_engine.evaluate.return_value = _Decision(PolicyEffect.ALLOW)

    tool_executor = SimpleNamespace(
        _registry=registry,
        _policy_engine=policy_engine,
        execute=AsyncMock(return_value={"value": 3}),
    )

    context = ExecutionContext(
        run_id="run-1",
        node_id="node-1",
        config={"prompt": "hello", "allow_tool_calls": True},
        provider_service=provider,
        tool_executor=tool_executor,
    )
    state: dict[str, object] = {}
    await llm_handler(state, context)

    tool_executor.execute.assert_awaited_once()
    assert state["_llm_tool_results"] == [{"tool": "sum", "result": {"value": 3}}]


@pytest.mark.asyncio
async def test_llm_tool_call_invalid_args_rejected() -> None:
    provider = AsyncMock()
    provider.infer_chat.return_value = SimpleNamespace(
        content="ok",
        model_id="m1",
        tool_calls=[{"name": "sum", "arguments": {"a": 1}}],
    )

    registry = ToolRegistry()

    async def handler(payload: dict[str, int]) -> dict[str, int]:
        return {"value": payload["a"] + payload["b"]}

    registry.register(_tool_schema(), handler)

    tool_executor = SimpleNamespace(
        _registry=registry,
        _policy_engine=AsyncMock(return_value=_Decision(PolicyEffect.ALLOW)),
        execute=AsyncMock(return_value={"value": 3}),
    )
    audit = SimpleNamespace(record=AsyncMock())

    context = ExecutionContext(
        run_id="run-1",
        node_id="node-1",
        config={"prompt": "hello", "allow_tool_calls": True},
        provider_service=provider,
        tool_executor=tool_executor,
        audit_service=audit,
    )

    await llm_handler({}, context)
    tool_executor.execute.assert_not_awaited()
    assert audit.record.await_count >= 1
