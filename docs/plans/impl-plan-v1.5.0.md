# Implementation Plan — v1.5.0: Developer Experience

**Sprint Duration:** 3 weeks  
**Branch:** `release/v1.5.0`  
**Spec Reference:** `v1_5_0-developer-experience-revised.md`  
**Depends on:** v1.4.0 shipped; migrations `001`–`023` applied

---

## Overview

Three sequential weeks: Python SDK (with streaming token integration, WorkflowBuilder validation, LocalRuntime production guard), visual workflow builder (with builder token auth and CSRF), and plugin system (with enforced `MappingProxyType` sandbox and AST security checker). The plugin sandbox and file-path prohibition are the most critical security tasks.

---

## Prerequisites

- [ ] v1.4.0 deployed; all migrations applied
- [ ] react-flow commercial license reviewed and resolved (block release if not)
- [ ] `jinja2`, `httpx`, `types` already in dependencies (confirm)
- [ ] PyPI account and package namespace `syndicateclaw-sdk` registered
- [ ] `hatchling` and `twine` in dev dependencies for SDK packaging
- [ ] `importlib.metadata` available (Python 3.10+ standard library — confirm Python version)
- [ ] `ast` module available (Python standard library — always available)

---

## Week 1 — Python SDK

### Milestone 1.1: SDK Package Structure

**Owner:** 1 engineer  
**Repo:** New package in `sdk/` directory or a separate `syndicateclaw-sdk` repository

```
syndicateclaw_sdk/
├── __init__.py               # SyndicateClaw client class
├── client.py                 # Core HTTP client (httpx.AsyncClient based)
├── resources/
│   ├── workflows.py          # WorkflowsResource
│   ├── runs.py               # RunsResource + streaming
│   ├── memory.py             # MemoryResource
│   ├── agents.py             # AgentsResource
│   ├── messages.py           # MessagesResource
│   ├── approvals.py          # ApprovalsResource
│   ├── organizations.py      # OrganizationsResource
│   ├── providers.py          # ProvidersResource
│   └── tools.py              # ToolsResource
├── builder.py                # WorkflowBuilder + BuildValidationError
├── local.py                  # LocalRuntime with production guard
├── streaming.py              # Streaming token management
├── exceptions.py             # All SDK exception types
└── py.typed                  # PEP 561 marker
```

---

### Milestone 1.2: Core Client with Version Check

**Owner:** 1 engineer  
**File:** `syndicateclaw_sdk/client.py`

```python
class SyndicateClaw:
    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        token: str | None = None,
        min_server_version: str = "1.5.0",
    ):
        self._http = httpx.AsyncClient(
            base_url=base_url,
            headers=self._build_auth_headers(api_key, token),
            timeout=30.0,
        )
        self._min_server_version = min_server_version
        # Version check at init (sync wrapper for async check)
        asyncio.get_event_loop().run_until_complete(self._check_server_version())

    async def _check_server_version(self):
        resp = await self._http.get("/api/v1/info")
        server_version = resp.json().get("version", "0.0.0")
        if Version(server_version) < Version(self._min_server_version):
            raise IncompatibleServerError(
                required=self._min_server_version,
                actual=server_version,
            )
```

---

### Milestone 1.3: Streaming Token Integration

**Owner:** 1 engineer  
**File:** `syndicateclaw_sdk/streaming.py`

```python
class StreamingSession:
    """Manages streaming token lifecycle for a single SSE connection."""

    async def connect(self, run_id: str) -> AsyncIterator[SSEEvent]:
        while True:
            # 1. Acquire streaming token (never use primary JWT in URL)
            token_resp = await self._client._http.post(
                f"/api/v1/runs/{run_id}/streaming-token"
            )
            streaming_token = token_resp.json()["streaming_token"]

            # 2. Connect to SSE stream with streaming token
            url = f"/api/v1/runs/{run_id}/stream?token={streaming_token}"
            async with self._client._http.stream("GET", url) as response:
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        event = parse_sse_event(line)
                        yield event
                        if event.type == "run_complete":
                            return

            # 3. On disconnect (before run_complete): loop and re-acquire token
            # Token is consumed on first connection; new one needed for reconnect
```

---

### Milestone 1.4: WorkflowBuilder with Validation

**Owner:** 1 engineer  
**File:** `syndicateclaw_sdk/builder.py`

