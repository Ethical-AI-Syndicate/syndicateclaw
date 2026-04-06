# SyndicateClaw Full-Codebase Remediation Design (Refactor-First)

Date: 2026-03-31
Owner: Platform Engineering
Status: Draft for review

## 1) Objective

Define a refactor-first remediation program for the full SyndicateClaw codebase that:

1. Resolves architecture and quality-gate instability before feature expansion.
2. Completes currently stubbed admin/console/connector capabilities after the foundation is hardened.
3. Performs a full re-review and verification sweep to drive residual risk to a minimum and ensure no known unresolved gaps remain at release time.

This plan intentionally prioritizes internal structural correctness over immediate feature throughput.

## 2) Problem Statement

Current state audit indicates four classes of issues:

- Architecture concentration and coupling in app bootstrap/lifespan paths.
- Governance inconsistencies (new API surface not fully integrated with centralized authz route policy registry).
- Functional incompleteness (intentional TODO stubs for admin APIs).
- Quality-gate debt (lint/type issues and broad skip/xfail surface reducing confidence density).

Without remediation sequencing, feature completion alone risks compounding latent defects and security drift.

## 3) Scope

### In Scope

- Refactor and modularization of startup wiring and route-governance integration.
- Remediation of static quality gates (lint, types, import hygiene).
- Completion of admin API stubs and required service/repository wiring.
- Console/backend contract alignment and connector hardening.
- Full verification pass across unit/integration/security/perf-defined gates.

### Out of Scope

- Net-new product features unrelated to remediation.
- Major infrastructure migration (e.g., replacing DB, framework rewrites).
- Promise of absolute defect absence; objective is zero known unresolved high/critical issues plus explicit residual-risk disclosure.

## 4) Design Principles

1. **Refactor before feature completion**: stabilize architecture and guardrails first.
2. **Fail closed on governance**: no new surface area ships outside route policy registration and explicit authorization semantics.
3. **Single source of truth**: route contracts, RBAC maps, and API docs must be mechanically aligned.
4. **Evidence over assumption**: completion is based on reproducible verification outputs.
5. **No TODO leakage**: no shipping TODO/FIXME markers in remediated paths.

## 5) Target End State

At completion:

- App startup and dependency wiring are decomposed into bounded modules with clear ownership.
- `/api/v1/admin/*` endpoints are fully implemented (no placeholder returns/501s/TODO behavior).
- Admin and webhook route surfaces are represented in the centralized authz route registry.
- Lint/type checks pass cleanly under project standards.
- Console and backend contracts match implemented API semantics.
- Test suite has reduced skip/xfail debt in core critical paths with explicit exceptions documented.
- Final re-review report lists no unresolved critical/high issues and no untriaged findings.

## 6) Sequenced Plan

## Phase 1 - Foundation Refactor (First)

### 1.1 Startup/Lifespan Decomposition

Refactor `api/main.py` bootstrap responsibilities into dedicated modules:

- service container assembly,
- connector lifecycle bootstrapping,
- middleware/router composition,
- optional console/static mount policy.

Deliverable: thinner app factory and lifespan, testable wiring units.

### 1.2 Route Governance Convergence

Integrate all new admin and webhook routes into route registry contracts.

- Add explicit route specs and permissions for `/api/v1/admin/*`.
- Define authorization expectations for admin endpoints (e.g., `admin:*` or stricter).
- Ensure route template keys match FastAPI template form exactly.

Deliverable: no unregistered protected route paths.

### 1.3 Quality Gate Stabilization

- Resolve all current Ruff violations in touched and newly added files.
- Resolve all current mypy errors in touched and newly added files.
- Add targeted tests to prevent regression of fixed defects.

Deliverable: clean static checks for source and tests.

### 1.4 Contract Normalization Hardening

Consolidate domain-row normalization patterns where ORM and domain schemas diverge (e.g., enum casing, nullable/text/list shape normalization).

Deliverable: deterministic conversion adapters with test coverage.

## Phase 2 - Feature Completion (Second)

### 2.1 Admin API Stub Replacement

Replace placeholder behavior in `api/routers/admin.py`:

- dashboard aggregates from persisted data,
- approvals queue and decision mutation via approval service,
- workflow runs list/detail,
- memory namespace listing/purge,
- audit query filters,
- provider summary endpoint,
- API key list/create/revoke with service integration.

Deliverable: all admin endpoints functional with validated response models.

### 2.2 Console Contract Alignment

Align frontend API client/types/pages with actual backend responses:

- remove assumptions that depend on stubbed behavior,
- enforce explicit error/loading states for each page,
- verify routing/auth redirects and API-key handling.

Deliverable: console build and page flows validated against real endpoints.

### 2.3 Connector Reliability and Security Completion

- Confirm signature/header validation paths for Telegram/Discord/Slack.
- Validate command parsing and streaming edit/update behavior.
- Add missing tests for edge and failure modes (invalid signatures, malformed payloads, transient upstream errors).

Deliverable: connector pathways covered with deterministic parser + handler tests.

## Phase 3 - Full Re-Review and Verification (Third)

### 3.1 Full Codebase Re-Audit

Perform structured re-review across:

- code quality,
- security posture,
- performance regressions,
- architecture consistency,
- API/docs contract integrity.

Deliverable: remediation report with all findings triaged and resolved or explicitly accepted.

### 3.2 Verification Matrix (Required)

Run and record results for:

- `ruff check src/ tests/`
- `mypy src/syndicateclaw`
- unit tests (including connector suite)
- integration tests
- security/pentest markers where environment permits
- console build verification
- OpenAPI/route contract checks

Deliverable: evidence bundle (command outputs, pass/fail summary, residual risks).

### 3.3 Exit Criteria

Release candidate accepted only when all are true:

- no unresolved critical/high findings,
- no unresolved TODO/FIXME in remediated scope,
- all quality gates pass,
- all required tests pass or are explicitly waived with rationale,
- docs updated to match implemented behavior.

## 7) Work Breakdown Structure

- **Epic A: Refactor Foundation**
  - A1: main/lifespan modularization
  - A2: route registry and authz integration
  - A3: static gate cleanup
  - A4: domain/ORM adapter normalization
- **Epic B: Feature Completion**
  - B1: admin endpoints implementation
  - B2: console integration hardening
  - B3: connector robustness completion
- **Epic C: Re-Review and Closure**
  - C1: full audit sweep
  - C2: verification matrix execution
  - C3: residual risk closure and sign-off

## 8) Risks and Mitigations

- **Risk**: Refactor introduces behavior drift.
  - **Mitigation**: characterization tests before module extraction and post-refactor parity checks.
- **Risk**: authz route additions break shadow/enforcement assumptions.
  - **Mitigation**: route-registry alignment tests for every new path template.
- **Risk**: feature completion expands scope.
  - **Mitigation**: strict backlog boundaries; defer non-remediation requests.
- **Risk**: test harness/environment flakiness hides defects.
  - **Mitigation**: deterministic local checks + integration reruns + explicit waiver ledger.

## 9) Deliverables

1. Refactored bootstrap architecture with tests.
2. Fully implemented admin API surface.
3. Console/backend contract parity.
4. Connector hardening and extended tests.
5. Final remediation audit report and verification evidence.

## 10) Definition of Done

Done means:

- refactor-first sequencing completed,
- feature-completion phase completed,
- full re-review completed,
- no known unresolved high/critical defects remain,
- all remaining non-critical debt is documented with owner and timeline.

Absolute proof of zero defects is not feasible; this plan instead enforces maximal practical assurance with explicit evidence and no untriaged findings.
