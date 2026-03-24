"""models.dev merge: unmapped providers skipped; anomaly abort; rollback."""

from __future__ import annotations

import pytest

from syndicateclaw.inference.catalog import ModelCatalog
from syndicateclaw.inference.catalog_sync.modelsdev import (
    ModelsDevCatalogSync,
    parse_models_dev_json,
)
from tests.unit.inference.fixtures import minimal_system, provider, static_chat_row


def test_skips_unmapped_provider() -> None:
    sys = minimal_system(provider("allowed"), static=(static_chat_row("allowed", "m1"),))
    cat = ModelCatalog()
    cat.replace_from_yaml_static(sys, snapshot_version="v0")
    sync = ModelsDevCatalogSync(
        base_system_config=sys,
        allowed_provider_ids=frozenset({"allowed"}),
        catalog=cat,
        yaml_static_rows=sys.static_catalog,
    )
    res = sync.sync_from_parsed_records(
        [
            {"provider_id": "other", "model_id": "x", "capability": "chat", "name": "X"},
            {"provider_id": "allowed", "model_id": "m2", "capability": "chat", "name": "M2"},
        ],
        snapshot_version="v1",
        previous_count=1,
    )
    assert res.applied is True
    assert res.records_accepted == 1
    assert cat.get("allowed", "m2") is not None


def test_full_json_parse_failure_raises() -> None:
    with pytest.raises(ValueError):
        parse_models_dev_json("not json")


def test_anomaly_aborts_when_drop_too_large() -> None:
    rows = (static_chat_row("p", "a"), static_chat_row("p", "b"))
    sys = minimal_system(provider("p"), static=rows)
    cat = ModelCatalog()
    cat.replace_from_yaml_static(sys, snapshot_version="v0")
    sync = ModelsDevCatalogSync(
        base_system_config=sys,
        allowed_provider_ids=frozenset({"p"}),
        catalog=cat,
        yaml_static_rows=sys.static_catalog,
        anomaly_max_drop_ratio=0.5,
    )
    res = sync.sync_from_parsed_records(
        [],
        snapshot_version="vbad",
        previous_count=2,
    )
    assert res.applied is False
    assert res.aborted_reason == "systemic_anomaly_drop"
