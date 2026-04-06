# SyndicateClaw CI/CD & Runtime Enforcement Gates

This document operationalizes the control-plane invariants into automated CI/CD checks and runtime canaries to ensure vulnerabilities are not reintroduced.

---

## 1. CI/CD Static Analysis Gates (Fail Build)

### 1.1 SSRF Transport Enforcement
* **Check:** Ban direct instantiation of `httpx.AsyncClient` or `httpx.Client` outside of `syndicateclaw/inference/catalog_sync/fetch.py` and approved connectors.
* **Implementation:** Add a Semgrep or ruff rule to flag `httpx.AsyncClient(...)` without the `transport=PinnedIPAsyncTransport` argument in the core orchestration and inference paths.
* **Why:** Prevents engineers from bypassing the DNS TOCTOU protection during routine feature development.

### 1.2 ORM Relationship Safety
* **Check:** Ban `lazy="selectin"` or `lazy="joined"` on `WorkflowDefinition.runs` and `WorkflowRun.node_executions`.
* **Implementation:** AST analysis script or Semgrep rule in CI.
* **Why:** Prevents accidental reintroduction of catastrophic N+1 or massive eager-loading OOM vectors.

### 1.3 Approval Flow Integrity
* **Check:** Ban `continue` statements inside branches evaluating `PolicyEffect.REQUIRE_APPROVAL`.
* **Implementation:** Semgrep rule enforcing that `REQUIRE_APPROVAL` must result in raising `WaitForApprovalError`.
* **Why:** Ensures the workflow execution boundary remains hard and cannot silently drop tool executions.

---

## 2. Integration Test Invariants (Fail Build)

These tests must pass in the CI pipeline before merging any PR that touches `orchestrator/`, `inference/`, or `db/`.

### 2.1 SSRF Mixed IPv4/IPv6 Resolution
* **Test:** `test_dns_resolution_mixed_ipv4_ipv6_prefers_safe_public`
* **Invariant:** When DNS returns both safe public IPs and internal/link-local IPv6 addresses, the transport must deterministically select the safe public IP or fail closed.

### 2.2 Approval Resume Idempotency
* **Test:** `test_resume_idempotent_no_duplicate_tool_execution`
* **Invariant:** Calling `resume()` twice on an approved run must result in exactly one tool execution. The second call must either safely ignore or raise a state conflict error.

### 2.3 Partial State Persistence
* **Test:** `test_approval_interrupt_preserves_preceding_state_only`
* **Invariant:** When `WaitForApprovalError` is raised, all state mutations prior to the tool call must be persisted. No side-effects or state mutations from the tool itself can exist.

### 2.4 Worker Exhaustion / Concurrency
* **Test:** `test_failed_run_does_not_starve_worker_pool`
* **Invariant:** Submitting 100 concurrent workflows with intentional cycles (`A -> B -> A`) must result in 100 fast failures (`WorkflowCycleDetected`) without degrading the API response time for health checks.

### 2.5 Unbounded Result Set Safety
* **Test:** `test_list_endpoint_does_not_scale_with_total_run_history`
* **Invariant:** A database populated with 1 workflow and 100,000 node executions must return the workflow list endpoint (`GET /api/v1/workflows/`) in constant time (e.g., < 50ms) and bounded memory.

---

## 3. Production Runtime Canaries

These are synthetic workflows run continuously in production to verify control-plane integrity under live conditions.

### 3.1 SSRF Canary
* **Action:** Scheduled workflow attempts to use a tool to fetch `http://169.254.169.254` and a domain configured for DNS rebinding (e.g., using `rbndr.us`).
* **Expected:** Tool execution fails with `SSRFError`. Alert if it succeeds.

### 3.2 Approval Boundary Canary
* **Action:** Scheduled workflow triggers a high-risk tool call configured to require approval.
* **Expected:** Run transitions to `WAITING_APPROVAL`. The tool must not execute. Alert if the run completes or the tool side-effect is observed.

### 3.3 Execution Budget Canary
* **Action:** Scheduled workflow executes a deliberate cycle (`Node A -> Node B -> Node A`).
* **Expected:** Run fails with `WorkflowCycleDetected`. Alert if the run hangs in `RUNNING` or exceeds the maximum execution time.
