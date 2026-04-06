"""Coverage for adapter factory dispatch and auth_headers helper."""

from __future__ import annotations

import enum
from unittest.mock import MagicMock

import pytest

from syndicateclaw.inference.adapters.base import auth_headers
from syndicateclaw.inference.adapters.factory import adapter_for
from syndicateclaw.inference.types import AdapterProtocol


def test_adapter_for_openai_and_ollama() -> None:
    a1 = adapter_for(AdapterProtocol.OPENAI_COMPATIBLE)
    a2 = adapter_for(AdapterProtocol.OLLAMA_NATIVE)
    assert type(a1).__name__ == "OpenAICompatibleAdapter"
    assert type(a2).__name__ == "OllamaAdapter"


def test_adapter_for_unsupported_protocol_raises() -> None:
    class _NotAnAdapter(enum.Enum):
        X = "x"

    with pytest.raises(ValueError, match="unsupported adapter protocol"):
        adapter_for(_NotAnAdapter.X)  # type: ignore[arg-type]


def test_auth_headers_prefers_bearer_when_both_present() -> None:
    cfg = MagicMock()
    cfg.auth = MagicMock()
    cfg.auth.additional_headers = {"X-Extra": "1"}
    cfg.auth.header_name = "Authorization"
    cfg.auth.header_prefix = "Bearer "
    h = auth_headers(cfg, api_key="should-not-use", bearer_token="btok")
    assert h["Authorization"] == "Bearer btok"
    assert h["X-Extra"] == "1"


def test_auth_headers_uses_api_key_when_no_bearer() -> None:
    cfg = MagicMock()
    cfg.auth = MagicMock()
    cfg.auth.additional_headers = {}
    cfg.auth.header_name = "api-key"
    cfg.auth.header_prefix = ""
    h = auth_headers(cfg, api_key="k123", bearer_token=None)
    assert h["api-key"] == "k123"
