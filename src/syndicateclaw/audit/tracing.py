from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

import structlog
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

from syndicateclaw import __version__

if TYPE_CHECKING:
    from opentelemetry.trace import Span, Tracer

_SERVICE_VERSION = __version__

logger = structlog.get_logger(__name__)


def setup_tracing(service_name: str, otlp_endpoint: str | None = None) -> None:
    """Configure the global OpenTelemetry tracer provider."""
    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": _SERVICE_VERSION,
        }
    )
    provider = TracerProvider(resource=resource)

    if otlp_endpoint:
        otlp_exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
        provider.add_span_processor(SimpleSpanProcessor(otlp_exporter))
        logger.info("otel_otlp_exporter_configured", endpoint=otlp_endpoint)

    provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)
    logger.info("otel_tracing_configured", service_name=service_name)


def get_tracer(name: str) -> Tracer:
    """Return a tracer from the global provider."""
    return trace.get_tracer(name)


@contextmanager
def create_span(
    tracer: Tracer,
    name: str,
    attributes: dict[str, Any] | None = None,
) -> Iterator[Span]:
    """Convenience wrapper for creating spans with common attributes."""
    with tracer.start_as_current_span(name) as span:
        if attributes:
            for key, value in attributes.items():
                span.set_attribute(key, value)
        yield span
