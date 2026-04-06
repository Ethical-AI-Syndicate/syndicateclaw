# Implementation Plan — v1.3.0: Agent Mesh

**Sprint Duration:** 4 weeks  
**Branch:** `release/v1.3.0`  
**Spec Reference:** `v1_3_0-agent-mesh-revised.md`  
**Depends on:** v1.2.0 shipped; migration numbering confirmed starting at `009`

---

## Overview

Four sequential weeks: agent registry (with identity enforcement), messaging protocol (with loop protection and subscription model), workflow integration, and versioning. Each week has a hard exit gate. The migration collision with v1.2.0's `008` is resolved by starting all v1.3.0 migrations at `009`.

---

## Prerequisites

- [ ] v1.2.0 deployed; migrations `001`–`008` applied in all environments
- [ ] Alembic migration history reviewed; confirm no pending migrations from previous releases
- [ ] `pytimeparse` added to runtime dependencies (used in v1.4.0 but confirm not needed earlier)
- [ ] `SYNDICATECLAW_MESSAGE_MAX_HOPS` env var slot confirmed in `Settings`
- [ ] New RBAC permissions (`agent:register`, `agent:read`, `agent:manage`, `agent:heartbeat`, `agent:admin`, `message:send`, `message:broadcast`, `message:read`, `message:ack`) added to `PERMISSION_VOCABULARY` in `syndicateclaw/authz/permissions.py`

---

## Week 1 — Agent Registry

### Milestone 1.1: Agent Model and Migration

**Owner:** 1 engineer  
**Files:** `syndicateclaw/models/agent.py`, `migrations/versions/009_agents.py`

**Migration:**
```python
def upgrade():
    op.create_table(
        "agents",
        sa.Column("id", sa.Text(), primary_key=True),           # ULID
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("namespace", sa.Text(), nullable=False),
        sa.Column("capabilities", postgresql.ARRAY(sa.TEXT()), nullable=False, server_default="{}"),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("status", sa.Text(), nullable=False, server_default="OFFLINE"),
        sa.Column("registered_by", sa.Text(), nullable=False),  # server-set; immutable
        sa.Column("heartbeat_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )
    # Uniqueness: name is unique within namespace
    op.create_unique_constraint("uq_agents_name_namespace", "agents", ["name", "namespace"])
    op.create_index("idx_agents_namespace_status", "agents", ["namespace", "status"])
    op.create_index("idx_agents_capabilities", "agents", ["capabilities"], postgresql_using="gin")
```

---

### Milestone 1.2: AgentService

**Owner:** 1 engineer  
**File:** `syndicateclaw/services/agent_service.py`

Key methods:
- `register(name, capabilities, namespace, metadata, actor) -> Agent`: generates ULID id; sets `registered_by = actor`; `status = OFFLINE`; validates `metadata` max 64 keys and 1KB total.
- `heartbeat(agent_id, actor)`: validates `actor == agent.registered_by` OR actor has `agent:admin`; sets `status = ONLINE`, updates `heartbeat_at`.
- `update(agent_id, actor, **fields)`: same ownership check as heartbeat; updates allowed fields (name, capabilities, metadata). `registered_by` is immutable.
- `deregister(agent_id, actor)`: ownership check; sets status to `OFFLINE`; soft-delete (or hard delete — spec leaves open; choose soft).
- `transition_stale_to_offline()`: called by a background task; queries agents where `heartbeat_at < NOW() - INTERVAL '60 seconds'` and `status = ONLINE`; transitions them to `OFFLINE`. Configurable via `SYNDICATECLAW_AGENT_HEARTBEAT_TIMEOUT_SECONDS`.
- `discover(namespace, capability, status, name) -> list[Agent]`: filter by any combination.

---

### Milestone 1.3: Agent API Routes

**Owner:** 1 engineer  
**File:** `syndicateclaw/api/routes/agents.py`

All routes registered in the RBAC route registry per spec §4.2:

```python
@router.post("/api/v1/agents")          # agent:register
@router.get("/api/v1/agents")           # agent:read
@router.get("/api/v1/agents/{id}")      # agent:read
@router.put("/api/v1/agents/{id}")      # agent:manage (ownership enforced in service)
@router.delete("/api/v1/agents/{id}")   # agent:manage (ownership enforced in service)
@router.post("/api/v1/agents/{id}/heartbeat")  # agent:heartbeat (ownership enforced)
```

Heartbeat route: actor validated; `agent_service.heartbeat(agent_id, actor)` enforces ownership.

---

### Milestone 1.4: Heartbeat Background Task

**Owner:** 1 engineer  
**File:** `syndicateclaw/tasks/agent_heartbeat.py`

```python
async def expire_stale_agents():
    """Transition ONLINE agents with stale heartbeats to OFFLINE.
    Called every 30 seconds by the background task runner.
    """
    await agent_service.transition_stale_to_offline()
```

Register as a startup asyncio task (using `asyncio.create_task` in the app lifespan or a background scheduler). Configurable polling interval via `SYNDICATECLAW_AGENT_HEARTBEAT_CHECK_INTERVAL` (default: 30 seconds).

**Tests (spec §11.1):**
- `test_register_agent` — 201 with server-set `registered_by`
- `test_duplicate_name_rejected` — 409 on same name + namespace
- `test_heartbeat_updates_status` — ONLINE after heartbeat
- `test_heartbeat_requires_ownership` — 403 if actor ≠ `registered_by` and no `agent:admin`
- `test_stale_heartbeat_marks_offline` — background task transitions status
- `test_discover_by_capability` — filters correctly
- `test_unauthorized_agent_update` — 403

**Exit gate for Week 1:** All agent registry tests pass; ownership enforced on heartbeat; background task transitions stale agents.

---

## Week 2 — Messaging Protocol

### Milestone 2.1: Migrations

**Owner:** 1 engineer

**Migration 010 — agent_messages:**
```python
op.create_table(
    "agent_messages",
    sa.Column("id", sa.Text(), primary_key=True),
    sa.Column("conversation_id", sa.Text(), nullable=False),
    sa.Column("sender", sa.Text(), nullable=False),      # server-set; never client-set
    sa.Column("recipient", sa.Text()),
    sa.Column("topic", sa.Text()),
    sa.Column("message_type", sa.Text(), nullable=False),
    sa.Column("content", postgresql.JSONB(), nullable=False, server_default="{}"),
    sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
    sa.Column("priority", sa.Text(), nullable=False, server_default="NORMAL"),
    sa.Column("status", sa.Text(), nullable=False, server_default="PENDING"),
    sa.Column("ttl_seconds", sa.Integer(), nullable=False, server_default="3600"),
    sa.Column("hop_count", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("parent_message_id", sa.Text()),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    sa.Column("delivered_at", sa.TIMESTAMP(timezone=True)),
    sa.Column("acked_at", sa.TIMESTAMP(timezone=True)),
    # Computed column: TTL expiry
    # NOTE: PostgreSQL generated column syntax
)
op.execute("""
    ALTER TABLE agent_messages
    ADD COLUMN expires_at TIMESTAMPTZ GENERATED ALWAYS AS
    (created_at + ttl_seconds * INTERVAL '1 second') STORED
""")
# Indexes
op.create_index("idx_messages_recipient_status", "agent_messages", ["recipient", "status"])
op.create_index("idx_messages_topic_status", "agent_messages", ["topic", "status"])
op.create_index("idx_messages_conversation", "agent_messages", ["conversation_id"])
op.create_index("idx_messages_expires", "agent_messages", ["expires_at"],
                postgresql_where=sa.text("status = 'PENDING'"))
op.create_index("idx_messages_sender", "agent_messages", ["sender"])
```

**Migration 011 — topic_subscriptions:**
```python
op.create_table(
    "topic_subscriptions",
    sa.Column("id", sa.Text(), primary_key=True),
    sa.Column("agent_id", sa.Text(), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
    sa.Column("topic", sa.Text(), nullable=False),
    sa.Column("namespace", sa.Text(), nullable=False),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
)
op.create_unique_constraint("uq_topic_subscriptions", "topic_subscriptions", ["agent_id", "topic"])
op.create_index("idx_topic_subs_topic", "topic_subscriptions", ["topic", "namespace"])
```

