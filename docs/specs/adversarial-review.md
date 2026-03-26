# Adversarial Spec Review

**Reviewer:** Adversarial analysis mode
**Date:** 2026-03-26
**Scope:** All sprint specs (v1.1.0 → v2.0.0)

---

## v1.1.0 — Hardened Foundations

### RBAC Enforcement

| Issue | Severity | Finding |
|-------|----------|---------|
| **Flag flip is atomic** | Critical | Changing `RBAC_ENFORCEMENT_ENABLED` from `false` to `true` is a hard cutover. No canary, no percentage rollout. If the RBAC evaluator has a bug, *all* access is blocked simultaneously. There's no "log but allow" intermediate state for canary validation. |
| **Migration race condition** | High | If a deployment rolls out with RBAC enforcement enabled *before* the migration adding `scopes` to `api_keys` completes, every API key with empty scopes gets full access — exactly the same as having no RBAC. The migration must complete *before* enforcement is enabled, but nothing enforces this ordering. |
| **Route registry drift** | High | The route registry maps `(method, path)` → `Permission`. If a developer adds a new endpoint and forgets to register it in the route registry, the RBAC evaluator either denies all access (fail-closed) or allows all access (fail-open). The spec says fail-closed, but fail-closed on *missing registration* means new endpoints are inaccessible until someone notices. There's no CI check for "all routes are registered." |
| **Admin role is god mode** | Medium | `admin:*` grants all permissions. In an org with multiple admins, one compromised admin key gives access to everything across all namespaces. There's no scoping — admin is always global. |
| **Scope explosion** | Medium | The permission model uses fine-grained scopes (`workflows:read`, `workflows:write`, `runs:create`, `runs:manage`, `approvals:write`, `policies:write`, `tools:execute`, `memory:read`, `memory:write`, `audit:read`). That's 10+ scopes. Managing them manually is error-prone. There's no grouping or inheritance — `workflows:write` doesn't imply `workflows:read`. |
| **Backward compat leak** | Medium | Empty `scopes` defaults to full access for backward compatibility. This means any existing API key created before v1.1.0 automatically gets god-mode. If keys were created for specific limited purposes, they now have full access until explicitly scoped. |

### Quality Debt

| Issue | Severity | Finding |
|-------|----------|---------|
| **Mypy strict mode** | Medium | The spec says "mypy src passes cleanly" but the current config uses `strict = true`. Strict mypy can require significant type annotation changes that alter public API signatures (return types, generic parameters). The risk of behavioral regression is real, especially around SQLAlchemy model interactions and Pydantic validators. |
| **Ruff rules scope** | Low | The current ruff config selects `["E", "F", "W", "I", "N", "UP", "B", "A", "SIM"]`. This is reasonable but `B` (bugbear) and `SIM` (simplify) can flag existing patterns that are intentional. The spec doesn't address how to handle false positives from newly enabled rules. |

### Integration Tests

| Issue | Severity | Finding |
|-------|----------|---------|
| **Postgres dependency in CI** | Medium | Integration tests require a running PostgreSQL. The CI config uses a service container, but there's no mention of what happens when the service container fails to start (network issue, image pull failure). The test just times out and fails with a cryptic error. |
| **Rollback testing** | Medium | The spec tests RBAC enforcement but doesn't test what happens when you *disable* enforcement mid-operation. If a run is executing when RBAC is toggled, does it complete with old permissions or new? |
| **Coverage gap: cross-tenant** | Medium | The integration tests don't explicitly test cross-tenant access attempts — e.g., Actor A from Org X trying to access Org Y's workflows. This is a critical governance boundary. |

---

## v1.2.0 — LLM Ready

### Provider Abstraction

| Issue | Severity | Finding |
|-------|----------|---------|
| **Provider lock-in in adapter** | Critical | The `ProviderAdapter` protocol defines `complete()` and `embed()`, but each provider has wildly different capabilities. OpenAI has tool-calling, Anthropic has extended thinking, Ollama has local model quirks. A unified protocol either becomes a lowest-common-denominator (losing provider-specific features) or accumulates provider-specific kwargs (breaking abstraction). |
| **Provider config secrets** | Critical | `providers.yaml` uses `${ENV_VAR}` syntax for API keys. If someone accidentally commits `providers.yaml` with real keys instead of env var references, secrets leak to the repo. The spec doesn't mention CI/CD validation that `providers.yaml` doesn't contain literal secrets. |
| **Model routing is brittle** | High | Routing rules match on model name patterns (`model:claude*`). If a provider changes model naming (which they do — Anthropic went from `claude-3` to `claude-sonnet-4`), routing breaks silently. There's no fallback or "model not found" handling in the router. |
| **No provider health checks** | High | The spec defines `POST /api/v1/providers/{name}/test` for manual testing, but no automated health monitoring. If OpenAI's API is down, workflows fail with generic errors. There's no circuit breaker to fail fast to a backup provider. |
| **Cost tracking deferred** | Medium | The spec says cost tracking is deferred to "enterprise tier." But LLM costs can spiral fast. Without basic cost visibility, a misconfigured workflow could rack up hundreds of dollars in a loop. The `llm_cost_usd_total` counter exists but there's no alerting or budget enforcement. |

