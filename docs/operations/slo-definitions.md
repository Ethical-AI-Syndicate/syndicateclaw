# Service Level Objectives (SLOs)

## API Availability

| SLO | Target | Measurement |
|-----|--------|-------------|
| Availability | 99.9% | `up{job="syndicateclaw"} == 1` over 30-day window |
| Error Budget | 43.2 min/month | Time with 5xx responses |

## API Latency

| SLO | Target | Measurement |
|-----|--------|-------------|
| p50 latency | < 200ms | `histogram_quantile(0.50, ...)` |
| p95 latency | < 2s | `histogram_quantile(0.95, ...)` |
| p99 latency | < 5s | `histogram_quantile(0.99, ...)` |

## Inference

| SLO | Target | Measurement |
|-----|--------|-------------|
| Inference success rate | 99.5% | `inference_requests_total{status="success"}` / total |
| Inference p95 latency | < 10s | `histogram_quantile(0.95, inference_duration_seconds_bucket)` |

## Audit

| SLO | Target | Measurement |
|-----|--------|-------------|
| Audit event write success | 99.99% | Events emitted vs dead-lettered |
| DLQ backlog | < 100 | `syndicateclaw_dead_letter_queue_size` |

## Alerting Thresholds

Alerts fire at 2x the SLO threshold to allow time for response before budget exhaustion.
