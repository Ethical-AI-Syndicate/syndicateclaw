from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

agent_messages_total = Counter(
    "agent_messages_total",
    "Total messages sent",
    labelnames=["message_type", "status"],
)

agent_message_hop_limit_exceeded_total = Counter(
    "agent_message_hop_limit_exceeded_total",
    "Messages terminated due to hop limit",
    labelnames=["message_type"],
)

workflow_versions_total = Counter(
    "workflow_versions_total",
    "Total workflow versions created",
    labelnames=["namespace"],
)

agent_message_delivery_duration_seconds = Histogram(
    "agent_message_delivery_duration_seconds",
    "Message delivery latency",
    labelnames=["message_type"],
)

agents_online = Gauge(
    "agents_online",
    "Number of agents currently online",
    labelnames=["namespace"],
)