```python
class WorkflowBuilder:
    def decision(self, node_id: str, condition: str,
                 true_branch: Callable, false_branch: Callable) -> "WorkflowBuilder":
        # Both branches required at call time
        if true_branch is None or false_branch is None:
            raise BuildValidationError(
                f"Decision node {node_id!r} requires both true_branch and false_branch"
            )
        # Validate condition string against safe evaluator grammar
        try:
            _validate_condition_syntax(condition)
        except SyntaxError as e:
            raise BuildValidationError(f"Invalid condition expression in {node_id!r}: {e}")
        # Record both branches
        ...

    def build(self) -> WorkflowDefinition:
        """Validate and return the complete workflow definition.
        Raises BuildValidationError on any validation failure.
        """
        self._validate_single_start_node()
        self._validate_at_least_one_end_node()
        self._validate_no_disconnected_subgraphs()
        self._validate_all_node_ids_unique()
        self._validate_against_json_schema()
        return WorkflowDefinition(nodes=self._nodes, edges=self._edges, ...)
```

`_validate_condition_syntax`: import and use `syndicateclaw.orchestrator.condition_parser._ConditionParser` from the server codebase if co-located, or re-implement the same grammar validator in the SDK.

---

### Milestone 1.5: LocalRuntime with Production Guard

**Owner:** 1 engineer  
**File:** `syndicateclaw_sdk/local.py`

```python
import os
import warnings

_PRODUCTION_ENVS = {"production", "prod", "staging"}
_DEV_ENVS = {"development", "dev", "test", "testing"}

BYPASSED_CONTROLS = [
    "Policy engine — all tools are allowed (no DENY decisions)",
    "Audit service — no audit trail for local executions",
    "RBAC — no permission checks",
    "Approval system — APPROVAL nodes auto-approve",
    "Tool executor sandbox — no SSRF or payload checks",
    "Database persistence — run state is in-memory only",
]

class LocalRuntime:
    def __init__(self):
        env = os.environ.get("SYNDICATECLAW_ENVIRONMENT", "production").lower()

        if env in _PRODUCTION_ENVS:
            raise RuntimeError(
                "LocalRuntime cannot be constructed in production environments "
                f"(SYNDICATECLAW_ENVIRONMENT={env!r}). "
                "Use the full SyndicateClaw client with a server instead."
            )

        warning_msg = (
            "\n⚠️  LocalRuntime bypasses the following security controls:\n"
            + "\n".join(f"  - {c}" for c in BYPASSED_CONTROLS)
            + "\nWorkflows tested with LocalRuntime may behave differently in production."
        )
        warnings.warn(warning_msg, UserWarning, stacklevel=2)

    def execute(self, workflow: WorkflowDefinition, input_state: dict) -> RunResult:
        """Execute workflow in-memory with no security controls."""
        # In-memory graph traversal only
        ...
```

---

### Milestone 1.6: Exception Types

**Owner:** 1 engineer  
**File:** `syndicateclaw_sdk/exceptions.py`

```python
class SyndicateClawError(Exception): pass
class WorkflowNotFoundError(SyndicateClawError): pass
class ToolDeniedError(SyndicateClawError):
    def __init__(self, reason: str): self.reason = reason
class ApprovalRequiredError(SyndicateClawError): pass
class RateLimitError(SyndicateClawError):
    def __init__(self, retry_after: int): self.retry_after = retry_after
class AuthenticationError(SyndicateClawError): pass
class QuotaExceededError(SyndicateClawError):
    def __init__(self, quota: str, limit: int, current: int): ...
class IncompatibleServerError(SyndicateClawError):
    def __init__(self, required: str, actual: str): ...
class BuildValidationError(SyndicateClawError): pass
```

**Tests (spec §9.1):** Write all 14 SDK tests. Key: `test_sdk_local_runtime_production_guard` sets `SYNDICATECLAW_ENVIRONMENT=production` and asserts `RuntimeError`.

**Exit gate for Week 1:** SDK installs via `pip install -e sdk/`; version check tested; streaming token flow tested; LocalRuntime guard tested; `WorkflowBuilder.build()` raises on missing branches.

---

## Week 2 — Visual Workflow Builder

### Milestone 2.1: Builder Token Infrastructure

**Owner:** 1 engineer  
**Files:** `migrations/versions/025_builder_token_type.py`, `syndicateclaw/services/builder_token_service.py`

