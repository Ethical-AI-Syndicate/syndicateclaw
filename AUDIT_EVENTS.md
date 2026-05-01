# Audit Events

## Event fields

- `actor`: JWT subject, API key identity, service account, or system actor.
- `action`: auth, workflow, tool execution, RBAC change, policy decision, provider call, config/admin operation.
- `target`: organization, namespace, workflow, run, tool, provider, policy, or credential reference.
- `before` / `after`: safe metadata only; never log tokens, provider secrets, prompts containing sensitive data, or full payloads by default.
- `timestamp`: UTC RFC3339.
- `request_id`: request/correlation ID.
- `source_ip`: trusted ingress/proxy chain only.
- `success`: true/false.
- `reason_code`: auth_failed, rbac_denied, policy_denied, validation_failed, provider_error, or system_error.

## Current implementation

The codebase includes audit middleware, audit endpoints, audit persistence, and optional integrity/signing concepts. Treat evidence as tamper-evident only when the integrity/signing output is generated and retained outside the mutable database.

## Structured logging example

```json
{"ts":"2026-05-01T00:00:00Z","level":"info","event":"workflow.execute","actor":"oidc:user@example.test","target":"workflow:wf_123","request_id":"req-123","success":true,"reason_code":"authorized"}
```

## Retention recommendation

Retain audit rows, API logs, provider-call metadata, IdP logs, and Kubernetes events according to customer policy. For regulated pilots, assume at least 1 year searchable and 7 years archived unless the customer specifies otherwise.

## Export path

Run `scripts/export-audit-evidence.sh`. Provide `SYNDICATECLAW_DATABASE_URL` and `psql` for database export. The script is non-destructive.
