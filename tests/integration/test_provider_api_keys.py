from __future__ import annotations

import os

import pytest


@pytest.mark.requires_api_keys
def test_provider_api_keys_available() -> None:
    assert os.environ.get("OPENAI_API_KEY")
    assert os.environ.get("ANTHROPIC_API_KEY")
