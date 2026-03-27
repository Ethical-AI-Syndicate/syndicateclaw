# Implementation Plan — v1.2.0: LLM Ready

**Sprint Duration:** 4 weeks  
**Branch:** `release/v1.2.0`  
**Spec Reference:** `v1_2_0-llm-ready-revised.md`  
**Depends on:** v1.1.0 shipped; `quality_gate` CI job passing; `system:engine` service account creatable in RBAC

---

## Overview

Four sequential weeks map directly to the four feature pillars: provider abstraction, LLM node handler + idempotency, SSE streaming + auth, and observability + toolcall gating. Each week has an explicit exit gate before the next begins.

---

## Prerequisites

- [ ] v1.1.0 is merged and deployed to staging
- [ ] `SYNDICATECLAW_RBAC_ENFORCEMENT_ENABLED=true` is confirmed working
- [ ] `system:engine` RBAC role assignment plan confirmed: the engine service account needs `run:control` and `tool:execute`
- [ ] Vault/secrets manager has slots for `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`
- [ ] `providers.yaml` template committed to the repo (with `${VAR}` placeholders, not real keys)
- [ ] `jinja2`, `openai`, `anthropic`, `ollama`, `respx` added to `pyproject.toml` dev/runtime dependencies

---

## Week 1 — Provider Abstraction Layer

### Milestone 1.1: Core Types and Protocol

**Owner:** 1 engineer  
**Files:** `syndicateclaw/providers/types.py`

```python
# Message, Tool, CompletionResponse, StreamChunk, ModelInfo types
@dataclass
class Message:
    role: str  # "system" | "user" | "assistant"
    content: str

@dataclass
class CompletionResponse:
    content: str
    tool_calls: list[ToolCall]
    usage: TokenUsage
    latency_ms: int
    model: str
    provider: str

@dataclass
class StreamChunk:
    content: str
    finish_reason: str | None
```

---

### Milestone 1.2: ProviderAdapter Protocol

**Owner:** 1 engineer  
**File:** `syndicateclaw/providers/base.py`

```python
class ProviderAdapter(Protocol):
    async def complete(
        self,
        messages: list[Message],
        model: str,
        tools: list[Tool] | None = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> CompletionResponse | AsyncIterator[StreamChunk]: ...

    async def embed(self, texts: list[str], model: str) -> list[list[float]]:
        raise NotImplementedError  # v1.2.0: stub; no node config exposes embed
```

---

### Milestone 1.3: Config Loader

**Owner:** 1 engineer  
**File:** `syndicateclaw/providers/config.py`

**Tasks:**

1. Implement `interpolate_env_vars(yaml_str: str) -> str`:
   - Regex: `\$\{([A-Z_][A-Z0-9_]*)(?::-(.*?))?\}` to match `${VAR}` and `${VAR:-default}`.
   - For each match: `os.environ.get(var_name, default)`. If no default and var is missing: raise `ConfigurationError(f"Required env var {var_name!r} is not set")`.

2. Implement `load_providers_config(path: str) -> ProviderConfig`:
   - Read YAML file.
   - Run `interpolate_env_vars` before parsing.
   - Validate result with Pydantic `ProviderConfig` model.
   - Raise `ConfigurationError` at startup on any validation failure.

3. Write `test_provider_config_missing_env_var_fatal`: assert `ConfigurationError` raised during load when a required key env var is unset.

---

### Milestone 1.4: Provider Adapters

**Owner:** 1–2 engineers  
**Files:** `syndicateclaw/providers/adapters/`

Implement four adapters, each in its own file:

| Adapter | File | Library | Key behavior |
|---------|------|---------|--------------|
| `OpenAIAdapter` | `openai_adapter.py` | `openai` Python SDK | Map `CompletionResponse` from `choices[0].message`; stream via `AsyncStream` |
| `AnthropicAdapter` | `anthropic_adapter.py` | `anthropic` Python SDK | Map `CompletionResponse` from `content[0].text`; stream via `stream()` context manager |
| `AzureAdapter` | `azure_adapter.py` | `openai` Python SDK with `azure_endpoint` | Same as OpenAI adapter; different client init |
| `OllamaAdapter` | `ollama_adapter.py` | `ollama` Python SDK | Map chat response; stream via generator |