---

### Milestone 2.2: MessageService and Router

**Owner:** 2 engineers  
**Files:** `syndicateclaw/services/message_service.py`, `syndicateclaw/messaging/router.py`

**Key design points:**

1. **Sender enforcement** — `send(actor, recipient_id, ...)`:
   - Resolve `sender` from the actor: if actor is a registered agent name, use agent name; otherwise use actor string.
   - Override any client-submitted `sender` silently with WARN log: `message.sender_override`.

2. **BROADCAST authorization** — if `message_type == BROADCAST`:
   - Check actor has `message:broadcast` permission (passed in from route handler).
   - Query `topic_subscriptions` for namespace; assert count ≤ 50. If >50 return error.
   - Deliver only to subscribed agents.

3. **Hop limit enforcement in router:**
   ```python
   MAX_HOPS = settings.message_max_hops  # default 10

   async def route(self, message: AgentMessage) -> DeliveryResult:
       if message.hop_count >= MAX_HOPS:
           await self._mark_hop_limit_exceeded(message)
           raise HopLimitExceededError(message.id, message.hop_count)
       # ... continue routing
   ```

4. **Name resolution** — if `recipient` looks like a name (not ULID): resolve to agent ID; log WARN `message.name_routing_used`.

5. **At-least-once delivery** — implement `DeliveryWorker` background task:
   - Polls for `status=PENDING` messages with `expires_at > NOW()`.
   - Attempts delivery (marks `DELIVERED`).
   - On failure: exponential backoff with max 5 attempts.
   - After 5 failures: mark `FAILED`; insert into dead letter queue with `source_type=agent_message`.

---

### Milestone 2.3: Subscription Service

**Owner:** 1 engineer  
**File:** `syndicateclaw/services/subscription_service.py`

```python
async def subscribe(agent_id: str, topic: str, namespace: str, actor: str):
    # Verify actor owns the agent
    agent = await agent_repo.get(agent_id)
    if agent.registered_by != actor:
        raise PermissionError("Cannot subscribe another agent")
    await subscription_repo.insert(agent_id, topic, namespace)

async def unsubscribe(agent_id: str, topic: str, actor: str): ...

async def get_subscribers(topic: str, namespace: str) -> list[Agent]: ...
```

`__broadcast__` is a virtual topic. Subscribing to `__broadcast__` enrolls an agent in namespace broadcasts.

---

### Milestone 2.4: Message API Routes

**Owner:** 1 engineer  
**File:** `syndicateclaw/api/routes/messages.py`

```python
@router.post("/api/v1/messages")         # message:send (or message:broadcast for BROADCAST type)
@router.get("/api/v1/messages")          # message:read (filtered to actor's messages)
@router.get("/api/v1/messages/{id}")     # message:read (own messages only)
@router.post("/api/v1/messages/{id}/ack") # message:ack
@router.post("/api/v1/messages/{id}/reply") # message:send

@router.post("/api/v1/topics/{topic}/subscribe")   # agent:manage
@router.delete("/api/v1/topics/{topic}/subscribe") # agent:manage
@router.get("/api/v1/topics")                       # agent:read
```

All added to RBAC route registry.

**Tests (spec §11.2):** Write all 13 messaging tests. Key tests:
- `test_send_direct_message_sender_enforced`: post with `"sender": "fake"` in body; assert response shows server-set sender; WARN logged.
- `test_broadcast_requires_permission`: actor without `message:broadcast` → 403.
- `test_hop_limit_enforced`: relay message 10 times; 11th relay rejected with DLQ entry.

**Exit gate for Week 2:** All messaging tests pass including broadcast auth, sender enforcement, hop limit, and DLQ behavior.

---

## Week 3 — Workflow Integration

### Milestone 3.1: Agent Node Handler

**Owner:** 1 engineer  
**File:** `syndicateclaw/orchestrator/handlers/agent_send.py`

