from __future__ import annotations

from pathlib import Path

import yaml

from syndicateclaw.inference.config_schema import ProviderSystemConfig
from syndicateclaw.inference.types import AdapterProtocol, ProviderType


def test_syndicategate_provider_example_uses_code_compatible_contract() -> None:
    raw = yaml.safe_load(
        (Path(__file__).resolve().parents[3] / "providers.syndicategate.yaml.example").read_text(
            encoding="utf-8"
        )
    )
    cfg = ProviderSystemConfig.model_validate(raw)

    provider = next(p for p in cfg.providers if p.id == "syndicategate")
    assert provider.provider_type == ProviderType.REMOTE
    assert provider.adapter_protocol == AdapterProtocol.OPENAI_COMPATIBLE
    assert provider.base_url == "http://syndicategate:8080"
    assert provider.auth is not None
    assert provider.auth.env_var == "SYNDICATEGATE_API_KEY"
    assert provider.auth.header_name == "Authorization"
    assert provider.auth.header_prefix == "Bearer "

    model_ids = {
        entry.model_id for entry in cfg.static_catalog if entry.provider_id == "syndicategate"
    }
    assert "gpt-4o-mini" in model_ids
    assert "text-embedding-3-small" in model_ids