**Migration 025:**
```python
def upgrade():
    op.add_column("streaming_tokens",
        sa.Column("token_type", sa.Text(), nullable=False, server_default="streaming"))
    op.create_index("idx_streaming_tokens_type", "streaming_tokens", ["token_type"])
```

**BuilderTokenService:**
```python
class BuilderTokenService:
    async def issue(self, workflow_id: str, actor: str) -> BuilderToken:
        token = secrets.token_urlsafe(32)
        expires_at = datetime.utcnow() + timedelta(seconds=settings.builder_token_ttl_seconds)
        await repo.insert(
            token=token,
            run_id=None,             # not a run token
            actor=actor,
            token_type="builder",
            workflow_id=workflow_id, # add to streaming_tokens table
            expires_at=expires_at,
        )
        return BuilderToken(token=token, workflow_id=workflow_id, expires_at=expires_at)

    async def validate(self, token: str, workflow_id: str) -> str:
        """Returns actor. Raises InvalidTokenError if wrong workflow, expired, or wrong type."""
        record = await repo.get(token)
        if not record or record.token_type != "builder":
            raise InvalidTokenError("Not a builder token")
        if record.workflow_id != workflow_id:
            raise InvalidTokenError("Token not valid for this workflow")
        if record.expires_at < datetime.utcnow():
            raise InvalidTokenError("Token expired")
        return record.actor
        # Builder tokens are NOT single-use (unlike streaming tokens)
        # They are valid for the TTL window to support save operations
```

Note: add `workflow_id` column to `streaming_tokens` table in migration 025 to support builder token scoping.

---

### Milestone 2.2: Builder Token Endpoint

**Owner:** 1 engineer  
**File:** `syndicateclaw/api/routes/workflows.py`

```python
@router.post("/api/v1/workflows/{id}/builder-token")
async def issue_builder_token(
    id: str,
    actor: str = Depends(get_current_actor),
    # RBAC: workflow:manage
):
    token = await builder_token_service.issue(workflow_id=id, actor=actor)
    return {"builder_token": token.token, "expires_at": token.expires_at.isoformat()}
```

Add to RBAC route registry: `("POST", "/api/v1/workflows/{id}/builder-token") → "workflow:manage"`.

---

### Milestone 2.3: CSRF Protection Middleware

**Owner:** 1 engineer  
**File:** `syndicateclaw/middleware/csrf.py`

```python
class BuilderCSRFMiddleware(BaseHTTPMiddleware):
    """Require X-Builder-Token header for state-modifying builder requests."""

    BUILDER_WRITE_PATHS = {
        ("PUT", "/api/v1/workflows/"),  # Save workflow via builder
    }

    async def dispatch(self, request: Request, call_next):
        if self._is_builder_write(request):
            builder_token = request.headers.get("X-Builder-Token")
            if not builder_token:
                return JSONResponse({"detail": "X-Builder-Token header required"}, status_code=403)
            # Validate the builder token (workflow_id from path)
            workflow_id = request.path_params.get("id")
            try:
                await builder_token_service.validate(builder_token, workflow_id)
            except InvalidTokenError:
                return JSONResponse({"detail": "Invalid or expired builder token"}, status_code=403)
        return await call_next(request)
```

---

### Milestone 2.4: React Builder App

**Owner:** 1 engineer (frontend)  
**Directory:** `syndicateclaw/static/builder/`

**Tech stack:** React 18, react-flow (after license resolution), Monaco editor.

**Build output:** Bundled to `syndicateclaw/static/builder/index.html` + assets. Served by FastAPI's `StaticFiles` mount.

**Key security requirements:**
1. Builder fetches a builder token from the server at page load (token in server-side session or meta tag — never in URL).
2. All `PUT` requests to save include `X-Builder-Token: <token>` header.
3. SSE streaming uses `POST /api/v1/runs/{id}/streaming-token` → connects to `GET .../stream?token=<streaming_token>` (same pattern as SDK).
4. Builder token is stored in memory only (not in localStorage — per platform policy).

**API endpoints served:**
```python
@router.get("/builder/{workflow_id}")
@router.get("/builder/new")
async def serve_builder(workflow_id: str | None = None):
    # Serve React app; builder token issued server-side and injected into page
    return FileResponse("syndicateclaw/static/builder/index.html")
```