```python
async def agent_send_handler(node_config: dict, state: dict, context: dict, ...) -> dict:
    # 1. Resolve recipient
    recipient_id = node_config.get("recipient_id")
    recipient_name = node_config.get("recipient_name")
    if not recipient_id and recipient_name:
        # Name-based routing: resolve to ID; log WARN
        agent = await agent_service.get_by_name(recipient_name, namespace=context["namespace"])
        recipient_id = agent.id
        logger.warning("message.name_routing_used", recipient_name=recipient_name, resolved_id=recipient_id)

    # 2. Render content via Jinja2 sandbox (reuse llm template engine)
    content = render_template_dict(node_config["content"], state, context)

    # 3. Generate conversation_id for response matching
    conversation_id = generate_ulid()

    # 4. Send message (sender = system:engine)
    msg = await message_service.send(
        actor="system:engine",
        recipient_id=recipient_id,
        conversation_id=conversation_id,
        message_type=node_config["message_type"],
        content=content,
        priority=node_config.get("priority", "NORMAL"),
    )

    if not node_config.get("wait_for_response", False):
        return {"message_id": msg.id, "conversation_id": conversation_id}

    # 5. Wait for response
    timeout = node_config.get("response_timeout_seconds", 300)
    response = await wait_for_response(
        conversation_id=conversation_id,
        timeout=timeout,
        run_id=context["run_id"],
    )

    if response is None:
        raise AgentResponseTimeoutError(node_id=context["node_id"], timeout=timeout)

    return {node_config["response_key"]: response.content}
```

**`wait_for_response` implementation:** The workflow run transitions to `WAITING_AGENT_RESPONSE`. A periodic background task checks for matching responses and resumes the run. This is the same pattern as `WAITING_APPROVAL`.

---

### Milestone 3.2: WAITING_AGENT_RESPONSE Run Status

**Owner:** 1 engineer

1. Add `WAITING_AGENT_RESPONSE` to `RunStatus` enum in `syndicateclaw/models/workflow_run.py`.
2. Update `max_concurrent_runs` check to include `WAITING_AGENT_RESPONSE` in the count query (spec §6.2).
3. Update `GET /readyz` to report count of runs in each waiting state.
4. Add `resume_on_agent_response` background task: polls for PENDING agent responses matching run conversation_ids; resumes the workflow run.

**Tests (spec §11.3):** Write all four workflow integration tests. `test_agent_node_timeout` verifies the run transitions to `FAILED` with `WAITING_AGENT_RESPONSE_TIMEOUT` error after `response_timeout_seconds`.

**Exit gate for Week 3:** Workflow integration tests pass; `WAITING_AGENT_RESPONSE` counted in run pool; health endpoint reports waiting state counts.

---

## Week 4 — Workflow Versioning

### Milestone 4.1: Versioning Migrations

**Owner:** 1 engineer  
**Files:** `migrations/versions/012_workflow_versions.py`, `migrations/versions/013_workflow_definitions_versioning.py`

**Migration 012 — workflow_versions (separate table):**
```python
op.create_table(
    "workflow_versions",
    sa.Column("id", sa.Text(), primary_key=True),
    sa.Column("workflow_id", sa.Text(),
              sa.ForeignKey("workflow_definitions.id", ondelete="CASCADE"),
              nullable=False),
    sa.Column("version", sa.Integer(), nullable=False),
    sa.Column("definition", postgresql.JSONB(), nullable=False),
    sa.Column("changed_by", sa.Text(), nullable=False),
    sa.Column("changed_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    sa.Column("comment", sa.Text()),
)
op.create_unique_constraint("uq_workflow_version", "workflow_versions", ["workflow_id", "version"])
op.create_index("idx_workflow_versions_wf", "workflow_versions", ["workflow_id", "version"],
                postgresql_ops={"version": "DESC"})
```

**Migration 013 — alter workflow_definitions:**
```python
op.add_column("workflow_definitions", sa.Column("current_version", sa.Integer(), nullable=False, server_default="1"))
op.add_column("workflow_definitions", sa.Column("updated_by", sa.Text()))
```

---

### Milestone 4.2: VersioningService

**Owner:** 1 engineer  
**File:** `syndicateclaw/services/versioning_service.py`

