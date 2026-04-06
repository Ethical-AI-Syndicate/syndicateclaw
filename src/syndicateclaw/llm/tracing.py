from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.trace import Span

tracer = trace.get_tracer("syndicateclaw.llm")


@contextmanager
def llm_span(provider: str, model: str, cached: bool = False) -> Iterator[Span]:
    with tracer.start_as_current_span("llm.complete") as span:
        span.set_attribute("provider", provider)
        span.set_attribute("model", model)
        span.set_attribute("cached", cached)
        yield span
