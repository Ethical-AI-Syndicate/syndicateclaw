# SyndicateClaw Release Governance & Control Assertions

This document translates engineering patches and tests into **Formal Control Assertions**. These assertions serve as non-negotiable Go/No-Go gates for the RBAC rollout. They shift the security posture from "we implemented a fix" to "we continuously prove the system cannot enter an unsafe state."

---

## 1. Formal Control Assertions

### Control 1: Network Boundary Determinism (SSRF)
**Assertion:** The execution engine CANNOT establish outbound HTTP connections to internal, loopback, or reserved IP spaces under any circumstances.
*   **Static Enforcement (Positive Pattern):** CI pipelines MUST fail if any outbound HTTP client is instantiated without explicitly passing `PinnedIPAsyncTransport`. Banning `httpx.AsyncClient` is insufficient; the AST check must verify the transport injection.
*   **Runtime Canary:** A synthetic workflow attempts to fetch `169.254.169.254` and a DNS rebinding domain every 5 minutes.
*   **Signal Quality:** The canary is only considered "Passed" if it raises exactly `SSRFError`. A generic `Timeout` or `500 Internal Server Error` is considered a **Canary Failure** (false negative).

### Control 2: Control-Plane Interrupts (Approval Boundary)
**Assertion:** A policy decision of `REQUIRE_APPROVAL` MUST immediately halt execution, persist a resume cursor, and prevent any subsequent tool execution in that tick.
*   **Static Enforcement (Positive Pattern):** CI pipelines MUST fail if the `REQUIRE_APPROVAL` branch does not explicitly contain `raise WaitForApprovalError(...)`. Negative checks (banning `continue`) are insufficient as they can be bypassed by `return` or `pass`.
*   **Runtime Canary:** A synthetic workflow triggers a mock high-risk tool. 
*   **Signal Quality:** The canary MUST verify the workflow transitions to `WAITING_APPROVAL` and MUST query the audit ledger to prove the tool's side-effect was NOT executed.

### Control 3: Execution Boundedness
**Assertion:** The execution engine CANNOT be monopolized by cyclic or infinitely expanding graphs.
*   **Static Enforcement (Drift Detection):** CI MUST parse the application configuration and fail the build if `max_steps` exceeds the hard ceiling of `1000`, preventing configuration drift from re-opening the DoS vector.
*   **Runtime Canary:** A synthetic workflow intentionally triggers a `Node A -> Node B -> Node A` cycle.
*   **Signal Quality:** The canary MUST raise exactly `WorkflowCycleDetected` within 5 seconds.

### Control 4: Data-Plane Cardinality (ORM)
**Assertion:** The system CANNOT implicitly load unbounded relationship graphs into memory.
*   **Static Enforcement:** CI MUST ban the string `lazy="selectin"` globally across `db/models.py`. Any legitimate need for eager loading MUST use explicit `.options(selectinload(...))` at the query call-site, combined with `.limit()`.

---

## 2. RBAC Rollout Governance Gates

These controls are strictly bound to the RBAC rollout phases. 

### Gate 0: Pre-Deployment (Unblocks Phase 1)
*   [ ] **CI Enforcement:** Semgrep/AST rules for Controls 1-4 are merged into the main CI pipeline.
*   [ ] **Build Status:** The main branch builds cleanly with zero static analysis violations.
*   [ ] **Test Coverage:** The Integration Test Matrix (`syndicateclaw_test_matrix.md`) is fully implemented and passing.

### Gate 1: Shadow Mode Validity (Unblocks Phase 2/3)
*   [ ] **Canary Isolation:** Runtime canaries are deployed to production under a dedicated `is_canary=True` tenant, completely isolated from billing, standard metrics, and customer logs.
*   [ ] **Signal Cleanliness:** Canaries have run for 7 consecutive days with 100% specific-error success (e.g., catching exactly `SSRFError` and `WorkflowCycleDetected`). Zero false negatives (timeouts/crashes).
*   [ ] **Audit Consistency:** A daily automated query verifies that `decision == execution_outcome` for all tool executions in the ledger. Zero instances of "Approval Required but Executed".

### Gate 3: Hard Enforcement (Unblocks Phase 4 Cutover)
*   [ ] **Drift Detection Active:** Alerting is active for any abnormal distribution of execution steps (e.g., a sudden spike in workflows hitting `max_steps - 1`).
*   [ ] **Idempotency Proven:** No duplicate side-effects observed in production during resume operations.
*   [ ] **Sign-off:** Security / CAB sign-off that the control-plane invariants are holding under real-world adversarial load.
