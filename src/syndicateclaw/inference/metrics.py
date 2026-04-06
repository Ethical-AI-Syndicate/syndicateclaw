"""Low-cardinality inference metrics (no model_id / actor labels)."""

from __future__ import annotations

from typing import Any

_counter: Any = None
_catalog_sync_counter: Any = None

try:
    from opentelemetry import metrics

    _meter = metrics.get_meter("syndicateclaw.inference")
    _counter = _meter.create_counter(
        "syndicateclaw_inference_outcomes",
        description="Inference outcomes by capability and result",
    )
    _catalog_sync_counter = _meter.create_counter(
        "syndicateclaw_catalog_sync_models_dev",
        description="models.dev catalog sync outcomes",
    )
except Exception:  # nosec B110
    pass


def record_inference_outcome(capability: str, outcome: str) -> None:
    """Emit one outcome sample (capability=chat|embedding|chat_stream; outcome=success|...)."""
    if _counter is not None:
        _counter.add(1, {"capability": capability, "outcome": outcome})


def record_catalog_sync_models_dev_outcome(outcome: str) -> None:
    """Low-cardinality sync result.

    Outcomes: success, fetch_failed, parse_failed, ssrf, http_error, anomaly, failed.
    """
    if _catalog_sync_counter is not None:
        _catalog_sync_counter.add(1, {"outcome": outcome})
