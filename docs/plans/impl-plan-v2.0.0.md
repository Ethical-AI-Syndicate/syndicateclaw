# Implementation Plan — v2.0.0: Stable Enterprise

**Sprint Duration:** 3 weeks  
**Branch:** `release/v2.0.0`  
**Spec Reference:** `v2_0_0-stable-enterprise-revised.md`  
**Depends on:** v1.5.0 shipped; all migrations `001`–`025` applied; load test baselines from v1.4.0 committed

---

## Overview

Three sequential weeks: security audit + hardening, chaos testing + performance benchmarks, documentation + release. This sprint produces no new features — it is the validation, hardening, and release sprint. The single most important output is a signed-off security audit covering all 26 penetration test scenarios from v1.3.0–v1.5.0 that earlier specs never addressed.

---

## Prerequisites

- [ ] v1.5.0 deployed to staging with all migrations applied
- [ ] `pip-audit` and `bandit` installed in CI and dev environments
- [ ] Chaos testing tooling available (Docker stop/kill commands, network block via `iptables`, disk fill via `dd`)
- [x] Pytest-benchmark smoke baseline committed to `tests/perf/baseline_v2.0.0.json` (Locust/load baselines remain separate)
- [ ] A second scheduler instance available in staging for HA chaos tests
- [ ] All ADR documents (0001–0014) drafted before Week 3 (assign to engineers during Weeks 1–2)
- [ ] react-flow commercial license confirmed resolved (hard block on release if not)
- [ ] `v2.0.0` PyPI package name confirmed reserved

---

## Week 1 — Security Audit and Hardening

### Milestone 1.1: Dependency Scanning

**Owner:** 1 engineer  
**Time estimate:** 0.5 days

```bash
# Run pip-audit — gate: zero critical/high with available patches
pip-audit --fix --dry-run --output json > audit_report.json

# Run bandit — gate: zero high-severity
bandit -r src/ -ll -o bandit_report.json --format json

# Parse and enforce gates
python scripts/check_audit_gates.py audit_report.json bandit_report.json
```

**`check_audit_gates.py` logic:**
- For `pip-audit`: fail if any vulnerability has severity `CRITICAL` or `HIGH` AND a fix is available (`fix_available == true`). CVEs with no available fix: log as accepted risk, do not fail.
- For `bandit`: fail if any issue has `severity: HIGH`.

Add to CI as a `security_scan` job that runs on every merge request and on the release branch.

**Resolve all findings** before proceeding. If a critical/high CVE has no patch, document it as an accepted risk with a mitigation note.

---

### Milestone 1.2: Penetration Testing — Core Scenarios (1–10)

**Owner:** Security engineer or senior backend engineer  
**Time estimate:** 2 days  
**Files:** `tests/security/test_core_pentest.py`

Execute each scenario from spec §4.3 and write an automated regression test where feasible:

| Scenario | Test Method | Pass Criteria |
|----------|-------------|--------------|
| 1. Unauthenticated access | `httpx` requests with no auth header to every endpoint | All return 401 |
| 2. Privilege escalation | MEMBER actor attempts ADMIN operations | All return 403 |
| 3. Cross-org namespace bypass | Org A actor requests Org B resource | 404 (information hiding) |
| 4. SSRF via tools | Submit tool call with private IP URLs | SSRFError; no network attempt |
| 5. Workflow injection | Workflow condition: `__import__('os').system(...)` | SafeEvaluatorError; not executed |
| 6. Memory bomb | POST memory record with 200-level nesting depth | 400; blocked by nesting limit |
| 7. Rate limit bypass | 1000 requests from one actor within window | 429 after threshold; no bypass via concurrent requests |
| 8. Token replay | Capture JWT; wait for expiry; replay | 401 after expiry |
| 9. Audit tampering | Direct DB UPDATE on `audit_events` + try to verify HMAC | HMAC mismatch detected on next read |
| 10. Checkpoint injection | Tamper with `checkpoint_hmac` in DB; attempt replay | Replay raises `ValueError`; run remains failed |

---

### Milestone 1.3: Penetration Testing — v1.3.0 Agent Mesh Scenarios (11–15)

**Owner:** 1 engineer  
**Files:** `tests/security/test_agent_pentest.py`