Each adapter's `embed()` raises `NotImplementedError` in v1.2.0.

---

### Milestone 1.5: ProviderRegistry and Routing

**Owner:** 1 engineer  
**File:** `syndicateclaw/providers/registry.py`

```python
class ProviderRegistry:
    def get_adapter(self, model: str) -> ProviderAdapter:
        """Evaluate routing rules top-to-bottom; first match wins.
        Raise UnroutableModelError if no rule matches.
        """
        for rule in self._routing_rules:
            if fnmatch.fnmatch(model, rule.match):
                return self._adapters[rule.provider]
        raise UnroutableModelError(model)
```

Write:
- `test_provider_routing_most_specific_wins`: `claude-sonnet-4-*` must route to Anthropic before `*` catches it. Assert rule order matters.
- `test_provider_routing_default_catchall`: unknown model routes to `openai` via `*` catch-all.

**Exit gate for Week 1:** All provider unit tests pass; `ConfigurationError` raised on missing keys; adapters instantiate without error against mock responses.

---

## Week 2 — LLM Node Handler + Idempotency

### Milestone 2.1: Message Template Engine

**Owner:** 1 engineer  
**File:** `syndicateclaw/llm/templates.py`

```python
from jinja2.sandbox import SandboxedEnvironment
from jinja2 import StrictUndefined

_ENV = SandboxedEnvironment(undefined=StrictUndefined)

def render_messages(
    message_templates: list[dict],
    state: dict,
    context: dict,
    node_outputs: dict,
) -> list[Message]:
    template_context = {
        "state": state,
        "context": context,
        "node_output": node_outputs,
    }
    return [
        Message(
            role=msg["role"],
            content=_ENV.from_string(msg["content"]).render(**template_context),
        )
        for msg in message_templates
    ]
```

Tests:
- `test_llm_handler_message_templating`: `{{ state.input }}` resolves correctly.
- `test_llm_handler_undefined_var_raises`: missing `state.missing` raises `UndefinedError`.
- `test_llm_handler_sandbox_blocks_import`: `{% import os %}` raises `SecurityError`.

---

### Milestone 2.2: Idempotency Store

**Owner:** 1 engineer  
**Files:** `syndicateclaw/llm/idempotency.py`, `migrations/versions/007_idempotency_records.py`

**Migration:**
```python
def upgrade():
    op.create_table(
        "idempotency_records",
        sa.Column("idempotency_key", sa.Text(), primary_key=True),
        sa.Column("request_hash", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("response", postgresql.JSONB(), nullable=False),
        sa.Column("usage", postgresql.JSONB()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
    )
    op.create_index("idx_idempotency_key", "idempotency_records", ["idempotency_key"])
    op.create_index("idx_idempotency_expires", "idempotency_records", ["expires_at"])
```

**IdempotencyStore:**
```python
class IdempotencyStore:
    def make_key(self, run_id: str, node_id: str, attempt: int) -> str:
        return f"{run_id}:{node_id}:{attempt}"

    def compute_hash(self, provider, model, messages, temperature, max_tokens, tools) -> str:
        payload = json.dumps({
            "provider": provider, "model": model, "messages": messages,
            "temperature": temperature, "max_tokens": max_tokens, "tools": tools,
        }, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()

    async def get(self, key: str, request_hash: str) -> CompletionResponse | None: ...
    async def set(self, key: str, request_hash: str, response: CompletionResponse): ...
```

Tests:
- `test_idempotency_dedup_same_attempt`
- `test_idempotency_no_dedup_on_retry`: attempt 1 gets a new key `run:node:1`, not cached.
- `test_idempotency_bypass_cache_flag`
- `test_idempotency_expired_record_ignored`

**Cleanup cron:** Add `syndicateclaw/tasks/idempotency_cleanup.py` as an async function callable from a scheduler or cron:
```python
async def purge_expired_records(session):
    await session.execute(
        "DELETE FROM idempotency_records WHERE expires_at < NOW()"
    )
```

---

### Milestone 2.3: LLM Node Handler

