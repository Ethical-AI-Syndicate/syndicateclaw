# SyndicateClaw Failure Modes

This document catalogs known failure scenarios, how they are detected, how the system mitigates them, and what recovery procedures are available.

---

## 1. Database Connection Failure

**Description**: PostgreSQL becomes unreachable — network partition, connection pool exhaustion, or the database process crashes.

**Detection**:
- `pool_pre_ping=True` on the SQLAlchemy engine detects stale connections before use.
- Readiness probe (`GET /readyz`) will report `database: error` and return 503. The liveness probe (`GET /healthz`) will continue to return 200.
- PostgreSQL Docker health check (`pg_isready`) fails, triggering container restart.

**Mitigation**:
- Connection pooling with `pool_size=10`, `max_overflow=20` absorbs transient spikes.
- `pool_pre_ping` recycles dead connections transparently.
- All database sessions are wrapped in `try/except` with automatic rollback in the `get_db_session` dependency.

**Recovery**:
- Once PostgreSQL is reachable again, the connection pool automatically reconnects.
- In-flight requests that encountered the failure will have returned 500/503 to the client and can be retried.
- No data corruption occurs — uncommitted transactions are rolled back.

**Operator action**: Monitor PostgreSQL availability. If the database is down for an extended period, check disk space, replication lag, and connection limits (`max_connections`).

---

## 2. Redis Unavailable

**Description**: The Redis instance is unreachable or has crashed.

**Detection**:
- Redis Docker health check (`redis-cli ping`) fails.
- Memory service logs `memory.cache_read_failed` and `memory.cache_write_failed` warnings.

**Mitigation**:
- **Graceful degradation**: All Redis operations in `MemoryService` are wrapped in try/except blocks. Cache misses fall through to PostgreSQL reads.
- Cache writes that fail are logged and silently skipped — the system operates correctly without caching.
- Cache invalidation failures are logged but do not block the write path.

**Recovery**:
- When Redis returns, the cache is cold. Records are populated on-demand as reads occur.
- Stale cache entries (written before Redis went down and survived a Redis restart with persistence) will be naturally evicted by TTL.

**Operator action**: Check Redis memory usage (`INFO memory`). If Redis was killed by the OOM killer, increase `maxmemory` or configure an eviction policy.

---

## 3. Tool Execution Timeout

**Description**: A tool handler takes longer than its configured `timeout_seconds` to complete.

**Detection**:
- `asyncio.wait_for()` raises `TimeoutError`, caught by `ToolExecutor`.
- `ToolTimeoutError` is raised with the tool name and timeout value.
- A `TOOL_EXECUTION_TIMED_OUT` audit event is emitted with the `ToolExecution` record (including `duration_ms`).

**Mitigation**:
- Per-tool timeout enforcement via `asyncio.wait_for()` (default 30s, configurable per tool).
- The `ToolExecution` record is marked `TIMED_OUT` with error details.
- The `http_request` built-in tool has a secondary httpx client timeout of 25s as a safety margin below the tool-level 30s timeout.

**Recovery**:
- The timed-out tool invocation is recorded in the audit log.
- If the tool is idempotent (`tool.idempotent=True`), it can be safely retried.
- The calling workflow node will fail, triggering its retry policy if configured.

**Operator action**: Review the audit log for recurring timeouts. Increase `timeout_seconds` on the tool definition or investigate the downstream service causing latency.

---

## 4. Workflow Node Failure

**Description**: A node handler raises an unhandled exception during execution.

**Detection**:
- The `WorkflowEngine._execute_node()` method catches all exceptions.
- Logs `node.failed` with `run_id`, `node_id`, `attempt`, and error message.
- `NodeExecution.status` is set to `FAILED` with `error` details.

**Mitigation**:
- **Retry policy**: If the node has a `RetryPolicy`, the engine retries with exponential backoff (`backoff_seconds * backoff_multiplier^attempt`).
- Retries are attempted up to `max_attempts` (default 3).
- Each retry increments `execution.attempt` and is visible in the audit trail.

**Recovery after max retries**:
- `WorkflowRun.status` transitions to `FAILED`.
- `WorkflowRun.error` is set to `"Node {node_id} failed: {error}"`.
- A `WORKFLOW_FAILED` audit event is emitted.
- The run can be replayed from the last checkpoint via `POST /api/v1/workflows/runs/{run_id}/replay`, which resets the run to `PENDING` status and restores the checkpoint state.

**Operator action**: Inspect the `NodeExecution` records for the failed run (`GET /api/v1/workflows/runs/{run_id}/nodes`). Fix the root cause and replay the run.

---

## 5. Approval Timeout

**Description**: A pending approval request passes its `expires_at` deadline without being approved or rejected.

**Detection**:
- `ApprovalService.expire_stale()` queries for requests where `status=PENDING` and `expires_at <= now`.
- An `APPROVAL_EXPIRED` audit event is emitted for each expired request.
- If an approver tries to approve an expired request via the API, the endpoint checks `expires_at`, transitions the status to `EXPIRED`, and returns `410 Gone`.

