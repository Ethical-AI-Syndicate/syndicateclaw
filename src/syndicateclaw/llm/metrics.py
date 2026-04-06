from __future__ import annotations

from prometheus_client import Counter, Histogram

llm_requests_total = Counter(
    "llm_requests_total",
    "Total LLM API requests",
    labelnames=["provider", "model", "status"],
)

llm_tokens_used_total = Counter(
    "llm_tokens_used_total",
    "Total tokens consumed",
    labelnames=["provider", "model", "token_type"],
)

llm_cost_usd_total = Counter(
    "llm_cost_usd_total",
    "Estimated cost in USD",
    labelnames=["provider", "model"],
)

llm_cache_hits_total = Counter(
    "llm_cache_hits_total",
    "Idempotency cache hits",
    labelnames=["provider", "model"],
)

llm_request_duration_seconds = Histogram(
    "llm_request_duration_seconds",
    "LLM request duration in seconds",
    labelnames=["provider", "model"],
    buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0],
)
