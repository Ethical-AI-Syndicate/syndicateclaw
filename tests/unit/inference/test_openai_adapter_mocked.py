"""Mocked unit tests for OpenAICompatibleAdapter (chat + embedding + stream)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from syndicateclaw.inference.adapters.openai_compatible import OpenAICompatibleAdapter
from syndicateclaw.inference.errors import InferenceError
from syndicateclaw.inference.types import (
    AdapterProtocol,
    ChatInferenceRequest,
    ChatMessage,
    EmbeddingInferenceRequest,
    InferenceCapability,
    ProviderConfig,
    ProviderType,
)

_ASYNC_CLIENT = "syndicateclaw.inference.adapters.openai_compatible.httpx.AsyncClient"


def _cfg(base_url: str = "https://api.test.local") -> ProviderConfig:
    return ProviderConfig(
        id="test-provider",
        name="Test",
        provider_type=ProviderType.REMOTE,
        adapter_protocol=AdapterProtocol.OPENAI_COMPATIBLE,
        base_url=base_url,
        capabilities=[InferenceCapability.CHAT, InferenceCapability.EMBEDDING],
    )


def _chat_req(model_id: str = "gpt-test") -> ChatInferenceRequest:
    return ChatInferenceRequest(
        model_id=model_id,
        messages=[ChatMessage(role="user", content="hello")],
        actor="test-actor",
        trace_id="trace-001",
    )


def _mock_resp(status: int, body: dict) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.json.return_value = body
    resp.text = json.dumps(body)
    return resp


def _mock_client(resp: MagicMock) -> AsyncMock:
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(return_value=resp)
    return client


# ---------------------------------------------------------------------------
# infer_chat
# ---------------------------------------------------------------------------


async def test_infer_chat_happy_path() -> None:
    body = {
        "model": "gpt-test",
        "choices": [{"message": {"content": "world"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
    }
    client = _mock_client(_mock_resp(200, body))
    with patch(_ASYNC_CLIENT, return_value=client):
        result = await OpenAICompatibleAdapter().infer_chat(
            _cfg(), _chat_req(), api_key="sk-test", bearer_token=None
        )
    assert result.content == "world"
    assert result.model_id == "gpt-test"
    assert result.usage is not None
    assert result.usage.total_tokens == 8


async def test_infer_chat_with_temperature_and_max_tokens() -> None:
    body = {
        "model": "m",
        "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
    }
    client = _mock_client(_mock_resp(200, body))
    req = ChatInferenceRequest(
        model_id="m",
        messages=[ChatMessage(role="user", content="hi")],
        temperature=0.7,
        max_tokens=50,
        actor="test-actor",
        trace_id="trace-002",
    )
    with patch(_ASYNC_CLIENT, return_value=client):
        result = await OpenAICompatibleAdapter().infer_chat(
            _cfg(), req, api_key=None, bearer_token=None
        )
    assert result.content == "ok"
    _, kwargs = client.post.call_args
    assert kwargs["json"]["temperature"] == 0.7
    assert kwargs["json"]["max_tokens"] == 50


async def test_infer_chat_http_error_raises_inference_error() -> None:
    client = _mock_client(_mock_resp(429, {"error": "rate limit"}))
    with patch(_ASYNC_CLIENT, return_value=client), pytest.raises(
        InferenceError, match="http_429"
    ):
        await OpenAICompatibleAdapter().infer_chat(
            _cfg(), _chat_req(), api_key=None, bearer_token=None
        )


# ---------------------------------------------------------------------------
# infer_embedding
# ---------------------------------------------------------------------------


async def test_infer_embedding_happy_path() -> None:
    body = {
        "model": "emb-model",
        "data": [{"embedding": [0.1, 0.2, 0.3]}],
        "usage": {"prompt_tokens": 2, "completion_tokens": 0, "total_tokens": 2},
    }
    client = _mock_client(_mock_resp(200, body))
    req = EmbeddingInferenceRequest(
        model_id="emb-model",
        inputs=["hello world"],
        actor="test-actor",
        trace_id="trace-003",
    )
    with patch(_ASYNC_CLIENT, return_value=client):
        result = await OpenAICompatibleAdapter().infer_embedding(
            _cfg(), req, api_key="sk-test", bearer_token=None
        )
    assert result.embeddings == [[0.1, 0.2, 0.3]]
    assert result.dimensions == 3


async def test_infer_embedding_http_error_raises() -> None:
    client = _mock_client(_mock_resp(503, {"error": "unavailable"}))
    req = EmbeddingInferenceRequest(
        model_id="emb-model",
        inputs=["text"],
        actor="test-actor",
        trace_id="trace-004",
    )
    with patch(_ASYNC_CLIENT, return_value=client), pytest.raises(
        InferenceError, match="http_503"
    ):
        await OpenAICompatibleAdapter().infer_embedding(
            _cfg(), req, api_key=None, bearer_token=None
        )


# ---------------------------------------------------------------------------
# stream_chat
# ---------------------------------------------------------------------------


async def test_stream_chat_yields_content_chunks() -> None:
    lines = [
        'data: {"choices":[{"delta":{"content":"hel"}}]}',
        'data: {"choices":[{"delta":{"content":"lo"}}]}',
        "data: [DONE]",
    ]

    async def aiter_lines():
        for line in lines:
            yield line

    mock_stream_resp = AsyncMock()
    mock_stream_resp.status_code = 200
    mock_stream_resp.aiter_lines = aiter_lines
    mock_stream_resp.__aenter__ = AsyncMock(return_value=mock_stream_resp)
    mock_stream_resp.__aexit__ = AsyncMock(return_value=False)

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.stream = MagicMock(return_value=mock_stream_resp)

    with patch(_ASYNC_CLIENT, return_value=mock_client):
        chunks = [
            c
            async for c in OpenAICompatibleAdapter().stream_chat(
                _cfg(), _chat_req(), api_key=None, bearer_token=None
            )
        ]
    assert chunks == ["hel", "lo"]


async def test_stream_chat_http_error_raises() -> None:
    mock_stream_resp = AsyncMock()
    mock_stream_resp.status_code = 401
    mock_stream_resp.aread = AsyncMock()
    mock_stream_resp.__aenter__ = AsyncMock(return_value=mock_stream_resp)
    mock_stream_resp.__aexit__ = AsyncMock(return_value=False)

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.stream = MagicMock(return_value=mock_stream_resp)

    with patch(_ASYNC_CLIENT, return_value=mock_client), pytest.raises(
        InferenceError, match="stream_http_401"
    ):
        async for _ in OpenAICompatibleAdapter().stream_chat(
            _cfg(), _chat_req(), api_key=None, bearer_token=None
        ):
            pass
