"""Prometheus-compatible metrics for SyndicateClaw."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

http_requests_total = Counter(
    "syndicateclaw_http_requests_total",
    "HTTP requests",
    ["method", "route", "status_code"],
)

http_request_duration_seconds = Histogram(
    "syndicateclaw_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "route"],
)

workflow_runs_total = Counter(
    "syndicateclaw_workflow_runs_total",
    "Workflow runs by terminal status",
    ["status"],
)

tool_executions_total = Counter(
    "syndicateclaw_tool_executions_total",
    "Tool executions",
    ["tool_name", "status"],
)

policy_evaluations_total = Counter(
    "syndicateclaw_policy_evaluations_total",
    "Policy evaluations",
    ["result"],
)

inference_requests_total = Counter(
    "syndicateclaw_inference_requests_total",
    "Inference requests",
    ["provider", "model", "status"],
)

inference_duration_seconds = Histogram(
    "syndicateclaw_inference_duration_seconds",
    "Inference latency",
    ["provider", "model"],
)

audit_events_total = Counter(
    "syndicateclaw_audit_events_total",
    "Audit events emitted",
    ["event_type"],
)

dead_letter_queue_size = Gauge(
    "syndicateclaw_dead_letter_queue_size",
    "Approximate dead-letter backlog (best-effort)",
)


def record_policy_evaluation(result: str) -> None:
    """result: allow | deny | error"""
    policy_evaluations_total.labels(result=result).inc()