### LLM Node Handler

| Issue | Severity | Finding |
|-------|----------|---------|
| **Template injection** | Critical | Jinja2-like state interpolation (`{{ state.field_name }}`) is described as "sandboxed" but Jinja2's sandbox mode has known bypasses. If a workflow state contains user-controlled input that gets interpolated into a prompt, prompt injection is trivial. The spec acknowledges prompt injection exists but says "responses go through redaction filter" — redaction only protects *outputs*, not *inputs*. |
| **Max tokens not enforced per-run** | High | `max_tokens` is enforced per-call, but a workflow with 10 LLM nodes and `max_tokens=4096` each could consume 40K tokens. There's no per-run budget. |
| **Idempotency table growth** | High | Idempotency records have a TTL, but the spec says cleanup is a "cron job." If the cron job fails or is misconfigured, the table grows unbounded. A workflow that runs every minute with an LLM call creates 1,440 records/day. At ~1KB each, that's 1.4MB/day — not terrible, but over months it adds up. |
| **Response key collision** | Medium | Multiple LLM nodes storing to `state[response_key]` could overwrite each other. If two nodes both use `response_key: "summary"`, the second overwrites the first. No namespace or prefix isolation. |

### Streaming (SSE)

| Issue | Severity | Finding |
|-------|----------|---------|
| **Connection management leak** | High | The `ConnectionManager` tracks active connections, but if a client disconnects without closing cleanly (mobile app crash, network loss), the connection sits in memory until the next broadcast attempt fails. Under high load with many flaky clients, memory grows. |
| **No replay on reconnect** | Medium | "If you reconnect, you only get events from that point forward." For long-running workflows, a client that disconnects and reconnects loses all events during the gap. There's no event cursor or replay mechanism. |
| **Query parameter auth is weak** | Medium | `?token=<jwt>` for browser EventSource is functional but tokens in URLs get logged in server access logs, browser history, and proxy logs. This is a security risk for long-lived tokens. |

---

## v1.3.0 — Agent Mesh

### Agent Registry

| Issue | Severity | Finding |
|-------|----------|---------|
| **Agent impersonation** | Critical | Any authenticated actor can register an agent with any name. There's no verification that the agent is who it claims to be. A malicious actor registers "research-agent", intercepts messages meant for the legitimate research agent. |
| **Heartbeat DoS** | High | If an attacker sends heartbeats faster than `agent_heartbeat_timeout_seconds`, the agent never goes OFFLINE. This could mask a compromised or unresponsive agent. Rate limiting heartbeats per-agent is not mentioned. |
| **Name uniqueness is namespace-scoped** | Medium | Agent names are unique per namespace. If two orgs both register "triage-agent", cross-namespace messaging requires fully-qualified names. The spec doesn't address how the message router resolves ambiguous names. |

### Messaging Protocol

| Issue | Severity | Finding |
|-------|----------|---------|
| **PostgreSQL as message queue** | Critical | Using PostgreSQL as a message queue is a well-known anti-pattern. Under high message volume, the `agent_messages` table becomes a bottleneck. Locking for at-least-once delivery creates table-level contention. The spec acknowledges "partition if volume grows" but provides no plan for when that threshold is hit. |
| **Message ordering not guaranteed** | High | The spec says "at-least-once" delivery but doesn't guarantee ordering. If Agent A sends messages 1, 2, 3 to Agent B, they could arrive in any order. For workflows that depend on sequential messaging, this is a correctness issue. |
| **Dead letter queue unbounded** | High | Failed messages go to DLQ but there's no mention of DLQ size limits, alerts, or manual resolution process. A misconfigured agent that never ACKs messages could fill the DLQ indefinitely. |
| **Broadcast storm** | Medium | Broadcasting to a namespace with 100 agents means 100 message inserts. With concurrent broadcasts, this could saturate the write path. No batching or fan-out optimization is discussed. |
| **Conversation ID collision** | Medium | `conversation_id` is generated by the sender. If two workflows use the same ID generation logic (timestamp-based), messages could cross-contaminate. No mention of namespace or workflow scoping for conversation IDs. |

