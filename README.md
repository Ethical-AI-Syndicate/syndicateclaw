# Syndicate Claw

## Problem Statement

AI workflows become operational liabilities when tools, inference calls,
approval waits, replays, and handoffs can execute without policy-constrained
authority and reconstructible evidence. Workflow orchestration is not
governance unless the execution path can technically prevent unauthorized
actions.

Syndicate Claw is the governed workflow and tool execution plane for AI
Syndicate deployments.

## Operational Risk

Uncontrolled workflow execution creates risk when:

- tools run without a policy decision record,
- sensitive actions proceed without authorized approval,
- workflow state cannot be reconstructed,
- replay loads unverified checkpoints,
- inference and tool execution evidence is fragmented,
- the execution plane grants itself authority.

Claw exists to ensure workflow execution remains attributable,
policy-constrained, interruptible, and evidentiary.

## Enforcement Model

Syndicate Claw owns workflow execution, policy-gated tool execution, inference
execution, replay, and runtime evidence emission when deployed.

In standalone deployments, Claw can use local policy, approval, and audit
services as the authority source. In enterprise deployments that install Claw,
ControlPlane Enterprise is the central authority source. Claw verifies
ControlPlane permits and approval bindings before executing, then emits
execution evidence back to ControlPlane.

ControlPlane Enterprise authorizes. Claw executes.

### Gate Approval Path

1. Gate receives a sensitive request and sends the approval checkpoint to Claw.
2. In standalone mode, Claw resolves approval locally. In enterprise mode, Claw
   binds the request to ControlPlane authority.
3. Gate blocks execution before the provider call while approval is pending.
4. Approval resumes the same Gate request; rejection terminates it with no
   provider call.
5. Claw and Gate emit correlated evidence for ControlPlane audit package
   assembly.

## Architectural Principles

- Workflow execution must not self-authorize in enterprise mode.
- Tool execution requires policy evaluation and a decision record.
- Approval decisions must bind to the action context they authorize.
- Replay must load only integrity-verified state.
- Evidence emission is part of execution, not a later reporting task.
- Missing required authority or decision persistence must prevent execution.

## System Boundaries

Syndicate Claw governs workflow, tool, inference, approval, replay, memory, and
runtime evidence surfaces inside its deployed boundary.

It does not replace:

- ControlPlane Enterprise as central authority in enterprise mode,
- Syndicate Gate as provider enforcement boundary,
- customer identity infrastructure,
- customer network controls,
- host hardening and database administration,
- multi-tenant isolation where current release scope does not provide it.

## Governance Guarantees

Within the configured deployment boundary, Claw provides:

- fail-closed policy defaults for tool execution,
- decision records for policy-gated tool calls,
- approval lifecycle with expiration and rejection paths,
- append-only audit records at the application layer,
- checkpoint-based replay controls,
- actor attribution and correlation IDs for run reconstruction.

Some behaviors are configuration-dependent. For example, strict Redis-backed
rate limiting differs from non-strict degraded behavior. Audit integrity also
depends on protecting signing secrets and storage.

## Failure Modes

- Policy engine unavailable: execution is denied before tool execution.
- Decision ledger unavailable: tool execution is blocked.
- Required approval missing, expired, or rejected: execution remains blocked or
  terminates.
- Checkpoint verification failure: replay is aborted.
- Audit write failure: request path behavior follows the configured dead-letter
  and retry model and must be represented accurately in evidence claims.
- Enterprise permit invalid or missing: execution is denied.

## Product Capabilities

- FastAPI gateway.
- Graph-based workflow engine with retry and checkpoints.
- Policy-gated tool executor with explicit tool registry.
- Memory service with provenance tracking.
- Policy engine with fail-closed RBAC behavior.
- Approval service for human authority boundaries.
- Append-only audit event persistence with OpenTelemetry tracing.
- Inference provider routing with idempotency controls.
- PostgreSQL persistence and optional Redis cache.

API groups under `/api/v1/` include workflows, tools, memory, policies,
approvals, audit, and system health. Interactive API documentation is available
at `/docs` and `/redoc` in deployed environments.

## Deployment/Usage

Install the Syndicate Claw package for your platform, then start the approval
service:

```bash
syndicateclaw start
```

Verify readiness:

```bash
curl http://localhost:8000/healthz
```

Core environment variables use the `SYNDICATECLAW_` prefix:

```bash
SYNDICATECLAW_DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/syndicateclaw
SYNDICATECLAW_REDIS_URL=redis://localhost:6379/0
SYNDICATECLAW_SECRET_KEY=change-me-to-a-random-secret
SYNDICATECLAW_LOG_LEVEL=INFO
SYNDICATECLAW_OTEL_ENDPOINT=http://localhost:4317
```

Run checks:

```bash
pytest
pytest --cov=syndicateclaw --cov-report=term-missing
mypy src/syndicateclaw
ruff check src/ tests/
ruff format --check src/ tests/
```

See `docs/architecture.md`, `docs/threat-model.md`, `docs/failure-modes.md`,
and `docs/operations.md` for architecture, threat model, failure behavior, and
operator guidance.

## Commercial Packaging

Syndicate Claw is distributed as part of the AI Syndicate commercial
enforcement suite for licensed enterprise deployments.

## License

Proprietary commercial license. Redistribution or standalone open source use is
not permitted without a commercial agreement.