| Scenario | Implementation | Pass Criteria |
|----------|----------------|--------------|
| 11. Agent impersonation | POST `/api/v1/messages` with `"sender": "billing-agent"` in body | Response shows server-set sender; WARN log emitted |
| 12. BROADCAST without permission | Actor with only `message:send` sends BROADCAST | 403 |
| 13. BROADCAST flood | Actor with `message:broadcast` sends to namespace with 51 subscribed agents | 400 |
| 14. Circular loop terminated | Agent A→B→A→B message chain; verify via hop_count | Message marked HOP_LIMIT_EXCEEDED at hop 10; DLQ entry created |
| 15. Cross-agent prompt injection | Message `content` contains `{{state.secret}}`; delivered to LLM node | Template not re-rendered from message content; LLM output treated as data not template |

---

### Milestone 1.4: Penetration Testing — v1.4.0 Enterprise Scenarios (16–19)

**Owner:** 1 engineer  
**Files:** `tests/security/test_enterprise_pentest.py`

| Scenario | Implementation | Pass Criteria |
|----------|----------------|--------------|
| 16. Scheduler duplicate execution | Two concurrent `SchedulerService` instances; one due schedule | Exactly one run created; confirmed by run count query |
| 17. Namespace NULL bypass | Direct DB insert: `INSERT INTO workflow_definitions (namespace) VALUES (NULL)` | `NOT NULL` constraint violation; PostgreSQL error |
| 18. Quota decorator path variation | POST to `/api/v1/workflows/` (trailing slash), `/api/v1/workflows?org=x`, etc. | Quota enforced on all path variants (FastAPI normalizes trailing slashes) |
| 19. JWT stale permissions | Issue JWT with `org_role=ADMIN`; change actor to VIEWER in DB; use old JWT | Next request resolves fresh permissions from RBAC; VIEWER permissions enforced |

---

### Milestone 1.5: Penetration Testing — v1.5.0 Developer Experience Scenarios (20–26)

**Owner:** 1 engineer  
**Files:** `tests/security/test_dx_pentest.py`

| Scenario | Implementation | Pass Criteria |
|----------|----------------|--------------|
| 20. Plugin state mutation bypass | Plugin attempts `ctx.state["key"] = "x"` | `TypeError` raised; live state unchanged |
| 21. Plugin file-path injection | `plugins.yaml` with `path: /tmp/evil.py` | `PluginConfigError` at startup |
| 22. Plugin async task escape | Plugin class containing `asyncio.create_task(...)` call | `PluginSecurityViolationError` at load time; AST checker rejects it |
| 23. Builder JWT leakage | GET `/api/v1/runs/{id}/stream?token=<primary_jwt>` | 401; only streaming tokens accepted |
| 24. Builder CSRF | PUT `/api/v1/workflows/{id}` without `X-Builder-Token` header | 403 |
| 25. LocalRuntime in production | `SYNDICATECLAW_ENVIRONMENT=production`; `LocalRuntime()` | `RuntimeError` raised |
| 26. WebhookPlugin SSRF | Configure webhook URL `http://10.0.0.1/steal`; trigger workflow end | `SSRFError`; no HTTP request made |

---

### Milestone 1.6: Input Validation Hardening

**Owner:** 1 engineer  
**Time estimate:** 1 day

Walk through all endpoints and verify:

1. **Workflow definition validation:** Ensure `nodes` and `edges` are validated by Pydantic schema before storage. If any path bypasses Pydantic (e.g., raw JSONB insert), add a validation step.

2. **Memory write size validation:** Confirm `SYNDICATECLAW_MEMORY_MAX_VALUE_BYTES` is enforced before DB insert.

3. **Audit event `details` redaction:** Tool call arguments are stored in `audit_events.details` — apply `from_orm_redacted()` to details before storage to prevent credential leakage in audit log.

4. **CORS verification:** Run `GET /api/v1/workflows` with `Origin: https://evil.example.com` header in staging. Assert response does not include `Access-Control-Allow-Origin: *`.

5. **HTTPS-only check:** Verify builder rejects non-HTTPS webhook URLs when `SYNDICATECLAW_ENVIRONMENT=production`.

---

### Week 1 Exit Gate

- [ ] `pip-audit` gate: zero critical/high with available patch
- [ ] `bandit` gate: zero high-severity
- [ ] All 26 penetration test scenarios pass (automated where feasible; manual steps documented)
- [ ] Audit event details redaction confirmed for tool arguments
- [ ] CORS wildcard not present in production responses