**Tests (spec §9.2):**
- `test_builder_serves_html`
- `test_builder_requires_builder_token` (API-level: PUT without X-Builder-Token → 403)
- `test_builder_token_scoped_to_workflow`
- `test_builder_token_expires`
- `test_builder_csrf_protection`

**Exit gate for Week 2:** Builder token tests pass; CSRF protection test passes; react-flow license confirmed resolved.

---

## Week 3 — Plugin System

### Milestone 3.1: Plugin Interface

**Owner:** 1 engineer  
**File:** `syndicateclaw/plugins/base.py`

```python
import types
import copy

class PluginContext:
    def __init__(self, run_id: str, workflow_id: str, actor: str, namespace: str, state: dict):
        self._run_id = run_id
        self._workflow_id = workflow_id
        self._actor = actor
        self._namespace = namespace
        self._state_snapshot = copy.deepcopy(state)  # deep copy before wrapping

    @property
    def state(self) -> types.MappingProxyType:
        """Read-only deep copy of workflow state.
        Mutation attempts raise TypeError.
        """
        return types.MappingProxyType(self._state_snapshot)

    # Expose other context fields as read-only properties
    @property
    def run_id(self) -> str: return self._run_id
    @property
    def workflow_id(self) -> str: return self._workflow_id


class Plugin:
    name: str
    version: str

    async def on_workflow_start(self, ctx: PluginContext) -> None: pass
    async def on_node_execute(self, ctx: PluginContext, node_id: str, result: Any) -> None: pass
    async def on_workflow_end(self, ctx: PluginContext, status: str) -> None: pass
    async def on_error(self, ctx: PluginContext, error: Exception) -> None: pass
```

---

### Milestone 3.2: AST Security Checker

**Owner:** 1 engineer  
**File:** `syndicateclaw/plugins/security.py`

```python
import ast
import inspect

BANNED_NAMES = {
    "create_task", "ensure_future",   # asyncio task spawning
    "Thread", "Process",              # threading/multiprocessing
    "system", "popen", "run",        # subprocess/os execution
    "exec", "eval", "compile",        # code execution
}

BANNED_IMPORTS = {
    "asyncio", "threading", "multiprocessing",
    "subprocess", "os", "sys", "importlib",
}

def check_plugin_security(plugin_class: type) -> None:
    """Inspect plugin source with AST. Raise PluginSecurityViolationError on banned patterns."""
    try:
        source = inspect.getsource(plugin_class)
        tree = ast.parse(source)
    except (OSError, SyntaxError) as e:
        raise PluginSecurityViolationError(f"Cannot inspect plugin source: {e}")

    for node in ast.walk(tree):
        # Check for banned function calls
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute) and node.func.attr in BANNED_NAMES:
                raise PluginSecurityViolationError(
                    f"Plugin uses banned call: {node.func.attr}. "
                    f"Async task spawning, threading, and subprocess are not permitted."
                )
            if isinstance(node.func, ast.Name) and node.func.id in BANNED_NAMES:
                raise PluginSecurityViolationError(f"Plugin uses banned function: {node.func.id}")

        # Check for banned imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in BANNED_IMPORTS:
                    raise PluginSecurityViolationError(f"Plugin imports banned module: {alias.name}")
        if isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] in BANNED_IMPORTS:
                raise PluginSecurityViolationError(f"Plugin imports from banned module: {node.module}")
```

---

### Milestone 3.3: PluginRegistry with Entry-Point Loading

**Owner:** 1 engineer  
**File:** `syndicateclaw/plugins/registry.py`

```python
from importlib.metadata import entry_points

class PluginRegistry:
    def load_from_config(self, config_path: str):
        """Load plugins from plugins.yaml. Entry points only — no file paths."""
        config = load_yaml(config_path)
        for entry in config.get("plugins", []):
            if "/" in entry or entry.endswith(".py"):
                raise PluginConfigError(
                    f"File-path plugin loading is not supported: {entry!r}. "
                    "Install the plugin as a Python package and reference its entry point instead."
                )
            plugin_class = self._load_entry_point(entry)
            self.register(plugin_class())

    def _load_entry_point(self, qualified_name: str) -> type:
        """Load from installed package. Format: 'module:ClassName' or entry point group name."""
        if ":" in qualified_name:
            module_path, class_name = qualified_name.rsplit(":", 1)
            module = importlib.import_module(module_path)
            cls = getattr(module, class_name)
        else:
            # Look up in syndicateclaw.plugins entry point group
            eps = entry_points(group="syndicateclaw.plugins")
            matching = [ep for ep in eps if ep.name == qualified_name]
            if not matching:
                raise PluginConfigError(f"No entry point found for plugin: {qualified_name!r}")
            cls = matching[0].load()

        # Validate class
        if not issubclass(cls, Plugin):
            raise PluginConfigError(f"{cls!r} does not inherit from Plugin")
        if not hasattr(cls, "name") or not hasattr(cls, "version"):
            raise PluginConfigError(f"{cls!r} missing required 'name' or 'version' class attributes")

        # AST security check
        check_plugin_security(cls)

        return cls
```