**Owner:** 1–2 engineers  
**File:** `syndicateclaw/orchestrator/handlers/llm.py`

**Handler logic:**
```python
async def llm_handler(node_config: dict, state: dict, context: dict, ...) -> dict:
    # 1. Render messages from templates
    messages = render_messages(node_config["messages"], state, context, node_outputs)

    # 2. Idempotency check
    key = idempotency_store.make_key(context["run_id"], context["node_id"], context["attempt"])
    if not node_config.get("bypass_cache"):
        cached = await idempotency_store.get(key, request_hash)
        if cached:
            audit("llm.cache_hit", ...)
            return {node_config["response_key"]: cached}

    # 3. Get adapter
    adapter = provider_registry.get_adapter(node_config["model"])

    # 4. Call provider (with retry per node's RetryPolicy)
    response = await _call_with_retry(adapter, messages, node_config)

    # 5. Store idempotency record
    await idempotency_store.set(key, request_hash, response)

    # 6. Tag LLM output
    result = response.content
    state[f"_llm_output_{node_config['response_key']}"] = True  # internal tag

    return {node_config["response_key"]: result, "_usage": response.usage}
```

Retry mapping (from spec §5.5):
```python
RETRY_ON: set[int] = {429, 500, 502, 503, 504}
FAIL_IMMEDIATELY: set[int] = {401, 403, 422}
```

**Exit gate for Week 2:** All template and idempotency tests pass; `test_llm_handler_response_storage`, `test_llm_handler_retry_on_429`, `test_llm_handler_immediate_fail_on_401` pass.

---

## Week 3 — SSE Streaming + Token Auth

### Milestone 3.1: Streaming Token Infrastructure

**Owner:** 1 engineer  
**Files:** `migrations/versions/008_streaming_tokens.py`, `syndicateclaw/services/streaming_token_service.py`

**Migration:**
```python
def upgrade():
    op.create_table(
        "streaming_tokens",
        sa.Column("token", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("token_type", sa.Text(), nullable=False, server_default="streaming"),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("used_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("idx_streaming_tokens_run", "streaming_tokens", ["run_id"])
    op.create_index("idx_streaming_tokens_expires", "streaming_tokens", ["expires_at"])
```

**StreamingTokenService:**
```python
class StreamingTokenService:
    async def issue(self, run_id: str, actor: str) -> StreamingToken:
        token = secrets.token_urlsafe(32)
        expires_at = datetime.utcnow() + timedelta(seconds=settings.streaming_token_ttl_seconds)
        await self.repo.insert(token, run_id, actor, expires_at)
        return StreamingToken(token=token, run_id=run_id, expires_at=expires_at)

    async def validate_and_consume(self, token: str, run_id: str) -> str:
        """Returns actor if valid; raises InvalidTokenError if expired, used, or wrong run_id."""
        record = await self.repo.get(token)
        if not record:
            raise InvalidTokenError("Token not found")
        if record.used_at is not None:
            raise InvalidTokenError("Token already used")
        if record.expires_at < datetime.utcnow():
            raise InvalidTokenError("Token expired")
        if record.run_id != run_id:
            raise InvalidTokenError("Token not valid for this run")
        await self.repo.mark_used(token)
        return record.actor
```

Tests:
- `test_streaming_token_single_use`
- `test_streaming_token_scoped_to_run`
- `test_streaming_token_expired`

---

### Milestone 3.2: Streaming Token Endpoint

**Owner:** 1 engineer  
**File:** `syndicateclaw/api/routes/runs.py`

```python
@router.post("/api/v1/runs/{run_id}/streaming-token")
async def issue_streaming_token(
    run_id: str,
    actor: str = Depends(get_current_actor),
    # RBAC: requires run:read — enforced by route registry
):
    token = await streaming_token_service.issue(run_id, actor)
    return {"streaming_token": token.token, "expires_at": token.expires_at.isoformat()}
```

Add to route registry: `("POST", "/api/v1/runs/{id}/streaming-token") → "run:read"`.

---

### Milestone 3.3: SSE Endpoint and ConnectionManager

