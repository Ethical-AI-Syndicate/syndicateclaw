"""OpenAI-compatible HTTP adapter (chat + embeddings).

No alias remapping — returns model field as-is.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from syndicateclaw.inference.adapters.base import auth_headers
from syndicateclaw.inference.errors import InferenceError
from syndicateclaw.inference.types import (
    ChatInferenceRequest,
    ChatInferenceResponse,
    EmbeddingInferenceRequest,
    EmbeddingInferenceResponse,
    ErrorCategory,
    ProviderConfig,
    TokenUsage,
)


class OpenAICompatibleAdapter:
    """POST /v1/chat/completions and /v1/embeddings."""

    async def infer_chat(
        self,
        cfg: ProviderConfig,
        req: ChatInferenceRequest,
        *,
        api_key: str | None,
        bearer_token: str | None,
    ) -> ChatInferenceResponse:
        url = cfg.base_url.rstrip("/") + "/v1/chat/completions"
        mid = req.model_id or ""
        body: dict[str, Any] = {
            "model": mid,
            "messages": [m.model_dump() for m in req.messages],
        }
        if req.temperature is not None:
            body["temperature"] = req.temperature
        if req.max_tokens is not None:
            body["max_tokens"] = req.max_tokens
        headers = auth_headers(cfg, api_key=api_key, bearer_token=bearer_token)
        headers.setdefault("Content-Type", "application/json")
        t0 = time.monotonic()
        timeout = httpx.Timeout(
            connect=cfg.timeout.connect_seconds,
            read=cfg.timeout.chat_seconds,
            write=cfg.timeout.connect_seconds,
            pool=cfg.timeout.connect_seconds,
        )
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=body, headers=headers)
        latency_ms = (time.monotonic() - t0) * 1000.0
        data = _json_or_error(resp, url)
        choice0 = (data.get("choices") or [{}])[0]
        msg = choice0.get("message") or {}
        content = msg.get("content") or ""
        resolved = str(data.get("model") or mid)
        usage = _usage(data.get("usage"))
        return ChatInferenceResponse(
            inference_id="",
            provider_id=cfg.id,
            model_id=resolved,
            content=content,
            finish_reason=choice0.get("finish_reason"),
            usage=usage,
            latency_ms=latency_ms,
        )

    async def infer_embedding(
        self,
        cfg: ProviderConfig,
        req: EmbeddingInferenceRequest,
        *,
        api_key: str | None,
        bearer_token: str | None,
    ) -> EmbeddingInferenceResponse:
        url = cfg.base_url.rstrip("/") + "/v1/embeddings"
        mid = req.model_id or ""
        body = {"model": mid, "input": req.inputs}
        headers = auth_headers(cfg, api_key=api_key, bearer_token=bearer_token)
        headers.setdefault("Content-Type", "application/json")
        t0 = time.monotonic()
        timeout = httpx.Timeout(
            connect=cfg.timeout.connect_seconds,
            read=cfg.timeout.embedding_seconds,
            write=cfg.timeout.connect_seconds,
            pool=cfg.timeout.connect_seconds,
        )
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=body, headers=headers)
        latency_ms = (time.monotonic() - t0) * 1000.0
        data = _json_or_error(resp, url)
        embs: list[list[float]] = []
        for item in data.get("data") or []:
            v = item.get("embedding")
            if isinstance(v, list):
                embs.append([float(x) for x in v])
        dims = len(embs[0]) if embs else 0
        return EmbeddingInferenceResponse(
            inference_id="",
            provider_id=cfg.id,
            model_id=str(data.get("model") or mid),
            embeddings=embs,
            dimensions=dims,
            usage=_usage(data.get("usage")),
            latency_ms=latency_ms,
        )

    async def stream_chat(
        self,
        cfg: ProviderConfig,
        req: ChatInferenceRequest,
        *,
        api_key: str | None,
        bearer_token: str | None,
    ) -> AsyncIterator[str]:
        url = cfg.base_url.rstrip("/") + "/v1/chat/completions"
        mid = req.model_id or ""
        body: dict[str, Any] = {
            "model": mid,
            "messages": [m.model_dump() for m in req.messages],
            "stream": True,
        }
        if req.temperature is not None:
            body["temperature"] = req.temperature
        if req.max_tokens is not None:
            body["max_tokens"] = req.max_tokens
        headers = auth_headers(cfg, api_key=api_key, bearer_token=bearer_token)
        headers.setdefault("Content-Type", "application/json")
        timeout = httpx.Timeout(
            connect=cfg.timeout.connect_seconds,
            read=cfg.timeout.chat_seconds,
            write=cfg.timeout.connect_seconds,
            pool=cfg.timeout.connect_seconds,
        )
        async with httpx.AsyncClient(timeout=timeout) as client, client.stream(
            "POST", url, json=body, headers=headers
        ) as resp:
            if resp.status_code >= 400:
                await resp.aread()
                raise InferenceError(
                    f"stream_http_{resp.status_code}",
                    category=ErrorCategory.PROVIDER,
                    retryable=resp.status_code in (429, 502, 503),
                )
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                payload = line.removeprefix("data:").strip()
                if payload == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                for ch in chunk.get("choices") or []:
                    delta = ch.get("delta") or {}
                    c = delta.get("content")
                    if c:
                        yield c


def _usage(raw: Any) -> TokenUsage | None:
    if not isinstance(raw, dict):
        return None
    return TokenUsage(
        prompt_tokens=int(raw.get("prompt_tokens") or 0),
        completion_tokens=int(raw.get("completion_tokens") or 0),
        total_tokens=int(raw.get("total_tokens") or 0),
    )


def _json_or_error(resp: httpx.Response, url: str) -> dict[str, Any]:
    if resp.status_code >= 400:
        raise InferenceError(
            f"http_{resp.status_code} {url}: {resp.text[:500]}",
            category=ErrorCategory.PROVIDER,
            retryable=resp.status_code in (429, 502, 503, 504),
        )
    try:
        out = resp.json()
    except json.JSONDecodeError as e:
        raise InferenceError(
            "malformed_json",
            category=ErrorCategory.VALIDATION,
            retryable=False,
        ) from e
    if not isinstance(out, dict):
        raise InferenceError(
            "response_not_object",
            category=ErrorCategory.VALIDATION,
            retryable=False,
        )
    return out