### Workflow Versioning

| Issue | Severity | Finding |
|-------|----------|---------|
| **Version history unbounded** | High | The `versions` JSONB column stores all definitions. With frequent edits (CI/CD pushing updates), this grows without limit. A workflow with 500 versions stores 500 definitions in a single JSONB blob. Query performance degrades. |
| **Rollback creates new version** | Medium | "Rollback restores a previous version as latest" — does this create version N+1 from version K, or does it mutate version K? The spec doesn't clarify. If rollback creates a new version, the version history includes the rollback itself, which is confusing. |
| **No diff API implementation detail** | Low | The diff API is mentioned but the diff format isn't specified. JSON diff libraries produce different outputs. Without a canonical format, clients can't reliably display diffs. |

---

## v1.4.0 — Enterprise Runtime

### Scheduling

| Issue | Severity | Finding |
|-------|----------|---------|
| **Scheduler single point of failure** | Critical | The scheduler runs as an asyncio background task. If the process crashes, no new schedules fire until it restarts. The "lock-based HA" mitigates duplicate execution but doesn't address the gap — a crash between checking schedules and executing them means that schedule run is lost. |
| **Cron expression validation** | Medium | The spec says `schedule_value` is a "cron expression" but doesn't specify which cron dialect (POSIX, Quartz, 6-field, 7-field). If users provide invalid expressions, the scheduler could silently skip runs or crash. |
| **Schedule drift under load** | Medium | If the scheduler takes longer than `poll_interval_seconds` to process due schedules, `next_run_at` calculations drift. Over days, a "every hour" schedule could become "every 65 minutes." |
| **No execution deduplication** | Medium | The spec says "optimistic locking via status field" but if two schedulers race on the same schedule, the locking logic isn't detailed. UPDATE with WHERE clause? Advisory locks? The implementation could allow double-execution during the race window. |

### Multi-tenancy

| Issue | Severity | Finding |
|-------|----------|---------|
| **Namespace column nullable** | Critical | The migration adds `namespace` as nullable "initially." If enforcement is enabled before backfill completes, queries filter by `NULL` namespace — returning no results. Users see empty dashboards. If enforcement isn't enabled, the column exists but isn't used — a false sense of security. |
| **Quota enforcement timing** | High | Quotas are checked at creation time, but concurrent requests could all pass the check simultaneously, exceeding the limit. The spec doesn't describe atomic quota counters or optimistic locking. |
| **Org deletion cascade** | Medium | The spec says "soft-delete organization" but doesn't describe what happens to workflows, memory, and agents belonging to that org. Are they orphaned? Deleted? Preserved but inaccessible? |
| **Cross-org admin god-mode** | Medium | The spec says "Cross-namespace access requires admin:* permission." This means any admin can see *all* orgs' data. For a multi-tenant SaaS, this is a dealbreaker — customers won't accept that the platform admin can read their data. |
| **Default org migration** | Medium | Existing resources migrate to namespace `default`. If a user had resources across multiple logical groups (e.g., personal + team), they all collapse into one namespace. Information loss. |

### Performance

| Issue | Severity | Finding |
|-------|----------|---------|
| **Benchmark environment unrealism** | Medium | "4 vCPU, 8GB RAM" is a development machine. Real production environments might have different specs. Benchmarks should be run on the target deployment platform. |
| **Cache invalidation race** | High | The spec says state cache is invalidated on "state update (write-through)" but if two concurrent requests modify the same workflow state, one write could invalidate the cache *after* the other has already read the stale value. |
| **Index migration on large tables** | Medium | Adding indexes to tables with millions of rows (audit_events, agent_messages) during a migration can lock the table and cause downtime. The spec doesn't address concurrent index creation (`CREATE INDEX CONCURRENTLY`). |

---

## v1.5.0 — Developer Experience

### Python SDK

| Issue | Severity | Finding |
|-------|----------|---------|
| **SDK-Server drift** | Critical | The SDK is a separate package. When the server adds a new endpoint or changes an API, the SDK is immediately out of sync. There's no auto-generation from the OpenAPI spec — it's hand-written. Over time, the SDK becomes stale. |
| **LocalRuntime accuracy** | High | The `LocalRuntime` claims to execute workflows in-memory without Postgres. But workflows that use database-backed features (memory, audit, policy) will behave differently locally vs. server. Developers could build confidence in local results that don't match production. |
| **Security: token in URL** | Medium | The SDK's `from_token()` method stores the token. If this token is logged or serialized (e.g., in a debugging session), it leaks. The spec doesn't mention token rotation or short-lived tokens. |
| **No versioning strategy** | Medium | The SDK is on PyPI but there's no mention of semver, deprecation policy, or compatibility matrix with server versions. Users don't know which SDK version works with which server version. |