**Owner:** 1–2 engineers  
**File:** `syndicateclaw/api/routes/streaming.py`, `syndicateclaw/streaming/connection_manager.py`

**ConnectionManager:**
```python
class ConnectionManager:
    _connections: dict[str, set[asyncio.Queue]] = defaultdict(set)

    async def subscribe(self, run_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._connections[run_id].add(q)
        return q

    async def unsubscribe(self, run_id: str, q: asyncio.Queue):
        self._connections[run_id].discard(q)

    async def broadcast(self, run_id: str, event: dict):
        dead = set()
        for q in self._connections.get(run_id, set()):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                dead.add(q)
        for q in dead:
            self._connections[run_id].discard(q)
```

**SSE endpoint:**
```python
@router.get("/api/v1/runs/{run_id}/stream")
async def stream_run(
    run_id: str,
    token: str = Query(...),  # streaming token only; primary JWT rejected
):
    actor = await streaming_token_service.validate_and_consume(token, run_id)
    # Token consumed on connect; reconnect requires new token
    queue = await connection_manager.subscribe(run_id)
    try:
        async def event_generator():
            while True:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                if event.get("type") == "run_complete":
                    yield f"event: run_complete\ndata: {json.dumps(event)}\n\n"
                    break
                yield f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"
        return EventSourceResponse(event_generator())
    finally:
        await connection_manager.unsubscribe(run_id, queue)
```

**Event shape enforcement:** `llm_complete` event must NOT include `response` key (prevents unbounded payloads). Only `usage` and `timestamp` are included. Clients wanting full response must call `GET /api/v1/runs/{id}/nodes/{node_id}`.

---

### Milestone 3.4: Event History Endpoint

**Owner:** 1 engineer  
**File:** `syndicateclaw/api/routes/runs.py`

```python
@router.get("/api/v1/runs/{run_id}/events")
async def get_run_events(
    run_id: str,
    since: datetime | None = Query(None),
    actor: str = Depends(get_current_actor),
    # RBAC: run:read
):
    """Returns paginated audit events for a run since a given timestamp.
    Used by SSE clients to recover missed events after reconnect.
    """
    events = await audit_service.query(
        resource_type="workflow_run",
        resource_id=run_id,
        after=since,
        actor_namespace=actor,
    )
    return {"events": events, "count": len(events)}
```

Add to route registry: `("GET", "/api/v1/runs/{id}/events") → "run:read"`.

**Exit gate for Week 3:** `test_streaming_token_single_use`, `test_streaming_token_scoped_to_run`, `test_sse_streaming_token_required`, `test_sse_reconnect_recovery` all pass. Primary JWT in query param returns 401.

---

## Week 4 — Tool Call Gating + Observability + Documentation

### Milestone 4.1: LLM Tool Call Gating

**Owner:** 1 engineer  
**File:** `syndicateclaw/orchestrator/handlers/llm.py`

**Changes:**

1. Add `allow_tool_calls: bool = False` to LLM node config schema. If `False` and response contains `tool_calls`: discard the `tool_calls`, log `WARN llm.tool_calls_ignored`.

2. If `allow_tool_calls: True` and response contains `tool_calls`:
   ```python
   for tool_call in response.tool_calls:
       tool_name = tool_call.function.name
       # 1. Validate args against tool schema
       try:
           validate_tool_args(tool_name, tool_call.function.arguments)
       except ValidationError as e:
           audit("llm.tool_call_invalid_args", tool_name=tool_name, error=str(e))
           continue  # skip this tool call

       # 2. Run through policy engine with actor=system:engine
       decision = await policy_engine.evaluate(
           actor="system:engine",
           tool=tool_name,
           context={"workflow_run_id": run_id},
       )
       if decision.effect == "DENY":
           audit("llm.tool_call_denied", tool_name=tool_name)
           continue
       if decision.effect == "REQUIRE_APPROVAL":
           # Create approval request; return partial result
           await create_approval_request(tool_name, tool_call.arguments, run_id)
           continue

       # 3. Execute
       audit("llm.tool_call", tool_name=tool_name, args=tool_call.arguments)
       result = await tool_executor.execute(tool_name, tool_call.arguments, context)
       tool_results.append(result)
   ```

