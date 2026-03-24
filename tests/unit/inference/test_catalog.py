"""Tests for ModelCatalog indexes and YAML vs models.dev merge semantics."""

from __future__ import annotations

from syndicateclaw.inference.catalog import CatalogEntryRecord, ModelCatalog
from syndicateclaw.inference.config_schema import StaticCatalogEntry
from syndicateclaw.inference.types import (
    CatalogEntrySource,
    CatalogEntryStatus,
    InferenceCapability,
    ModelDescriptor,
)
from tests.unit.inference.fixtures import chat_descriptor, minimal_system, provider, static_chat_row


def test_replace_from_yaml_builds_indexes() -> None:
    sys = minimal_system(
        provider("p1"),
        static=(static_chat_row("p1", "m1"),),
    )
    cat = ModelCatalog()
    cat.replace_from_yaml_static(sys, snapshot_version="v1")
    assert cat.snapshot_version == "v1"
    assert cat.get("p1", "m1") is not None
    assert cat.models_for_capability_and_provider(InferenceCapability.CHAT, "p1") == ("m1",)
    assert cat.providers_for_model_id("m1") == (("p1", "m1"),)


def test_yaml_wins_on_collision_skips_models_dev_row() -> None:
    yaml_rows = (
        StaticCatalogEntry(
            provider_id="p",
            model_id="m",
            capability=InferenceCapability.CHAT,
            descriptor=chat_descriptor("p", "m"),
        ),
    )
    md_row = CatalogEntryRecord(
        provider_id="p",
        model_id="m",
        descriptor=ModelDescriptor(
            model_id="m",
            name="from-md",
            provider_id="p",
            is_embedding_model=False,
        ),
        capabilities=frozenset({InferenceCapability.CHAT}),
        status=CatalogEntryStatus.ACTIVE,
        source=CatalogEntrySource.MODELS_DEV,
    )
    cat = ModelCatalog()
    cat.merge_yaml_and_models_dev(
        yaml_rows=yaml_rows,
        models_dev_rows=(md_row,),
        snapshot_version="s1",
        yaml_wins_on_key_collision=True,
    )
    row = cat.get("p", "m")
    assert row is not None
    assert row.source == CatalogEntrySource.YAML_STATIC
    assert row.descriptor.name != "from-md"


def test_models_dev_wins_when_configured() -> None:
    yaml_rows = (
        StaticCatalogEntry(
            provider_id="p",
            model_id="m",
            capability=InferenceCapability.CHAT,
            descriptor=chat_descriptor("p", "m"),
        ),
    )
    md_row = CatalogEntryRecord(
        provider_id="p",
        model_id="m",
        descriptor=ModelDescriptor(
            model_id="m",
            name="from-md",
            provider_id="p",
            is_embedding_model=False,
        ),
        capabilities=frozenset({InferenceCapability.CHAT}),
        status=CatalogEntryStatus.ACTIVE,
        source=CatalogEntrySource.MODELS_DEV,
    )
    cat = ModelCatalog()
    cat.merge_yaml_and_models_dev(
        yaml_rows=yaml_rows,
        models_dev_rows=(md_row,),
        snapshot_version="s2",
        yaml_wins_on_key_collision=False,
    )
    assert cat.get("p", "m") is not None
    assert cat.get("p", "m").descriptor.name == "from-md"
    assert cat.get("p", "m").source == CatalogEntrySource.MODELS_DEV