---

## Week 2 — Chaos Testing + Performance Benchmarks

### Milestone 2.1: Chaos Test Infrastructure

**Owner:** 1 engineer  
**Directory:** `tests/chaos/`

Set up chaos test harness:
- Docker Compose environment for controlled failure injection
- Helper scripts: `chaos/stop_postgres.sh`, `chaos/stop_redis.sh`, `chaos/fill_disk.sh`, `chaos/block_network.sh`
- Each chaos test: (1) establish baseline load (50 users, 5 min), (2) inject failure, (3) measure during failure, (4) remove failure, (5) measure recovery.

---

### Milestone 2.2: Infrastructure Chaos Tests

**Owner:** 1 engineer  
**File:** `tests/chaos/test_infrastructure_chaos.py`

| Scenario | Failure Method | Pass Criteria |
|----------|---------------|--------------|
| PostgreSQL down | `docker stop postgres` during active workflow | 503 on `/readyz`; no crash; run resumes after DB returns |
| Redis down | `docker stop redis` during API requests | Cache miss warnings; requests succeed; rate limiting degrades open |
| Provider API timeout | Mock provider with 60s delay | LLM node retries 3× with backoff; eventually fails with audit event |
| Provider API 500 | Mock provider returning 500 | Same retry behavior; run fails gracefully |
| Network partition | `iptables -A OUTPUT -p tcp --dport 5432 -j DROP` | Same as PostgreSQL down |
| Disk full | `dd if=/dev/zero of=/tmp/fill bs=1M` until full | Audit events queue in DLQ; error logged; DLQ write failure logged separately; no crash |
| Memory pressure | `stress --vm 1 --vm-bytes 7G` | OOM may trigger; service restarts; run resumes from checkpoint |

**Measurement template for each scenario:**
```python
async def measure_chaos_scenario(failure_fn, recovery_fn, load_fn):
    baseline = await load_fn(duration=60)
    failure_fn()
    during = await load_fn(duration=60)
    recovery_fn()
    recovery_start = datetime.utcnow()
    await wait_for_healthy()
    recovery_time = (datetime.utcnow() - recovery_start).seconds

    assert recovery_time < 30, f"Recovery took {recovery_time}s (limit: 30s)"
    assert await count_lost_runs() == 0, "Data loss detected"
```

---

### Milestone 2.3: Scheduler Chaos Tests

**Owner:** 1 engineer  
**File:** `tests/chaos/test_scheduler_chaos.py`

These are the scenarios not covered in the infrastructure tests:

**Scenario A — DB loss mid-execution:**
```python
async def test_scheduler_db_loss_mid_execution():
    # Create a due schedule
    schedule = await create_due_schedule()

    # Hook: after scheduler claims lock but before run creation, kill DB connection
    with mock.patch("syndicateclaw.services.scheduler_service.workflow_service.start_run",
                    side_effect=stop_db_after_first_call()):
        await scheduler_service._process_due_schedules()

    restart_db()
    await asyncio.sleep(settings.scheduler_lock_lease_seconds + 5)
    await scheduler_service._process_due_schedules()  # Second instance picks up

    runs = await get_runs_for_schedule(schedule.id)
    assert len(runs) == 1, f"Expected 1 run, got {len(runs)}"
```

**Scenario B — Crash after lock:**
```python
async def test_scheduler_crash_after_lock():
    schedule = await create_due_schedule()
    # Manually set locked_by with short expiry (simulate crash scenario)
    await set_schedule_lock(schedule.id, locked_by="dead-instance", locked_until=past_time())

    await scheduler_service._process_due_schedules()

    runs = await get_runs_for_schedule(schedule.id)
    assert len(runs) == 1, "Crashed scheduler's schedule should be recovered exactly once"
```

**Scenario C — Concurrent instances:**
```python
async def test_two_schedulers_no_duplicate():
    schedule = await create_due_schedule()
    instance_a = SchedulerService(instance_id="a")
    instance_b = SchedulerService(instance_id="b")

    # Both instances poll simultaneously
    await asyncio.gather(
        instance_a._process_due_schedules(),
        instance_b._process_due_schedules(),
    )

    runs = await get_runs_for_schedule(schedule.id)
    assert len(runs) == 1, f"Duplicate execution detected: {len(runs)} runs created"
```