3. Write tests: `test_llm_tool_call_requires_opt_in`, `test_llm_tool_call_passes_policy_gate`, `test_llm_tool_call_invalid_args_rejected`.

---

### Milestone 4.2: system:engine RBAC Setup

**Owner:** 1 engineer  
**File:** `syndicateclaw/startup.py` (or equivalent startup hook)

```python
async def configure_system_engine_service_account():
    """Ensure system:engine has required RBAC permissions.
    Called at application startup before serving requests.
    """
    await rbac_service.ensure_role_assignment(
        principal="system:engine",
        permissions=["run:control", "tool:execute"],
    )
```

Add to deployment runbook: "Before deploying v1.2.0, verify `system:engine` service account exists in RBAC with `run:control` and `tool:execute` permissions."

---

### Milestone 4.3: Prometheus Metrics

**Owner:** 1 engineer  
**File:** `syndicateclaw/llm/metrics.py`

```python
from prometheus_client import Counter, Histogram

llm_requests_total = Counter(
    "llm_requests_total",
    "Total LLM API requests",
    labelnames=["provider", "model", "status"],
)

llm_tokens_used_total = Counter(
    "llm_tokens_used_total",
    "Total tokens consumed",
    labelnames=["provider", "model", "token_type"],  # token_type: prompt|completion
)

llm_cost_usd_total = Counter(
    "llm_cost_usd_total",
    "Estimated cost in USD",
    labelnames=["provider", "model"],
)

llm_cache_hits_total = Counter(
    "llm_cache_hits_total",
    "Total idempotency cache hits",
    labelnames=["provider", "model"],
)

llm_request_duration_seconds = Histogram(
    "llm_request_duration_seconds",
    "LLM API request duration",
    labelnames=["provider", "model"],
    buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0],
)
```

Instrument `llm_handler` to call these counters and histograms on every request.

---

### Milestone 4.4: OpenTelemetry Spans

**Owner:** 1 engineer  
**File:** `syndicateclaw/llm/tracing.py`

```python
from opentelemetry import trace

tracer = trace.get_tracer("syndicateclaw.llm")

@contextmanager
def llm_span(provider, model, cached=False):
    with tracer.start_as_current_span("llm.complete") as span:
        span.set_attribute("provider", provider)
        span.set_attribute("model", model)
        span.set_attribute("cached", cached)
        yield span
        # Caller sets prompt_tokens, completion_tokens, latency_ms after response
```

---

### Milestone 4.5: Provider Test Endpoint

**Owner:** 1 engineer  
**File:** `syndicateclaw/api/routes/providers.py`

```python
@router.post("/api/v1/providers/{name}/test")
async def test_provider(
    name: str,
    actor: str = Depends(get_current_actor),
    # RBAC: admin:* — enforced by route registry
):
    try:
        adapter = provider_registry.get_adapter_by_name(name)
        await adapter.complete([Message(role="user", content="ping")], model=adapter.default_model)
        return {"status": "ok", "provider": name}
    except Exception:
        # Generic error — do NOT leak internal topology
        return JSONResponse({"status": "unreachable", "provider": name}, status_code=502)
```

SSRF protection: all provider calls go through existing `validate_url()` via the HTTP client. The test endpoint uses the same client.

---

### Milestone 4.6: CI Secret Management for Provider Tests

Add to `.gitlab-ci.yml`:

```yaml
provider_integration_tests:
  stage: integration
  when: manual
  variables:
    SYNDICATECLAW_CI_PROVIDER_TESTS: "true"
  secrets:
    OPENAI_API_KEY:
      vault: ci/syndicateclaw/openai_api_key@secret
    ANTHROPIC_API_KEY:
      vault: ci/syndicateclaw/anthropic_api_key@secret
  script:
    - pytest tests/ -m requires_api_keys -q --tb=short
```

Mark provider integration tests with `@pytest.mark.requires_api_keys`. Default CI run skips them.

---

## File Map

