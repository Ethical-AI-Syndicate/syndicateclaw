"""ModelProvider protocol — stateless HTTP to provider; no routing or policy."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from syndicateclaw.inference.types import (
    ChatInferenceRequest,
    ChatInferenceResponse,
    EmbeddingInferenceRequest,
    EmbeddingInferenceResponse,
    ProviderConfig,
)


@runtime_checkable
class ModelProvider(Protocol):
    """Adapter implementation for one protocol (OpenAI-compatible or Ollama-native)."""

    async def infer_chat(
        self,
        cfg: ProviderConfig,
        req: ChatInferenceRequest,
        *,
        api_key: str | None,
        bearer_token: str | None,
    ) -> ChatInferenceResponse: ...

    async def infer_embedding(
        self,
        cfg: ProviderConfig,
        req: EmbeddingInferenceRequest,
        *,
        api_key: str | None,
        bearer_token: str | None,
    ) -> EmbeddingInferenceResponse: ...

    async def stream_chat(
        self,
        cfg: ProviderConfig,
        req: ChatInferenceRequest,
        *,
        api_key: str | None,
        bearer_token: str | None,
    ) -> AsyncIterator[str]: ...


def auth_headers(
    cfg: ProviderConfig,
    *,
    api_key: str | None,
    bearer_token: str | None,
) -> dict[str, str]:
    """Build Authorization / extra headers from resolved secrets (no routing)."""
    headers: dict[str, str] = dict(cfg.auth.additional_headers) if cfg.auth else {}
    if cfg.auth and bearer_token:
        headers[cfg.auth.header_name] = f"{cfg.auth.header_prefix}{bearer_token}"
    elif cfg.auth and api_key:
        headers[cfg.auth.header_name] = f"{cfg.auth.header_prefix}{api_key}"
    return headers