---

### Milestone 2.4: Performance Benchmarks

**Owner:** 1 engineer  
**File:** `tests/perf/benchmark_v2.0.0.json`

Run the same Locust scenarios from v1.4.0 against the v1.5.0/v2.0.0 codebase:

```bash
locust -f tests/perf/locustfile.py --headless -u 50 -r 10 --run-time 30m \
    --host https://staging.syndicateclaw.example.com \
    --json > tests/perf/benchmark_v2.0.0.json

# Compare current pytest-benchmark JSON against committed baseline
python scripts/check_benchmark_regression.py \
    benchmark.json \
    tests/perf/baseline_v2.0.0.json
```

Add `benchmark` CI job:
```yaml
benchmark:
  stage: test
  script:
    - pytest tests/perf/ --benchmark-only --benchmark-json=benchmark.json
    - python scripts/check_benchmark_regression.py benchmark.json tests/perf/baseline_v2.0.0.json
  rules:
    - if: '$CI_PIPELINE_SOURCE == "schedule"'
```

---

### Week 2 Exit Gate

- [ ] All 11 chaos scenarios pass: no data loss, recovery <30s, no crashes
- [ ] Scheduler produces exactly 1 run per schedule tick under all three concurrent scenarios
- [ ] Performance benchmarks within 10% of `tests/perf/baseline_v2.0.0.json` (smoke); Locust baselines tracked separately
- [ ] `tests/perf/benchmark_v2.0.0.json` committed to repo
- [ ] Benchmark regression CI job added and passing

---

## Week 3 — Documentation + Release

### Milestone 3.1: ADR Completion

**Owner:** 1 engineer per 2 ADRs (assign during Weeks 1–2; complete in Week 3)  
**Directory:** `docs/adr/`

| ADR | Assigned to | Status check by |
|-----|-------------|----------------|
| 0001–0007 | (review existing; may already be written) | Week 3 Day 1 |
| 0008 — PostgreSQL queue for agent messages | Engineer A | Week 3 Day 2 |
| 0009 — SKIP LOCKED scheduler | Engineer A | Week 3 Day 2 |
| 0010 — Namespace-based multi-tenancy | Engineer B | Week 3 Day 2 |
| 0011 — Plugin sandbox design | Engineer B | Week 3 Day 3 |
| 0012 — Workflow versioning via separate table | Engineer C | Week 3 Day 2 |
| 0013 — Streaming tokens for SSE and builder | Engineer C | Week 3 Day 2 |
| 0014 — LocalRuntime security boundaries | Engineer D | Week 3 Day 3 |

ADR format:
```markdown
# ADR-NNNN: <Title>

**Status:** Accepted  
**Date:** YYYY-MM-DD  
**Deciders:** [names]

## Context
## Decision
## Consequences
## Alternatives Considered
```

---

### Milestone 3.2: API Documentation

**Owner:** 1 engineer  
**Time estimate:** 1 day

1. Verify all FastAPI endpoints have `summary`, `description`, and `response_model` set.
2. Verify every endpoint has at least one request/response example in the docstring.
3. Add a **permission table** to the OpenAPI spec: include the required RBAC permission as a custom extension on each operation (`x-required-permission`).
4. Generate and review `/docs` (Swagger) and `/redoc` for completeness.
5. Verify error codes are documented: add a `GET /api/v1/errors` endpoint or a static section in the OpenAPI spec listing all error codes and their meanings.
6. Verify rate limit documentation: each endpoint description includes rate limit context.

---

### Milestone 3.3: Deployment Guide

**Owner:** 1 engineer  
**File:** `docs/deployment/`

Sections to write or complete:

| Section | Content | Status |
|---------|---------|--------|
| Single-node Docker Compose | Full `docker-compose.yml` with all services; health check verification | Draft in `operations.md` — expand |
| Multi-node | PostgreSQL primary/replica; Redis cluster; load balancer config; multiple API instances | New |
| Kubernetes (Helm chart) | `helm/syndicateclaw/` chart; StatefulSet for PostgreSQL; PVC config; note: NOT an operator | New |
| Scheduler HA | Running multiple scheduler instances; lock lease tuning; monitoring for lock stuck | New |
| Security | TLS config; firewall rules; secrets manager integration; env var guidance | Expand from `operations.md` |
| Monitoring | Prometheus scrape config; Grafana dashboard JSON; alerting rules for all key metrics | New |