---

### Milestone 3.4: Plugin Execution with Audit

**Owner:** 1 engineer  
**File:** `syndicateclaw/plugins/executor.py`

```python
class PluginExecutor:
    async def invoke_hook(
        self,
        hook_name: str,
        ctx: PluginContext,
        **kwargs,
    ) -> None:
        for plugin in self.registry.plugins:
            hook = getattr(plugin, hook_name, None)
            if not callable(hook):
                continue

            await audit_service.record("plugin.hook_invoked", plugin_name=plugin.name, hook=hook_name)
            try:
                await asyncio.wait_for(
                    hook(ctx, **kwargs),
                    timeout=settings.plugin_timeout,
                )
                await audit_service.record("plugin.hook_completed", plugin_name=plugin.name, hook=hook_name)
            except asyncio.TimeoutError:
                await audit_service.record("plugin.hook_timeout", plugin_name=plugin.name, hook=hook_name)
            except Exception as e:
                logger.error("plugin.hook_failed", plugin_name=plugin.name, hook=hook_name, error=str(e))
                await audit_service.record("plugin.hook_failed", plugin_name=plugin.name,
                                           hook=hook_name, error=str(e))
                # Never propagate — plugin errors must not crash the workflow
```

**Execution ordering in WorkflowEngine:** Plugin hooks fire **after** the audit event for the same lifecycle point is written. In `_execute_node()`:
```python
# 1. Execute node handler
result = await handler(...)
# 2. Write node execution audit event
await audit_service.record("NODE_EXECUTION_COMPLETED", ...)
# 3. Fire plugin hooks (after audit)
await plugin_executor.invoke_hook("on_node_execute", ctx=ctx, node_id=node_id, result=result)
```

---

### Milestone 3.5: Schema Migrations for Plugin Events

**Owner:** 1 engineer  
**File:** `migrations/versions/024_plugin_event_types.py`

```python
def upgrade():
    # If event_type is constrained by a CHECK constraint, add new values
    # If event_type is free-text TEXT column, no migration needed
    # Check the current constraint first
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.check_constraints
                WHERE constraint_name = 'ck_audit_events_event_type'
            ) THEN
                ALTER TABLE audit_events DROP CONSTRAINT ck_audit_events_event_type;
                -- Re-add with new values including plugin event types
                ALTER TABLE audit_events ADD CONSTRAINT ck_audit_events_event_type
                    CHECK (event_type IN (
                        -- existing types ...
                        'plugin.hook_invoked', 'plugin.hook_completed',
                        'plugin.hook_failed', 'plugin.hook_timeout',
                        'plugin.security_violation'
                    ));
            END IF;
        END $$;
    """)
```

---

### Milestone 3.6: Built-in Plugins

**Owner:** 1 engineer  
**File:** `syndicateclaw/plugins/builtin/`

**WebhookPlugin** (SSRF guard critical):
```python
class WebhookPlugin(Plugin):
    name = "webhook"
    version = "1.0.0"

    async def on_workflow_end(self, ctx: PluginContext, status: str) -> None:
        url = self.config.get("webhook_url")
        if not url:
            return

        # SSRF protection — validate before every send
        try:
            validate_url(url)  # syndicateclaw.security.ssrf.validate_url
        except SSRFError as e:
            logger.error("webhook.ssrf_blocked", url=url, reason=str(e))
            return

        # No redirects; HTTPS required in non-dev environments
        async with httpx.AsyncClient(follow_redirects=False) as client:
            await client.post(url, json={
                "run_id": ctx.run_id,
                "workflow_id": ctx.workflow_id,
                "status": status,
            })
```