```python
class VersioningService:
    async def create_version(self, workflow_id: str, definition: dict, actor: str, comment: str | None) -> int:
        """Atomically create a new version row and increment current_version."""
        async with session.begin():
            # Get next version number
            result = await session.execute(
                "SELECT current_version FROM workflow_definitions WHERE id = :id FOR UPDATE",
                {"id": workflow_id}
            )
            next_version = result.scalar() + 1

            # Insert version row (unique constraint prevents duplicate)
            await session.execute(
                "INSERT INTO workflow_versions (id, workflow_id, version, definition, changed_by, comment) "
                "VALUES (:id, :wf_id, :v, :def, :actor, :comment)",
                {"id": new_ulid(), "wf_id": workflow_id, "v": next_version,
                 "def": json.dumps(definition), "actor": actor, "comment": comment}
            )

            # Update current_version on parent
            await session.execute(
                "UPDATE workflow_definitions SET current_version = :v, updated_by = :actor "
                "WHERE id = :id",
                {"v": next_version, "actor": actor, "id": workflow_id}
            )

            # Enforce version cap
            await self._enforce_version_cap(session, workflow_id)

            return next_version

    async def _enforce_version_cap(self, session, workflow_id: str, cap: int = 100):
        """Archive and delete oldest versions when count exceeds cap."""
        count = await session.scalar(
            "SELECT COUNT(*) FROM workflow_versions WHERE workflow_id = :id", {"id": workflow_id}
        )
        if count > cap:
            excess = count - cap
            # Archive oldest `excess` versions
            oldest = await session.execute(
                "SELECT * FROM workflow_versions WHERE workflow_id = :id "
                "ORDER BY version ASC LIMIT :n", {"id": workflow_id, "n": excess}
            )
            # Insert into archive table
            # Delete from versions table
            ...

    async def rollback(self, workflow_id: str, target_version: int, actor: str, comment: str | None) -> int:
        """Create a new version with the content of target_version. Does NOT delete history."""
        target = await self.get_version(workflow_id, target_version)
        return await self.create_version(workflow_id, target.definition, actor,
                                          comment or f"Rollback to version {target_version}")

    async def diff(self, workflow_id: str, from_v: int, to_v: int) -> dict:
        """Return structured diff between two versions."""
        v_from = await self.get_version(workflow_id, from_v)
        v_to = await self.get_version(workflow_id, to_v)
        return _compute_workflow_diff(v_from.definition, v_to.definition)
```

---

### Milestone 4.3: Versioning API Routes

**Owner:** 1 engineer  
**File:** `syndicateclaw/api/routes/workflow_versions.py`

```python
@router.get("/api/v1/workflows/{id}/versions")     # workflow:manage
@router.get("/api/v1/workflows/{id}/versions/{v}") # workflow:manage
@router.post("/api/v1/workflows/{id}/rollback")    # workflow:manage — body: {"version": N, "comment": "..."}
@router.get("/api/v1/workflows/{id}/diff")         # workflow:manage — query: ?from=1&to=2
```

Update `PUT /api/v1/workflows/{id}` to call `versioning_service.create_version()` on every update.

Update `POST /api/v1/workflows/{id}/runs` to accept optional `version` parameter; resolve to version definition and store `workflow_version` on the run.

**Tests (spec §11.4):** Write all seven versioning tests. Key: `test_concurrent_update_atomic` must use two concurrent transactions and verify both get distinct version numbers (no lost update).

**Exit gate for Week 4:** All versioning tests pass; concurrent update atomicity confirmed; version cap archives correctly; rollback creates new version without destroying history.

---

## Observability

**Owner:** 1 engineer (Week 4)  
**File:** `syndicateclaw/messaging/metrics.py`

