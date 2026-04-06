# SyndicateClaw P0/P1 Remediation Plan

This document contains the concrete, file-level patches required to secure the SyndicateClaw control plane before proceeding with the RBAC Phase 1 rollout.

## 1. SSRF IP-Pinning Patch (fetch.py & ssrf.py)
*Status: P0 (Critical) - DNS Rebinding Vulnerability*

**Issue:** `assert_safe_url` resolves DNS, validates the IP, but then `httpx.AsyncClient` resolves it *again* when connecting. This TOCTOU allows DNS rebinding attacks.

**Fix:** Implement a custom `httpx.AsyncBaseTransport` that connects to the pre-validated IP address while preserving the original hostname for the HTTP `Host` header and TLS SNI.

## 2. LLM Approval Boundary Patch (handlers.py)
*Status: P0 (Critical) - Silent Policy Bypass*

**Issue:** When an LLM tool call requires approval, the handler logs it, appends it to state, and uses `continue` to proceed to the next node without executing the tool. The workflow never actually pauses.

**Fix:** Introduce `WaitForApprovalError`. When `REQUIRE_APPROVAL` is hit, raise this exception. The workflow engine must catch it, persist the `WAITING_APPROVAL` status, and halt execution.

## 3. Workflow Engine Budget Patch (engine.py)
*Status: P0 (Critical) - Infinite Loop DoS*

**Issue:** The `while current_node_id is not None:` loop in `WorkflowEngine.execute` has no cycle detection or step limit. Malicious or poorly authored graphs will OOM the process.

**Fix:** Add a `max_steps` counter and a `visited` set to the execution loop. Raise an exception and transition the run to `FAILED` if bounds are exceeded.

## 4. ORM Mitigation Patch (models.py)
*Status: P1 (High) - Cascading Eager Load OOM*

**Issue:** `WorkflowDefinition.runs` and `WorkflowRun.node_executions` use `lazy="selectin"`. Querying workflows recursively loads the entire execution history of the system.

**Fix:** Change all unbounded 1-to-N relationships to `lazy="raise"` (or `"noload"`). Update specific detail endpoints to use explicit `.options(selectinload(...))` only when required.
