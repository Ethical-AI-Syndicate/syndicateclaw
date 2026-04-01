"""Exercise OllamaAdapter HTTP paths with mocked httpx (no real Ollama)."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest

from syndicateclaw.inference.adapters.ollama import OllamaAdapter, _json_or_error
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


def _cfg() -> ProviderConfig:
    return ProviderConfig(
        id="ollama-test",
        name="Ollama",
        provider_type=ProviderType.LOCAL,
        adapter_protocol=AdapterProtocol.OLLAMA_NATIVE,
        base_url="http://127.0.0.1:11434",
        capabilities=[InferenceCapability.CHAT, InferenceCapability.EMBEDDING],
    )


class _Resp:
    def __init__(self, data: dict[str, Any], status: int = 200) -> None:
        self.status_code = status
        self.text = ""
        self._data = data

    def json(self) -> dict[str, Any]:
        return self._data


class _Client:
    def __init__(self, response: _Resp, **_: Any) -> None:
        self._response = response

    async def __aenter__(self) -> _Client:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(self, url: str, json: Any = None, headers: Any = None) -> _Resp:
        return self._response


@pytest.mark.asyncio
async def test_ollama_infer_chat_success() -> None:
    adapter = OllamaAdapter()
    resp = _Resp({"model": "llama3", "message": {"content": "hi"}})
    req = ChatInferenceRequest(
        messages=[ChatMessage(role="user", content="yo")],
        actor="a",
        trace_id="t",
        model_id="llama3",
    )
    patch_path = "syndicateclaw.inference.adapters.ollama.httpx.AsyncClient"
    with patch(patch_path, lambda **k: _Client(resp)):
        out = await adapter.infer_chat(_cfg(), req, api_key=None, bearer_token=None)
    assert out.content == "hi"
    assert out.model_id == "llama3"


@pytest.mark.asyncio
async def test_ollama_infer_embedding_matrix_format() -> None:
    adapter = OllamaAdapter()
    resp = _Resp({"model": "e", "embeddings": [[0.1, 0.2], [0.3, 0.4]]})
    req = EmbeddingInferenceRequest(inputs=["a", "b"], actor="a", trace_id="t", model_id="e")
    patch_path = "syndicateclaw.inference.adapters.ollama.httpx.AsyncClient"
    with patch(patch_path, lambda **k: _Client(resp)):
        out = await adapter.infer_embedding(_cfg(), req, api_key=None, bearer_token=None)
    assert out.dimensions == 2
    assert len(out.embeddings) == 2


@pytest.mark.asyncio
async def test_ollama_infer_embedding_single_vector_format() -> None:
    adapter = OllamaAdapter()
    resp = _Resp({"model": "e2", "embedding": [1.0, 2.0, 3.0]})
    req = EmbeddingInferenceRequest(inputs=["x"], actor="a", trace_id="t", model_id="e2")
    patch_path = "syndicateclaw.inference.adapters.ollama.httpx.AsyncClient"
    with patch(patch_path, lambda **k: _Client(resp)):
        out = await adapter.infer_embedding(_cfg(), req, api_key=None, bearer_token=None)
    assert out.dimensions == 3
    assert out.embeddings == [[1.0, 2.0, 3.0]]


def test_json_or_error_http_raises() -> None:
    r = _Resp({}, status=500)
    r.text = "oops"
    with pytest.raises(InferenceError, match="http_500"):
        _json_or_error(r, "http://x")  # type: ignore[arg-type]


def test_json_or_error_not_object_raises() -> None:
    class ListBody:
        status_code = 200
        text = ""

        def json(self) -> Any:
            return [1, 2]

    with pytest.raises(InferenceError, match="response_not_object"):
        _json_or_error(ListBody(), "http://x")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_ollama_infer_chat_with_temperature() -> None:
    adapter = OllamaAdapter()
    resp = _Resp({"model": "llama3", "message": {"content": "hot"}})
    req = ChatInferenceRequest(
        messages=[ChatMessage(role="user", content="hot?")],
        actor="a",
        trace_id="t",
        model_id="llama3",
        temperature=0.9,
    )
    patch_path = "syndicateclaw.inference.adapters.ollama.httpx.AsyncClient"
    with patch(patch_path, lambda **k: _Client(resp)):
        out = await adapter.infer_chat(_cfg(), req, api_key=None, bearer_token=None)
    assert out.content == "hot"


class _StreamResp:
    """Async streaming response mock for OllamaAdapter.stream_chat tests."""

    def __init__(self, lines: list[str], status: int = 200) -> None:
        self.status_code = status
        self._lines = lines

    async def aread(self) -> None:
        pass

    async def aiter_lines(self) -> Any:
        for line in self._lines:
            yield line


class _StreamClient:
    def __init__(self, resp: _StreamResp, **_: Any) -> None:
        self._resp = resp

    async def __aenter__(self) -> _StreamClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    def stream(self, *args: Any, **kwargs: Any) -> _StreamClient:
        return self

    async def __aenter2__(self) -> _StreamResp:
        return self._resp

    # support `async with client.stream(...) as resp:`
    def __call__(self, *args: Any, **kwargs: Any) -> _StreamClient:
        return self

    class _StreamCtx:
        def __init__(self, resp: _StreamResp) -> None:
            self._resp = resp

        async def __aenter__(self) -> _StreamResp:
            return self._resp

        async def __aexit__(self, *args: object) -> None:
            pass

    def _stream_ctx(self) -> _StreamCtx:
        return _StreamClient._StreamCtx(self._resp)


class _StreamClientFactory:
    """Factory that returns an async context manager yielding _StreamClient."""

    def __init__(self, resp: _StreamResp) -> None:
        self._resp = resp

    def __call__(self, **kwargs: Any) -> _OuterCtx:
        return _OuterCtx(self._resp)


class _OuterCtx:
    def __init__(self, resp: _StreamResp) -> None:
        self._resp = resp
        self._inner = _InnerClient(resp)

    async def __aenter__(self) -> _InnerClient:
        return self._inner

    async def __aexit__(self, *args: object) -> None:
        pass


class _InnerClient:
    def __init__(self, resp: _StreamResp) -> None:
        self._resp = resp

    def stream(self, *args: Any, **kwargs: Any) -> _InnerStreamCtx:
        return _InnerStreamCtx(self._resp)


class _InnerStreamCtx:
    def __init__(self, resp: _StreamResp) -> None:
        self._resp = resp

    async def __aenter__(self) -> _StreamResp:
        return self._resp

    async def __aexit__(self, *args: object) -> None:
        pass


@pytest.mark.asyncio
async def test_ollama_stream_chat_yields_content() -> None:
    adapter = OllamaAdapter()
    lines = [
        json.dumps({"message": {"content": "Hello"}}),
        "",  # empty line — should be skipped
        json.dumps({"message": {"content": " world"}}),
        "not-json",  # malformed — should be skipped
        json.dumps({"message": {}}),  # no content — should be skipped
    ]
    resp = _StreamResp(lines)
    req = ChatInferenceRequest(
        messages=[ChatMessage(role="user", content="hi")],
        actor="a",
        trace_id="t",
        model_id="llama3",
    )
    patch_path = "syndicateclaw.inference.adapters.ollama.httpx.AsyncClient"
    with patch(patch_path, _StreamClientFactory(resp)):
        chunks = [
            c async for c in adapter.stream_chat(_cfg(), req, api_key=None, bearer_token=None)
        ]
    assert chunks == ["Hello", " world"]


@pytest.mark.asyncio
async def test_ollama_stream_chat_http_error_raises() -> None:
    adapter = OllamaAdapter()
    resp = _StreamResp([], status=503)
    req = ChatInferenceRequest(
        messages=[ChatMessage(role="user", content="hi")],
        actor="a",
        trace_id="t",
        model_id="llama3",
    )
    patch_path = "syndicateclaw.inference.adapters.ollama.httpx.AsyncClient"
    from syndicateclaw.inference.errors import InferenceError as _InferenceError

    with patch(patch_path, _StreamClientFactory(resp)), pytest.raises(_InferenceError):
        async for _ in adapter.stream_chat(_cfg(), req, api_key=None, bearer_token=None):
            pass


def test_json_or_error_malformed_json() -> None:
    class Bad:
        status_code = 200
        text = "nope"

        def json(self) -> dict[str, Any]:
            raise json.JSONDecodeError("msg", "doc", 0)

    with pytest.raises(InferenceError, match="malformed_json"):
        _json_or_error(Bad(), "http://x")  # type: ignore[arg-type]
