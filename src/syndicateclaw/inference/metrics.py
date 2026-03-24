"""Low-cardinality inference metrics (no model_id / actor labels)."""

from __future__ import annotations

_counter = None

try:
    from opentelemetry import metrics

    _meter = metrics.get_meter("syndicateclaw.inference")
    _counter = _meter.create_counter(
        "syndicateclaw_inference_outcomes",
        description="Inference outcomes by capability and result",
    )
except Exception:
    pass


def record_inference_outcome(capability: str, outcome: str) -> None:
    """Emit one outcome sample (capability=chat|embedding|chat_stream; outcome=success|...)."""
    if _counter is not None:
        _counter.add(1, {"capability": capability, "outcome": outcome})