---

### Milestone 3.4: Upgrade Guide Testing on Staging

**Owner:** 1 engineer  
**Time estimate:** 1 day

**Test procedure:**

1. Provision a fresh staging environment with v1.0.0 and representative data (100 workflows, 500 runs, 10K audit events, 5 agents).
2. Take a backup: `pg_dump -Fc syndicateclaw_staging > pre_upgrade_backup.dump`.
3. Run: `alembic upgrade head` — confirm all 25 migrations apply cleanly.
4. Verify:
   - All namespace columns are NOT NULL with `default` values
   - v1.0.0 API keys still work (empty scopes = full access)
   - Existing workflows are accessible at version 1
   - `GET /readyz` returns 200
5. Test rollback:
   - Export post-upgrade data as CSV per guide instructions.
   - Stop v2.0.0 service.
   - Restore: `pg_restore -d syndicateclaw_staging pre_upgrade_backup.dump`.
   - Start v1.0.0 service; verify it starts and serves requests.
   - Confirm rollback guide instructions are accurate.
6. Document any gaps between written guide and actual procedure; fix the guide.

---

### Milestone 3.5: Changelog and Release Tag

**Owner:** Release manager  
**Time estimate:** 0.5 days

1. **Fill in the changelog date:** Replace `{RELEASE_DATE}` with the actual date. This must be a checklist item; do not let it ship with a placeholder.
2. **Review changelog completeness:** Every item in the "Added", "Changed", and "Security" sections corresponds to a spec feature.
3. **Create release tag:**
   ```bash
   git tag -a v2.0.0 -m "Release v2.0.0 — Stable Enterprise"
   git push origin v2.0.0
   ```
4. **Build and push Docker image:**
   ```bash
   docker build -t registry.mikeholownych.com/ai-syndicate/syndicateclaw:v2.0.0 .
   docker push registry.mikeholownych.com/ai-syndicate/syndicateclaw:v2.0.0
   ```
5. **Publish SDK to PyPI:**
   ```bash
   cd sdk/
   python -m build
   twine upload dist/* --repository pypi
   ```
6. **Publish release notes** to GitHub Releases or equivalent.

---

## CI Jobs Added in This Sprint

```yaml
security_scan:
  stage: test
  script:
    - pip-audit --fix --dry-run --output json > audit_report.json
    - bandit -r src/ -ll -o bandit_report.json --format json
    - python scripts/check_audit_gates.py audit_report.json bandit_report.json
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
    - if: '$CI_COMMIT_BRANCH == "release/v2.0.0"'

chaos_tests:
  stage: integration
  script:
    - pytest tests/chaos/ -v --tb=short
  when: manual  # Run manually; chaos tests require Docker stop/kill access

benchmark:
  stage: test
  script:
    - pytest tests/perf/ --benchmark-only --benchmark-json=benchmark.json
    - python scripts/check_benchmark_regression.py benchmark.json tests/perf/baseline_v2.0.0.json
  rules:
    - if: '$CI_PIPELINE_SOURCE == "schedule"'

pentest:
  stage: integration
  script:
    - pytest tests/security/ -v --tb=short -m pentest
  rules:
    - if: '$CI_COMMIT_BRANCH == "release/v2.0.0"'
```

---

## File Map

