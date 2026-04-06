from __future__ import annotations

import os

import pytest


@pytest.mark.requires_api_keys
def test_provider_api_keys_available() -> None:
    if os.environ.get("SYNDICATECLAW_CI_PROVIDER_TESTS", "").lower() != "true":
        pytest.skip("provider API key tests run only when CI provider gate is enabled")
    assert os.environ.get("OPENAI_API_KEY")
    assert os.environ.get("ANTHROPIC_API_KEY")