### Visual Builder

| Issue | Severity | Finding |
|-------|----------|---------|
| **Embedding security** | High | The builder is embedded via iframe with a token in the URL. If the token is long-lived, anyone with the URL gets full API access. No mention of short-lived or scoped builder tokens. |
| **Sync conflicts** | High | If two users edit the same workflow simultaneously, the second save overwrites the first. No conflict detection, no locking, no merge resolution. |
| **React-flow limitations** | Medium | react-flow handles visual graph rendering but complex workflow graphs (100+ nodes) can become unreadable. No mention of subgraph grouping, collapsing, or navigation aids. |
| **Code view parity** | Medium | "Toggle between visual and code views" — but the visual builder might produce JSON that doesn't match what a developer would write by hand. Round-trip fidelity (visual → code → visual) is hard to guarantee. |

### Plugin System

| Issue | Severity | Finding |
|-------|----------|---------|
| **Plugin isolation is weak** | Critical | "Plugins run in a sandboxed context" but the sandbox only provides "read-only state access" and "timeout enforcement." A malicious plugin can still: import arbitrary Python packages, make network calls, access environment variables, read the filesystem. Python doesn't have real sandboxing. |
| **Plugin dependency conflicts** | High | If Plugin A requires `httpx==0.27` and Plugin B requires `httpx==0.28`, they can't coexist in the same process. The spec doesn't address plugin dependency isolation (separate processes, virtual environments, etc.). |
| **Plugin hot-reload** | Medium | The spec loads plugins at startup. Adding a new plugin requires a process restart. No hot-reload, no plugin version management. |
| **Plugin crash impact** | Medium | "Plugin errors don't crash the workflow" — but if a plugin corrupts shared state or raises an unrecoverable exception, the workflow could be in an inconsistent state. |

---

## v2.0.0 — Stable Enterprise

### Security Audit

| Issue | Severity | Finding |
|-------|----------|---------|
| **Audit scope is incomplete** | Medium | The OWASP coverage is a checklist, not an actual penetration test. The spec says "penetration testing scenarios" but doesn't specify who performs them, what tools are used, or what remediation SLA exists. A spec listing attack vectors isn't the same as executing them. |
| **Dependency scanning gaps** | Medium | `pip-audit` checks PyPI packages but doesn't check OS-level dependencies in the Docker image (e.g., `libssl`, `libffi`). A vulnerable `libssl` could be a critical issue that `pip-audit` misses. |
| **Secrets rotation not addressed** | Medium | The spec audits secret *storage* but not secret *rotation*. How do you rotate JWT signing keys? Provider API keys? Database passwords? No rotation strategy means compromised secrets can't be recovered without downtime. |

### Chaos Testing

| Issue | Severity | Finding |
|-------|----------|---------|
| **Testing environment differs from prod** | High | Chaos testing on a development/staging machine doesn't guarantee production behavior. Network partitions in Docker Compose behave differently from real network failures. |
| **Recovery time measurement** | Medium | "Recovery time < 30 seconds after failure removal" — but "failure removal" is ambiguous. Does it mean the service restarts? The database reconnects? Workflows resume? The definition of "recovered" needs precision. |
| **Data loss detection is manual** | Medium | The spec says "no data loss" but doesn't describe how to verify. Running a count query before and after chaos testing? Comparing checksums? Without automated verification, data loss can go undetected. |

### Documentation

| Issue | Severity | Finding |
|-------|----------|---------|
| **ADR completeness** | Low | The spec lists 11 ADRs but doesn't specify format, review process, or status tracking. ADRs that are written after the fact tend to rationalize decisions rather than document trade-offs. |
| **Troubleshooting guide is reactive** | Low | The guide lists known symptoms and fixes but doesn't cover unknown failure modes. A production incident could present symptoms not in the guide. |
| **Upgrade guide assumes backward compat** | Medium | The guide says "existing keys retain full access" but if a user has modified the database schema outside of migrations (manual SQL), alembic could fail. No mention of pre-upgrade validation. |

### Release