```python
agent_messages_total = Counter("agent_messages_total", "Total messages sent",
                                labelnames=["message_type", "status"])
agent_message_hop_limit_exceeded_total = Counter(
    "agent_message_hop_limit_exceeded_total", "Messages terminated due to hop limit",
    labelnames=["message_type"])
workflow_versions_created_total = Counter(
    "workflow_versions_created_total", "Total workflow versions created",
    labelnames=["namespace"])  # NO workflow_id label — cardinality explosion risk
agent_message_delivery_duration_seconds = Histogram(
    "agent_message_delivery_duration_seconds", "Message delivery latency",
    labelnames=["message_type"])
agents_online = Gauge("agents_online", "Number of agents currently online",
                      labelnames=["namespace"])
```

---

## File Map

| File | Action | Description |
|------|--------|-------------|
| `syndicateclaw/models/agent.py` | **Create** | `Agent` model |
| `syndicateclaw/models/agent_message.py` | **Create** | `AgentMessage` model with `hop_count`, `parent_message_id` |
| `syndicateclaw/models/topic_subscription.py` | **Create** | `TopicSubscription` model |
| `syndicateclaw/models/workflow_version.py` | **Create** | `WorkflowVersion` model |
| `syndicateclaw/services/agent_service.py` | **Create** | Agent CRUD + heartbeat + stale transition |
| `syndicateclaw/services/message_service.py` | **Create** | Message send + delivery + DLQ |
| `syndicateclaw/services/subscription_service.py` | **Create** | Topic subscribe/unsubscribe |
| `syndicateclaw/services/versioning_service.py` | **Create** | Version create + rollback + diff + cap |
| `syndicateclaw/messaging/router.py` | **Create** | `MessageRouter` with hop-limit check |
| `syndicateclaw/messaging/metrics.py` | **Create** | Prometheus metrics |
| `syndicateclaw/orchestrator/handlers/agent_send.py` | **Create** | `AGENT` node handler |
| `syndicateclaw/api/routes/agents.py` | **Create** | Agent API endpoints |
| `syndicateclaw/api/routes/messages.py` | **Create** | Message API endpoints + topic subscription |
| `syndicateclaw/api/routes/workflow_versions.py` | **Create** | Versioning API endpoints |
| `syndicateclaw/models/workflow_run.py` | **Modify** | Add `WAITING_AGENT_RESPONSE` status |
| `syndicateclaw/tasks/agent_heartbeat.py` | **Create** | Stale agent transition background task |
| `syndicateclaw/tasks/message_delivery.py` | **Create** | At-least-once delivery worker |
| `syndicateclaw/tasks/agent_response_resume.py` | **Create** | Resume runs waiting for agent responses |
| `syndicateclaw/authz/permissions.py` | **Modify** | Add agent + message permissions |
| `syndicateclaw/authz/route_registry.py` | **Modify** | Add all new v1.3.0 routes |
| `migrations/versions/009_agents.py` | **Create** | Agent registry table |
| `migrations/versions/010_agent_messages.py` | **Create** | Message queue table |
| `migrations/versions/011_topic_subscriptions.py` | **Create** | Topic subscription table |
| `migrations/versions/012_workflow_versions.py` | **Create** | Workflow versions table |
| `migrations/versions/013_workflow_definitions_versioning.py` | **Create** | Add `current_version`, `updated_by` |

---

## Definition of Done

- [ ] `sender` always server-set; client-submitted sender overridden with WARN log
- [ ] Heartbeat requires ownership; non-owner actor gets 403
- [ ] BROADCAST requires `message:broadcast` permission; limited to subscribed agents; cap at 50
- [ ] All agent and message endpoints registered in RBAC route registry
- [ ] Topic subscriptions have a data model, API, and migration
- [ ] Hop count on every message; router rejects at MAX_HOPS; loop test terminates correctly
- [ ] `WAITING_AGENT_RESPONSE` counted in concurrent run pool
- [ ] Versioning uses separate `workflow_versions` table (not JSONB column)
- [ ] Rollback creates new version; history is preserved
- [ ] Concurrent updates get distinct version numbers (no lost update)
- [ ] Version cap enforces 100 max; oldest archived on overflow
- [ ] `workflow_versions_total` uses `namespace` label only (no `workflow_id`)
- [ ] Migration numbers start at `009` (no collision)
- [ ] All new modules ≥80% integration test coverage
- [ ] `ruff` and `mypy` CI gates still passing
