"""Ollama-native HTTP adapter (/api/chat, /api/embed). No hidden alias mapping."""

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
)


class OllamaAdapter:
    """POST /api/chat and /api/embed — model id returned as reported by Ollama."""

    async def infer_chat(
        self,
        cfg: ProviderConfig,
        req: ChatInferenceRequest,
        *,
        api_key: str | None,
        bearer_token: str | None,
    ) -> ChatInferenceResponse:
        url = cfg.base_url.rstrip("/") + "/api/chat"
        mid = req.model_id or ""
        body: dict[str, Any] = {
            "model": mid,
            "messages": [m.model_dump() for m in req.messages],
            "stream": False,
        }
        if req.temperature is not None:
            body["options"] = {"temperature": req.temperature}
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
        msg = data.get("message") or {}
        content = str(msg.get("content") or "")
        resolved = str(data.get("model") or mid)
        return ChatInferenceResponse(
            inference_id="",
            provider_id=cfg.id,
            model_id=resolved,
            content=content,
            finish_reason=None,
            usage=None,
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
        url = cfg.base_url.rstrip("/") + "/api/embed"
        mid = req.model_id or ""
        body: dict[str, Any] = {"model": mid, "input": req.inputs}
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
        embs_raw = data.get("embeddings")
        if isinstance(embs_raw, list) and embs_raw and isinstance(embs_raw[0], list):
            embs = [[float(x) for x in row] for row in embs_raw]
        else:
            emb = data.get("embedding")
            embs = [[float(x) for x in emb]] if isinstance(emb, list) else []
        dims = len(embs[0]) if embs else 0
        return EmbeddingInferenceResponse(
            inference_id="",
            provider_id=cfg.id,
            model_id=str(data.get("model") or mid),
            embeddings=embs,
            dimensions=dims,
            usage=None,
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
        url = cfg.base_url.rstrip("/") + "/api/chat"
        mid = req.model_id or ""
        body: dict[str, Any] = {
            "model": mid,
            "messages": [m.model_dump() for m in req.messages],
            "stream": True,
        }
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
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg = chunk.get("message") or {}
                c = msg.get("content")
                if c:
                    yield str(c)


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