| Issue | Severity | Finding |
|-------|----------|---------|
| **No beta/RC period** | Medium | The spec goes from "testing" to "release" with no beta or release candidate period. Enterprise customers expect a soak period where they can test the upgrade on their own infrastructure. |
| **Rollback is lossy** | High | "Data created after the upgrade will be lost" — this is acknowledged but not mitigated. If a user upgrades, creates workflows, then needs to rollback, they lose everything. No export/migration tool. |
| **PyPI publishing is manual** | Low | The spec doesn't automate PyPI publishing. Manual publishing introduces human error (wrong version, wrong package, forgetting to publish). |

---

## Cross-Cutting Concerns

### Architectural

| Issue | Severity | Finding |
|-------|----------|---------|
| **No service mesh** | Medium | As features grow (scheduler, plugins, agents), the architecture becomes a monolith with internal message passing. There's no plan for service decomposition if the monolith becomes unwieldy. |
| **PostgreSQL as single source of truth** | High | Every feature — scheduling, messaging, agents, memory, audit — depends on PostgreSQL. A Postgres failure is a total outage. The spec mentions "graceful Redis degradation" but not "graceful Postgres degradation." |
| **No backup/restore testing** | Medium | The operations docs mention backup but there's no spec for testing backup/restore during the sprint. A backup that can't be restored is worthless. |

### Process

| Issue | Severity | Finding |
|-------|----------|---------|
| **20-week estimate is optimistic** | High | The roadmap assumes 3-4 weeks per sprint. Real-world estimates typically double. A 20-week plan with no buffer for unknowns, rework, or scope creep is likely to slip. |
| **No feature flags** | Medium | Features are either on or off per release. Feature flags (e.g., `SYNDICATECLAW_LLM_ENABLED`) would allow incremental rollout and safer deployment. |
| **No migration testing in CI** | Medium | The upgrade guide describes migration steps but there's no CI job that tests migrations on a copy of production data. Schema changes could fail silently on real data. |

### Testing

| Issue | Severity | Finding |
|-------|----------|---------|
| **Integration tests require external services** | Medium | Tests against "real PostgreSQL" and "real Ollama" mean CI depends on external infrastructure. If the test database is flaky, all CI is flaky. Mock-based tests would be more reliable but less realistic. |
| **No end-to-end tests** | Medium | Unit tests and integration tests cover components, but there's no end-to-end test that covers: create workflow → add schedule → run workflow → agent receives message → approval granted → workflow completes. |
| **Load testing is synthetic** | Medium | Locust tests simulate HTTP requests but don't simulate real-world patterns: long-lived connections, intermittent failures, slow clients, varied payload sizes. |

---

## Summary

| Sprint | Critical | High | Medium | Low |
|--------|----------|------|--------|-----|
| v1.1.0 | 1 | 3 | 5 | 1 |
| v1.2.0 | 3 | 4 | 4 | 0 |
| v1.3.0 | 2 | 4 | 3 | 1 |
| v1.4.0 | 2 | 2 | 8 | 0 |
| v1.5.0 | 2 | 3 | 3 | 0 |
| v2.0.0 | 0 | 1 | 6 | 2 |
| **Total** | **10** | **17** | **29** | **4** |

### Top 5 Critical Issues

1. **v1.2.0: Template injection via Jinja2 interpolation** — User-controlled state values interpolated into prompts without sanitization
2. **v1.3.0: Agent impersonation** — No verification that an agent is who it claims to be
3. **v1.3.0: PostgreSQL as message queue** — Known anti-pattern that won't scale
4. **v1.5.0: Plugin sandbox is fake** — Python can't sandbox; plugins can access everything
5. **v1.2.0: Provider lock-in in adapter protocol** — Unified interface loses provider-specific features

### Recommended Actions

1. **v1.1.0**: Add CI check for route registry completeness. Add canary RBAC rollout mechanism.
2. **v1.2.0**: Use a real sandbox (e.g., RestrictedPython or WASM) for template interpolation. Add provider circuit breakers. Add per-run LLM budget.
3. **v1.3.0**: Add agent identity verification (JWT or signed claims). Evaluate NATS or RabbitMQ for message queue instead of PostgreSQL.
4. **v1.4.0**: Make namespace column required from day one (no nullable migration). Add atomic quota counters.
5. **v1.5.0**: Auto-generate SDK from OpenAPI spec. Run plugins in separate processes for isolation. Add collaborative editing locks for visual builder.
6. **v2.0.0**: Add beta/RC release period. Add automated backup/restore testing. Add feature flags for incremental rollout.

---

*Review generated: 2026-03-26*