| File | Action | Description |
|------|--------|-------------|
| `scripts/check_audit_gates.py` | **Create** | Parse pip-audit + bandit output; enforce gates |
| `scripts/check_benchmark_regression.py` | **Create** | Compare benchmark JSON against baseline; fail on >10% regression |
| `tests/security/test_core_pentest.py` | **Create** | Pen test scenarios 1–10 |
| `tests/security/test_agent_pentest.py` | **Create** | Pen test scenarios 11–15 (v1.3.0) |
| `tests/security/test_enterprise_pentest.py` | **Create** | Pen test scenarios 16–19 (v1.4.0) |
| `tests/security/test_dx_pentest.py` | **Create** | Pen test scenarios 20–26 (v1.5.0) |
| `tests/chaos/test_infrastructure_chaos.py` | **Create** | 7 infrastructure chaos scenarios |
| `tests/chaos/test_scheduler_chaos.py` | **Create** | 3 scheduler-specific chaos scenarios |
| `tests/chaos/helpers.py` | **Create** | Failure injection helpers |
| `tests/perf/benchmark_v2.0.0.json` | **Create** | Committed benchmark results |
| `docs/adr/0008-postgresql-queue.md` | **Create** | ADR: agent message queue choice |
| `docs/adr/0009-skip-locked-scheduler.md` | **Create** | ADR: scheduler locking |
| `docs/adr/0010-namespace-multitenancy.md` | **Create** | ADR: namespace-based tenancy |
| `docs/adr/0011-plugin-sandbox.md` | **Create** | ADR: plugin sandbox design |
| `docs/adr/0012-workflow-versioning-table.md` | **Create** | ADR: versioning schema |
| `docs/adr/0013-streaming-tokens.md` | **Create** | ADR: streaming token security |
| `docs/adr/0014-local-runtime.md` | **Create** | ADR: LocalRuntime boundaries |
| `docs/deployment/single-node.md` | **Create** | Docker Compose deployment guide |
| `docs/deployment/multi-node.md` | **Create** | Multi-node deployment guide |
| `docs/deployment/kubernetes.md` | **Create** | Helm chart deployment guide |
| `docs/deployment/scheduler-ha.md` | **Create** | Scheduler HA configuration |
| `docs/deployment/security.md` | **Create** | Security hardening guide |
| `docs/deployment/monitoring.md` | **Create** | Prometheus + Grafana setup |
| `helm/syndicateclaw/` | **Create** | Helm chart |
| `CHANGELOG.md` | **Create** | v1.0.0 → v2.0.0 complete changelog |
| `.gitlab-ci.yml` | **Modify** | Add `security_scan`, `chaos_tests`, `benchmark`, `pentest` jobs |

---

## Release Sign-Off Checklist

Each item requires an explicit sign-off from the responsible owner before the release tag is created.

| Item | Owner | Status |
|------|-------|--------|
| `pip-audit` gate passed (zero critical/high with patch) | Security | |
| `bandit` gate passed (zero high-severity) | Security | |
| All 26 pen test scenarios pass | Security | |
| All 11 chaos scenarios pass (no data loss, recovery <30s) | Platform | |
| Scheduler: exactly 1 run per tick under concurrent HA instances | Platform | |
| Benchmarks within 10% of `baseline_v2.0.0.json` (smoke) | Performance | |
| Upgrade guide tested on staging (migration + rollback confirmed) | Platform | |
| Changelog `{RELEASE_DATE}` replaced with actual date | Release Mgr | |
| Changelog reviewed for completeness | Release Mgr | |
| All 14 ADRs written and linked from documentation | Engineering | |
| API docs complete (Swagger/ReDoc) with permission table | Backend | |
| Deployment guide covers single-node, multi-node, Kubernetes | DevOps | |
| react-flow commercial license resolved | Legal | |
| SDK `pyproject.toml` uses compatible version ranges | Backend | |
| Docker image built and pushed | DevOps | |
| `v2.0.0` tag created and pushed | Release Mgr | |
| `syndicateclaw-sdk` published to PyPI | Backend | |
| Release notes published | Release Mgr | |

---

## Definition of Done

- [ ] All 26 penetration test scenarios automated and passing in CI
- [ ] All 11 chaos scenarios documented with pass/fail evidence (screenshots or logs)
- [ ] Scheduler duplicate execution test passes under concurrent HA instances
- [ ] `pip-audit`: zero critical/high with available patches
- [ ] `bandit`: zero high-severity issues
- [ ] Performance benchmarks within 10% of `tests/perf/baseline_v2.0.0.json` (smoke); Locust baselines tracked separately; regression CI job added
- [ ] All 14 ADRs written (0001–0014)
- [ ] API documentation complete with permission table per endpoint
- [ ] Upgrade guide tested on staging: migration succeeds, rollback works, data export procedure verified
- [ ] Upgrade guide includes: explicit backup mandate, data loss warning, export procedure, reconciliation guide
- [ ] Changelog date filled in (no placeholder)
- [ ] react-flow commercial license confirmed resolved
- [ ] `v2.0.0` tag pushed; Docker image at `registry.mikeholownych.com/ai-syndicate/syndicateclaw:v2.0.0`
- [ ] `syndicateclaw-sdk` published to PyPI
