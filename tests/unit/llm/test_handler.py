from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from syndicateclaw.orchestrator.engine import ExecutionContext
from syndicateclaw.orchestrator.handlers import llm_handler


@pytest.mark.asyncio
async def test_llm_handler_calls_provider_service_and_tags_state() -> None:
    provider = AsyncMock()
    provider.infer_chat.return_value = SimpleNamespace(content="hi", model_id="m1")

    context = ExecutionContext(
        run_id="run-1",
        node_id="node-1",
        attempt=1,
        config={"prompt_template": "Hello {{ state.name }}", "response_key": "answer"},
        provider_service=provider,
    )

    state = {"name": "alice"}
    result = await llm_handler(state, context)

    assert result.output_state["answer"] == "hi"
    assert result.output_state["_llm_output_answer"] is True
    assert provider.infer_chat.await_count == 1


@pytest.mark.asyncio
async def test_llm_handler_raises_when_provider_missing() -> None:
    context = ExecutionContext(run_id="run-1", node_id="node-1", config={})
    with pytest.raises(RuntimeError):
        await llm_handler({}, context)
