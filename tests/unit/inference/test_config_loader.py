"""Tests for YAML provider config validation, diff, and atomic reload."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from pydantic import ValidationError

from syndicateclaw.inference.config_loader import (
    ConfigurationError,
    ProviderConfigLoader,
    compute_provider_diff,
    validate_provider_env_vars,
)
from syndicateclaw.inference.config_schema import ProviderSystemConfig, StaticCatalogEntry
from syndicateclaw.inference.types import (
    AdapterProtocol,
    InferenceCapability,
    ProviderAuthConfig,
    ProviderConfig,
    ProviderType,
)
from tests.unit.inference.fixtures import chat_descriptor, minimal_system, provider


def _write(path: Path, cfg: ProviderSystemConfig) -> None:
    import yaml

    path.write_text(
        yaml.safe_dump(cfg.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )


def test_load_validate_roundtrip(tmp_path: Path) -> None:
    sys = minimal_system(
        provider("a"),
        static=(
            StaticCatalogEntry(
                provider_id="a",
                model_id="m",
                capability=InferenceCapability.CHAT,
                descriptor=chat_descriptor("a", "m"),
            ),
        ),
    )
    _write(tmp_path / "p.yaml", sys)
    loader = ProviderConfigLoader(tmp_path / "p.yaml")
    loaded = loader.load_validate()
    assert loaded.providers[0].id == "a"


def test_duplicate_provider_ids_rejected() -> None:
    a = provider("dup")
    b = provider("dup")
    with pytest.raises(ValidationError, match="duplicate"):
        ProviderSystemConfig(
            inference_enabled=True,
            providers=(a, b),
        )


def test_static_catalog_unknown_provider_rejected() -> None:
    p = provider("only")
    row = StaticCatalogEntry(
        provider_id="missing",
        model_id="m",
        capability=InferenceCapability.CHAT,
        descriptor=chat_descriptor("missing", "m"),
    )
    with pytest.raises(ValueError, match="unknown provider"):
        ProviderSystemConfig(
            inference_enabled=True,
            providers=(p,),
            static_catalog=(row,),
        )


def test_diff_added_removed_modified() -> None:
    a = ProviderConfig(
        id="x",
        name="x",
        provider_type=ProviderType.LOCAL,
        adapter_protocol=AdapterProtocol.OLLAMA_NATIVE,
        base_url="http://x",
        capabilities=[InferenceCapability.CHAT],
        config_version="1",
    )
    b = ProviderConfig(
        id="x",
        name="x",
        provider_type=ProviderType.LOCAL,
        adapter_protocol=AdapterProtocol.OLLAMA_NATIVE,
        base_url="http://x",
        capabilities=[InferenceCapability.CHAT],
        config_version="2",
    )
    old = ProviderSystemConfig(providers=(a,))
    new = ProviderSystemConfig(providers=(a, provider("y")))
    d0 = compute_provider_diff(None, old)
    assert d0.added_provider_ids == ("x",)
    d1 = compute_provider_diff(old, new)
    assert d1.added_provider_ids == ("y",)
    assert d1.removed_provider_ids == ()
    d2 = compute_provider_diff(ProviderSystemConfig(providers=(a, provider("y"))), new)
    assert d2.added_provider_ids == ()
    d3 = compute_provider_diff(old, ProviderSystemConfig(providers=(b,)))
    assert d3.modified_provider_ids == ("x",)


def test_reload_atomic_reader_sees_only_complete_snapshots(tmp_path: Path) -> None:
    """Readers never observe a mixed provider set mid-swap (same key identity)."""
    import yaml

    sys_a = minimal_system(
        provider("a"),
        static=(
            StaticCatalogEntry(
                provider_id="a",
                model_id="m",
                capability=InferenceCapability.CHAT,
                descriptor=chat_descriptor("a", "m"),
            ),
        ),
    )
    sys_b = minimal_system(
        provider("b"),
        provider("c"),
        static=(
            StaticCatalogEntry(
                provider_id="b",
                model_id="m1",
                capability=InferenceCapability.CHAT,
                descriptor=chat_descriptor("b", "m1"),
            ),
            StaticCatalogEntry(
                provider_id="c",
                model_id="m2",
                capability=InferenceCapability.CHAT,
                descriptor=chat_descriptor("c", "m2"),
            ),
        ),
    )
    path = tmp_path / "live.yaml"
    path.write_text(yaml.safe_dump(sys_a.model_dump(mode="json")))

    loader = ProviderConfigLoader(path)
    loader.load_and_activate()
    set_a = frozenset(p.id for p in loader.current()[0].providers)
    set_b = frozenset(p.id for p in sys_b.providers)

    barrier = threading.Barrier(2)
    seen: list[frozenset[str]] = []

    def reader() -> None:
        barrier.wait()
        for _ in range(400):
            cfg, _ = loader.current()
            seen.append(frozenset(p.id for p in cfg.providers))
        barrier.wait()

    def writer() -> None:
        barrier.wait()
        for i in range(80):
            if i % 2 == 0:
                path.write_text(yaml.safe_dump(sys_a.model_dump(mode="json")))
            else:
                path.write_text(yaml.safe_dump(sys_b.model_dump(mode="json")))
            loader.load_and_activate()
        barrier.wait()

    t = threading.Thread(target=reader)
    t.start()
    writer()
    t.join()

    for s in seen:
        assert s in (set_a, set_b)


def test_provider_config_missing_env_var_fatal(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = ProviderSystemConfig(
        inference_enabled=True,
        providers=(
            ProviderConfig(
                id="remote",
                name="remote",
                provider_type=ProviderType.REMOTE,
                adapter_protocol=AdapterProtocol.OPENAI_COMPATIBLE,
                base_url="https://api.example.invalid",
                capabilities=[InferenceCapability.CHAT],
                auth=ProviderAuthConfig(env_var="SYNDICATECLAW_OPENAI_KEY"),
            ),
        ),
    )

    monkeypatch.delenv("SYNDICATECLAW_OPENAI_KEY", raising=False)
    with pytest.raises(ConfigurationError, match="SYNDICATECLAW_OPENAI_KEY"):
        validate_provider_env_vars(cfg)
