# SyndicateClaw Test Matrix & Release Gates

This document defines the strict testing requirements, failure injection cases, and release gates for the four control-plane remediation PRs.

---

## PR-1: SSRF IP-Pinning & Fetch Hardening

### Unit Tests
* [ ] `test_ssrf_validator_blocks_internal_ips`: Assert 10.0.0.0/8, 169.254.169.254, 127.0.0.1, and IPv6 equivalents raise `SSRFError`.
* [ ] `test_pinned_transport_preserves_host_header`: Assert `PinnedIPAsyncTransport` sets `Host` to the original logical hostname, not the IP literal.
* [ ] `test_pinned_transport_sni_hostname`: Assert `sni_hostname` is passed to the underlying `httpcore` pool for TLS verification.

### Integration Tests
* [ ] `test_fetch_rejects_redirects`: Assert hitting an endpoint that returns 301/302 raises `SSRFError`.
* [ ] `test_fetch_succeeds_public_https`: Assert fetching a known-good public HTTPS endpoint succeeds with the pinned transport.
* [ ] `test_fetch_dns_rebinding_simulation`: Mock `socket.getaddrinfo` to return a safe IP on first call and an internal IP on second call. Assert the connection is made to the safe IP.

### Failure Injection & Rollback
* **Failure Case:** DNS resolution timeout. Assert it fails closed (timeout error, no execution).
* **Rollback Criteria:** Broken legitimate public fetches for catalog sync.

### Release Gate
* Must pass Phase 0 G0.3: No outbound HTTP uses unpinned transport. Redirects disabled.

---

## PR-2: LLM Approval Boundary Enforcement

### Unit Tests
* [ ] `test_process_llm_tool_calls_raises_approval_error`: Assert `_process_llm_tool_calls` raises `WaitForApprovalError` when policy evaluates to `REQUIRE_APPROVAL`.
* [ ] `test_workflow_engine_catches_approval_error`: Assert the engine catches `WaitForApprovalError`, sets status to `WAITING_APPROVAL`, and persists the resume cursor.
* [ ] `test_no_continue_on_require_approval`: Static analysis or AST check to ensure `continue` is not used in the `REQUIRE_APPROVAL` branch.

### Integration Tests
* [ ] `test_workflow_halts_on_approval`: Execute a workflow with a tool requiring approval. Assert the run transitions to `WAITING_APPROVAL` and the tool is *not* executed.
* [ ] `test_workflow_resumes_after_approval`: Resume a `WAITING_APPROVAL` run. Assert it re-enters exactly at the blocked node and executes the tool successfully (assuming approval granted).

### Failure Injection & Rollback
* **Failure Case:** Approval service unavailable during policy evaluation. Assert it fails closed (DENY or ERROR, tool not executed).
* **Rollback Criteria:** Legitimate tool executions blocked incorrectly or inability to resume.

### Release Gate
* Must pass Phase 0 G0.2: `REQUIRE_APPROVAL` halts execution. All approval flows are resumable and idempotent.

---

## PR-3: Workflow Execution Budget & Cycle Control

### Unit Tests
* [ ] `test_engine_enforces_max_steps`: Assert `WorkflowExecutionBudgetExceeded` is raised when `step_count > max_steps`.
* [ ] `test_engine_detects_cycles`: Assert `WorkflowCycleDetected` is raised when a node is visited more than once (strict acyclic enforcement).
* [ ] `test_engine_enforces_time_budget`: Assert execution halts if `time.monotonic() - started > max_execution_seconds`.

### Integration Tests
* [ ] `test_malicious_cyclic_graph_fails_cleanly`: Submit a workflow with an intentional cycle A -> B -> A. Assert the run fails with a cycle detection error and the worker remains healthy.
* [ ] `test_long_acyclic_graph_fails_budget`: Submit a massive linear graph exceeding `max_steps`. Assert it fails cleanly.

### Failure Injection & Rollback
* **Failure Case:** State persistence failure during a budget exception. Assert the worker doesn't crash but the run remains in a terminal/failed state.
* **Rollback Criteria:** Legitimate, complex (but acyclic) workflows hitting the default budget prematurely. (Tune `max_steps` accordingly).

### Release Gate
* Must pass Phase 0 G0.1: Deterministic execution. No infinite loops possible. Bounded step/time execution.

---

## PR-4: ORM `lazy="raise"` Migration & Optimization

### Unit Tests
* [ ] `test_workflow_definition_runs_lazy_raise`: Assert accessing `workflow.runs` without explicit `selectinload` raises `InvalidRequestError`.
* [ ] `test_workflow_run_nodes_lazy_raise`: Assert accessing `run.node_executions` without explicit `selectinload` raises `InvalidRequestError`.

### Integration Tests
* [ ] `test_list_workflows_endpoint_no_n_plus_one`: Execute `GET /api/v1/workflows/`. Assert the number of SQL queries executed is exactly 1 (or 2 if paginated with a count), regardless of the number of runs.
* [ ] `test_get_run_detail_endpoint_loads_nodes`: Execute `GET /api/v1/workflows/runs/{run_id}`. Assert `node_executions` are loaded successfully using explicit `.options(selectinload(...))`.

### Failure Injection & Rollback
* **Failure Case:** Uncaught `InvalidRequestError` in a background task accessing `runs`. Fix the query, do not revert the model.
* **Rollback Criteria:** Catastrophic breakage of core API endpoints that cannot be trivially fixed with `.options()`.

### Release Gate
* Must pass Phase 0 G0.4: No `lazy="selectin"` on unbounded relationships. All list endpoints paginated and optimized.
