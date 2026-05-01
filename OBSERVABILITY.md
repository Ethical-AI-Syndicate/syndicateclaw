# Observability

## Logs

Application logs are emitted to stdout/stderr for container collection. Customer SRE must collect API logs, worker/runtime logs, database logs, Redis logs, ingress logs, and IdP logs.

## Metrics

Use existing health endpoints and any configured application/runtime metrics. Do not expose new `/metrics` publicly without auth/network policy review.

## Traces

Tracing depends on deployment configuration. If OpenTelemetry is enabled, customer SRE owns collector, exporter, sampling, and retention.

## Correlation IDs

Ingress should inject/preserve request IDs. Workflow execution, provider calls, audit rows, and policy decisions should retain request/run correlation where available.

## Alert Suggestions

- `/healthz` or `/readyz` failure.
- Workflow execution error spike.
- Policy/RBAC denial spike.
- Provider error or timeout spike.
- DB pool saturation and migration failures.
- Redis unavailable when used for runtime state.
- Audit export/integrity failure.

## Dashboard Starter KPIs

- Request rate, error rate, latency.
- Workflow run count and failures.
- Provider latency/error rate.
- RBAC/policy denial count.
- DB and Redis saturation.
- Release version and config fingerprint.

## PII Logging Cautions

Do not log raw prompts, workflow payloads, API keys, JWTs, customer documents, or provider responses unless explicitly approved and redacted.

## Retention Owner Split

Customer owns log storage, SIEM routing, access controls, and retention. Vendor owns emitted signal documentation and audit/export tooling.