| File | Action | Description |
|------|--------|-------------|
| `syndicateclaw/providers/types.py` | **Create** | `Message`, `CompletionResponse`, `StreamChunk`, `TokenUsage` |
| `syndicateclaw/providers/base.py` | **Create** | `ProviderAdapter` protocol |
| `syndicateclaw/providers/config.py` | **Create** | `interpolate_env_vars()`, `load_providers_config()` |
| `syndicateclaw/providers/registry.py` | **Create** | `ProviderRegistry` with first-match routing |
| `syndicateclaw/providers/adapters/openai_adapter.py` | **Create** | OpenAI adapter |
| `syndicateclaw/providers/adapters/anthropic_adapter.py` | **Create** | Anthropic adapter |
| `syndicateclaw/providers/adapters/azure_adapter.py` | **Create** | Azure OpenAI adapter |
| `syndicateclaw/providers/adapters/ollama_adapter.py` | **Create** | Ollama adapter |
| `syndicateclaw/llm/templates.py` | **Create** | Jinja2 `SandboxedEnvironment` + `StrictUndefined` template renderer |
| `syndicateclaw/llm/idempotency.py` | **Create** | `IdempotencyStore` with key `{run_id}:{node_id}:{attempt}` |
| `syndicateclaw/llm/metrics.py` | **Create** | Prometheus counters and histograms |
| `syndicateclaw/llm/tracing.py` | **Create** | OTel span context manager |
| `syndicateclaw/orchestrator/handlers/llm.py` | **Modify** | Replace placeholder; full provider call + idempotency + tool gating |
| `syndicateclaw/services/streaming_token_service.py` | **Create** | Issue/validate/consume streaming tokens |
| `syndicateclaw/streaming/connection_manager.py` | **Create** | In-process SSE connection manager |
| `syndicateclaw/api/routes/streaming.py` | **Create** | `GET /api/v1/runs/{id}/stream` endpoint |
| `syndicateclaw/api/routes/runs.py` | **Modify** | Add streaming token endpoint + events endpoint |
| `syndicateclaw/api/routes/providers.py` | **Create** | `GET /api/v1/providers`, `POST /api/v1/providers/{name}/test` |
| `syndicateclaw/startup.py` | **Modify** | Configure `system:engine` RBAC on startup |
| `syndicateclaw/tasks/idempotency_cleanup.py` | **Create** | Purge expired idempotency records |
| `migrations/versions/007_idempotency_records.py` | **Create** | Idempotency table |
| `migrations/versions/008_streaming_tokens.py` | **Create** | Streaming tokens table with `token_type` column |
| `providers.yaml` | **Create** | Template with `${VAR}` placeholders; committed to repo |
| `syndicateclaw/authz/route_registry.py` | **Modify** | Add all new v1.2.0 routes |
| `.gitlab-ci.yml` | **Modify** | Add `provider_integration_tests` job |

---

## Definition of Done

- [ ] Fatal `ConfigurationError` on missing provider API key at startup
- [ ] Routing rules first-match-wins; `claude-*` routes to Anthropic before `*` catch-all
- [ ] `llm` handler calls real providers (≥1 provider tested in manual CI gate)
- [ ] `SandboxedEnvironment` with `StrictUndefined`; sandbox tests pass
- [ ] `allow_tool_calls` defaults to `false`; tool calls gated by policy engine when enabled
- [ ] Idempotency key is `{run_id}:{node_id}:{attempt}`; retries skip cache automatically
- [ ] Streaming tokens: single-use, run-scoped, 5-min TTL; primary JWT in `?token=` returns 401
- [ ] `GET /api/v1/runs/{id}/events?since=` returns missed events
- [ ] `llm_complete` SSE event contains only `usage` + `timestamp`; no full response body
- [ ] All metrics are Counter or Histogram; no mislabeled Gauges
- [ ] `POST /api/v1/providers/{name}/test` requires `admin:*`; error responses contain no internal topology
- [ ] `system:engine` configured with `run:control` + `tool:execute` before deployment
- [ ] All new routes in RBAC route registry
- [ ] Provider integration tests gated behind `SYNDICATECLAW_CI_PROVIDER_TESTS=true`
- [ ] All new modules ≥80% integration test coverage (≥75% for SSE)
- [ ] `ruff` and `mypy` CI gates still passing