**Tests (spec §9.3):** Write all 11 plugin tests. Key:
- `test_plugin_state_immutable`: `ctx.state["key"] = "x"` raises `TypeError`.
- `test_plugin_state_deep_copy`: `dict(ctx.state)["key"] = "x"` does not affect live state.
- `test_plugin_banned_import_rejected`: plugin importing `asyncio` raises `PluginSecurityViolationError` at load time.
- `test_webhook_plugin_ssrf_blocked`: `WebhookPlugin` configured with `http://192.168.1.1` does not send.

**Exit gate for Week 3:** All plugin tests pass; AST checker rejects banned patterns at load time; `MappingProxyType` prevents state mutation; WebhookPlugin SSRF guard blocks private IPs.

---

## File Map

| File | Action | Description |
|------|--------|-------------|
| `sdk/syndicateclaw_sdk/__init__.py` | **Create** | `SyndicateClaw` client with version check |
| `sdk/syndicateclaw_sdk/client.py` | **Create** | Core `httpx.AsyncClient` wrapper |
| `sdk/syndicateclaw_sdk/resources/` | **Create** | All resource classes (workflows, runs, memory, etc.) |
| `sdk/syndicateclaw_sdk/builder.py` | **Create** | `WorkflowBuilder` with completeness validation |
| `sdk/syndicateclaw_sdk/local.py` | **Create** | `LocalRuntime` with production guard + warning |
| `sdk/syndicateclaw_sdk/streaming.py` | **Create** | Streaming token management + SSE consumer |
| `sdk/syndicateclaw_sdk/exceptions.py` | **Create** | All SDK exception types |
| `sdk/pyproject.toml` | **Create** | Package config with flexible dependency ranges |
| `syndicateclaw/plugins/base.py` | **Create** | `Plugin` base class + `PluginContext` with `MappingProxyType` |
| `syndicateclaw/plugins/security.py` | **Create** | AST security checker |
| `syndicateclaw/plugins/registry.py` | **Create** | Entry-point-only `PluginRegistry` |
| `syndicateclaw/plugins/executor.py` | **Create** | Hook invocation with audit + error isolation |
| `syndicateclaw/plugins/builtin/` | **Create** | `AuditTrailPlugin`, `CostTrackingPlugin`, `WebhookPlugin`, `MetricsPlugin`, `RateLimitPlugin` |
| `syndicateclaw/services/builder_token_service.py` | **Create** | Issue + validate builder tokens |
| `syndicateclaw/middleware/csrf.py` | **Create** | `BuilderCSRFMiddleware` |
| `syndicateclaw/api/routes/workflows.py` | **Modify** | Add builder token endpoint |
| `syndicateclaw/orchestrator/engine.py` | **Modify** | Call plugin hooks after audit events |
| `syndicateclaw/static/builder/` | **Create** | React app bundle |
| `syndicateclaw/authz/route_registry.py` | **Modify** | Add builder and builder-token routes |
| `migrations/versions/024_plugin_event_types.py` | **Create** | Plugin audit event types |
| `migrations/versions/025_builder_token_type.py` | **Create** | Add `token_type` + `workflow_id` to streaming_tokens |

---

## Definition of Done

- [ ] `pip install syndicateclaw-sdk` works; SDK raises `IncompatibleServerError` on old server
- [ ] `stream()` never places primary JWT in URL; uses streaming token transparently
- [ ] `WorkflowBuilder.build()` raises `BuildValidationError` on missing branches, invalid conditions, disconnected graph
- [ ] `LocalRuntime` raises `RuntimeError` in production; prints complete bypass-warning at construction
- [ ] Builder iframe uses builder token (not primary JWT) in URL
- [ ] Builder `PUT` requests require `X-Builder-Token` header; missing header → 403
- [ ] Plugin file-path loading raises `PluginConfigError` at startup
- [ ] `PluginContext.state` returns `MappingProxyType` over deep copy; mutation raises `TypeError`
- [ ] AST checker rejects plugins importing `asyncio`, `threading`, `subprocess` at load time
- [ ] Plugin hooks fire after audit event for same lifecycle point is written
- [ ] `WebhookPlugin` validates URLs via `validate_url()` before every send; private IPs blocked
- [ ] All plugin audit event types defined and emitted
- [ ] react-flow commercial license resolved before release tag
- [ ] SDK `pyproject.toml` uses compatible version ranges (not exact pins)
- [ ] All new routes in RBAC route registry
- [ ] All new modules ≥80% integration test coverage
- [ ] `ruff` and `mypy` CI gates still passing
