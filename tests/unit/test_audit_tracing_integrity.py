"""Unit tests for audit/tracing.py and audit/integrity.py."""
from __future__ import annotations

# ── tracing.py ────────────────────────────────────────────────────────────────

def test_setup_tracing_no_endpoint():
    """setup_tracing configures a tracer provider without OTLP endpoint."""
    from syndicateclaw.audit.tracing import get_tracer, setup_tracing
    setup_tracing("test-service")
    tracer = get_tracer("test")
    assert tracer is not None


def test_setup_tracing_with_otlp_endpoint():
    """setup_tracing with an OTLP endpoint adds the OTLP exporter."""
    from syndicateclaw.audit.tracing import setup_tracing
    # Should not raise even with a non-reachable endpoint
    setup_tracing("test-service", otlp_endpoint="http://localhost:4317")


def test_get_tracer_returns_tracer():
    from syndicateclaw.audit.tracing import get_tracer
    tracer = get_tracer(__name__)
    assert tracer is not None


def test_create_span_yields_span():
    from syndicateclaw.audit.tracing import create_span, get_tracer
    tracer = get_tracer(__name__)
    with create_span(tracer, "test-span", attributes={"key": "value"}) as span:
        assert span is not None


def test_create_span_no_attributes():
    from syndicateclaw.audit.tracing import create_span, get_tracer
    tracer = get_tracer(__name__)
    with create_span(tracer, "test-span-no-attrs") as span:
        assert span is not None