**Mitigation**:
- Default approval timeout is configurable via `Settings.approval_timeout_seconds` (default 3600s / 1 hour).
- `expire_stale()` should be called periodically (e.g., via a scheduled task or cron).

**Recovery**:
- The associated workflow run remains in `WAITING_APPROVAL` status.
- An operator can create a new approval request or resume the run manually via `POST /api/v1/workflows/runs/{run_id}/resume`.
- The expired approval is preserved in the audit log for compliance.

**Operator action**: Set up a periodic task to call `expire_stale()`. Monitor for workflows stuck in `WAITING_APPROVAL` status.

---

## 6. Policy Engine Unavailable

**Description**: The policy engine cannot be reached or the database query for policy rules fails.

**Detection**:
- `ToolExecutor._check_policy()` checks if `self._policy_engine` is `None` or lacks an `evaluate` method.
- Database errors during rule loading will propagate as exceptions.

**Mitigation**:
- **Fail-closed design**: If the policy engine is `None`, the `ToolExecutor` returns `DENY` and logs `policy_engine.missing`. There is no permissive fallback — the system is fail-closed at every layer.
- The `PolicyEngine.evaluate()` method also defaults to `DENY` when no rules match.
- If the database query for rules fails, the exception propagates up, and the tool execution is blocked.
- The readiness probe (`GET /readyz`) checks for policy engine availability and returns 503 if missing.

**Recovery**:
- Once the database connection is restored, policy evaluation resumes normally.
- No policy decisions are lost — a failed evaluation means no `PolicyDecision` was recorded, so there is no inconsistency.
- The decision ledger records all DENY decisions, including those from missing policy engines, for forensic review.

**Operator action**: Ensure the database is healthy. If policy evaluation is failing, check the `policy_rules` table for corrupt data. Consider caching active rules in Redis to reduce database dependency.

---

## 7. Audit Log Write Failure

**Description**: An audit event cannot be persisted to the database.

**Detection**:
- `AuditMiddleware` catches exceptions from `audit_service.record()` and logs `audit.middleware_record_failed`.
- The `DeadLetterQueue` receives failed events with error context.

**Mitigation**:
- **Non-blocking**: Audit write failures in the middleware do not block the HTTP response. The request continues and the response is returned normally.
- **Database-backed dead letter queue**: Failed events are persisted to the `dead_letter_records` PostgreSQL table immediately, surviving process restarts. Each record includes error classification (`transient` or `permanent`), retry count, and resolution tracking.
- **Error classification**: Errors containing keywords like "validation", "schema", "permission", or "not found" are classified as `permanent` (0 retries). All others are classified as `transient` (3 retries).
- Service-layer audit failures (in `MemoryService`, `PolicyEngine`, `ApprovalService`) are caught and logged but do not block the primary operation.

**Recovery**:
- Call `DeadLetterQueue.retry_all(audit_service)` to retry eligible transient errors. Returns the count of successfully retried events.
- Permanently failed events are marked `FAILED` and require manual resolution via `DeadLetterQueue.resolve(record_id, actor, reason)`.
- Resolution actions are themselves audited with actor attribution.

**Operator action**: Monitor dead letter queue size via `DeadLetterQueue.size()`. Query `dead_letter_records` table for status breakdown. Set up alerts when pending count grows. Dead letter records are durable — they survive process restarts.

---

## 8. Checkpoint Corruption / Tampering

**Description**: The serialized checkpoint data stored on a `WorkflowRun` is corrupted, cannot be deserialized, or has been tampered with.

**Detection**:
- `WorkflowEngine.replay()` calls `json.loads(run.checkpoint_data)`. If the data is corrupt, a `JSONDecodeError` is raised.
- If the checkpoint contains an HMAC envelope (`checkpoint_hmac` field), `_verify_checkpoint_hmac()` recomputes the HMAC-SHA256 and raises `ValueError("Checkpoint integrity check failed: HMAC mismatch")` if the stored and computed signatures differ. This detects both corruption and deliberate tampering.
- The replay operation fails and the run remains in its current status.

**Mitigation**:
- **HMAC signing**: When a signing key is configured, `_persist_checkpoint()` wraps serialized state in a `{"data": ..., "checkpoint_hmac": "<hex>"}` envelope. The HMAC is verified before loading on replay.
- **Fallback to initial state**: If `checkpoint_data` is `None`, the replay resets the run to `PENDING` with its existing `state` (which may be the initial state or the last modified state).
- **Unsigned checkpoint support**: If the checkpoint does not contain an HMAC (legacy or unsigned), it is loaded directly. If the engine has a signing key but the checkpoint has no HMAC, a warning is logged.
- Checkpoint serialization uses `json.dumps(run.state, default=str)` which safely converts non-JSON types to strings.

**Recovery**:
- If checkpoint data is corrupt or tampered, the run can be manually reset by setting `status=PENDING`, clearing `error` and `completed_at`, and providing a clean initial state via the API.
- The original run's node executions are preserved in the audit trail for forensic analysis.
- A tampered checkpoint is a security event and should trigger incident review.

