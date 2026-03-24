"""Map AdapterProtocol enum to adapter implementation (declarative; no topology)."""

from __future__ import annotations

from syndicateclaw.inference.adapters.base import ModelProvider
from syndicateclaw.inference.adapters.ollama import OllamaAdapter
from syndicateclaw.inference.adapters.openai_compatible import OpenAICompatibleAdapter
from syndicateclaw.inference.types import AdapterProtocol


def adapter_for(protocol: AdapterProtocol) -> ModelProvider:
    if protocol == AdapterProtocol.OPENAI_COMPATIBLE:
        return OpenAICompatibleAdapter()
    if protocol == AdapterProtocol.OLLAMA_NATIVE:
        return OllamaAdapter()
    raise ValueError(f"unsupported adapter protocol: {protocol!r}")