**Operator action**: Enable checkpoint signing by configuring a signing key (derived from the application secret). If HMAC mismatch errors occur, investigate whether the database was directly modified. Monitor for `checkpoint.hmac_present_but_no_key` warnings that indicate a signing configuration mismatch.

---

## 9. Concurrent Run Limit Exceeded

**Description**: The number of active workflow runs exceeds `Settings.max_concurrent_runs` (default 100).

**Detection**:
- The `start_run` API endpoint counts active runs (PENDING, RUNNING, WAITING_APPROVAL) before creating each new run.
- When the limit is reached, `workflow.admission_denied` is logged with active count, max limit, and actor identity.

**Mitigation**:
- **429 response**: When active runs reach `Settings.max_concurrent_runs` (default 100), `POST /{workflow_id}/runs` returns HTTP 429 Too Many Requests with a message showing current/max counts.
- Database connection pool limits (`pool_size=10`, `max_overflow=20`) provide additional backpressure.
- Admission decisions are structured-logged for audit and alerting.

**Recovery**:
- Wait for running workflows to complete, fail, or cancel.
- Operators can cancel stale runs via `POST /api/v1/workflows/runs/{run_id}/cancel`.

**Operator action**: Monitor active run counts. Set up alerts when approaching 80% of `max_concurrent_runs`. Adjust `SYNDICATECLAW_MAX_CONCURRENT_RUNS` if the limit is regularly hit.

---

## 10. Per-Actor Rate Limit Exceeded

**Description**: A single actor sends more requests than the configured sustained or burst rate limit.

**Detection**:
- `RateLimitMiddleware` logs `rate_limit.exceeded` with the actor, count, limit, and whether the breach was `sustained` or `burst`.
- Responses include `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and `X-RateLimit-Reset` headers.

**Mitigation**:
- **429 response**: Returns HTTP 429 with `Retry-After` header when sustained rate (`rate_limit_requests` per `rate_limit_window_seconds`) or burst rate (`rate_limit_burst` per 1-second window) is exceeded.
- Health/docs paths (`/healthz`, `/readyz`, `/docs`, `/openapi.json`, `/redoc`) are exempt.
- Redis-backed sliding window per actor — counts survive across requests but not across Redis restarts.
- **Degradation**: If Redis is unavailable, rate limiting degrades open (allows requests) with a logged warning.

**Recovery**:
- Actor waits for `Retry-After` seconds.
- Operators adjust `SYNDICATECLAW_RATE_LIMIT_REQUESTS`, `SYNDICATECLAW_RATE_LIMIT_WINDOW_SECONDS`, or `SYNDICATECLAW_RATE_LIMIT_BURST` via environment variables.

**Operator action**: Monitor `rate_limit.exceeded` log events. Investigate patterns indicating abuse or misconfigured clients.

---

## 11. Memory Retention Failure

**Description**: The `RetentionEnforcer` fails to purge expired or soft-deleted memory records.

**Detection**:
- `RetentionEnforcer.run()` catches exceptions and records them in `RetentionReport.errors`.
- Logs `retention.enforcement_failed` with the error details.
- `retention.run_complete` log entry includes `expired_count`, `deleted_count`, and `error_count`.

**Mitigation**:
- **Isolated error handling**: The retention sweep catches exceptions and continues. Errors are recorded in the report rather than crashing the process.
- Memory records with `expires_at` in the past are excluded from reads and searches regardless of whether the purge has run.
- A `MEMORY_EXPIRED` audit event is emitted when records are purged.

**Recovery**:
- Retry the retention sweep on the next scheduled run.
- If the database is the root cause, resolve the database issue first.
- Manually run retention by calling `MemoryService.enforce_retention()`.

**Operator action**: Schedule `RetentionEnforcer.run()` as a periodic task (e.g., every hour). Monitor the `RetentionReport` for recurring errors. Alert if `error_count > 0`.

---

## Failure Summary Matrix

| # | Failure | Detection | Impact | Auto-Recovery | Manual Recovery |
|---|---|---|---|---|---|
| 1 | DB connection | pool_pre_ping, health check | All DB ops fail | Pool reconnects | Check PostgreSQL |
| 2 | Redis down | Cache miss warnings | Degraded perf | Cache repopulates | Check Redis memory |
| 3 | Tool timeout | ToolTimeoutError, audit event | Tool invocation fails | Node retry policy | Increase timeout |
| 4 | Node failure | NodeExecution.FAILED | Workflow fails after retries | Retry policy | Replay from checkpoint |
| 5 | Approval timeout | expire_stale(), audit event | Workflow stuck | None | Resume or new approval |
| 6 | Policy unavailable | DENY + readyz 503 | Tool execution blocked (fail-closed) | DB reconnect | Check policy_rules |
| 7 | Audit write fail | DB-backed dead letter queue | Events queued for retry | retry_all() | Monitor dead_letter_records |
| 8 | Checkpoint corrupt | JSONDecodeError | Replay fails | None | Manual state reset |
| 9 | Concurrent limit | 429 on run creation | New runs rejected with count detail | Runs complete | Cancel stale runs |
| 10 | Retention failure | RetentionReport.errors | Stale data persists | Next scheduled run | Manual sweep |
