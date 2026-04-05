# Codebase Remediation (Refactor-First) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor core wiring first, complete admin/console/connectors second, then perform a full verification re-review with zero unresolved high/critical issues.

**Architecture:** First, split app startup/lifespan concerns into bounded bootstrap modules and align route governance with RBAC registry contracts. Second, replace admin API stubs with service-backed implementations and align console contracts to real responses. Third, run a strict, evidence-based re-review matrix (lint/type/tests/build/security markers) and close remaining defects.

**Tech Stack:** Python 3.14.3, FastAPI, Pydantic v2, SQLAlchemy async, structlog, pytest, Ruff, mypy, React 18, TypeScript, Vite, Tailwind.

---

### Task 1: Characterize and Lock Current App Wiring Behavior

**Files:**
- Create: `tests/unit/api/test_app_bootstrap_characterization.py`
- Modify: `src/syndicateclaw/api/main.py`
- Test: `tests/unit/api/test_app_bootstrap_characterization.py`

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

import os

from syndicateclaw.api.main import create_app


def test_create_app_sets_settings_on_app_state() -> None:
    os.environ.setdefault("SYNDICATECLAW_DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    os.environ.setdefault("SYNDICATECLAW_SECRET_KEY", "test-key")
    app = create_app()
    assert hasattr(app.state, "settings")


def test_create_app_includes_admin_and_webhook_routes() -> None:
    app = create_app()
    paths = {route.path for route in app.routes}
    assert "/api/v1/admin/dashboard" in paths
    assert "/webhooks/telegram/update" in paths
    assert "/webhooks/discord/interactions" in paths
    assert "/webhooks/slack/events" in paths
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/api/test_app_bootstrap_characterization.py -v`
Expected: FAIL on `app.state.settings` missing.

- [ ] **Step 3: Write minimal implementation**

```python
# src/syndicateclaw/api/main.py (inside create_app)
settings = Settings()
app = FastAPI(...)
app.state.settings = settings
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/api/test_app_bootstrap_characterization.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/api/test_app_bootstrap_characterization.py src/syndicateclaw/api/main.py
git commit -m "test: lock app bootstrap state and route characterization"
```

### Task 2: Extract Bootstrap/Lifespan Composition Modules

**Files:**
- Create: `src/syndicateclaw/api/bootstrap/runtime.py`
- Create: `src/syndicateclaw/api/bootstrap/connectors.py`
- Create: `src/syndicateclaw/api/bootstrap/__init__.py`
- Modify: `src/syndicateclaw/api/main.py`
- Test: `tests/unit/api/test_app_bootstrap_characterization.py`

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from syndicateclaw.api.bootstrap.connectors import start_connector_registry


@pytest.mark.asyncio
async def test_start_connector_registry_sets_app_state() -> None:
    class DummyAppState:
        pass

    class DummyApp:
        state = DummyAppState()

    class DummyRegistry:
        start_all = AsyncMock()

    registry = DummyRegistry()
    app = DummyApp()

    await start_connector_registry(app, registry)

    assert app.state.connector_registry is registry
    registry.start_all.assert_awaited_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/api/test_app_bootstrap_characterization.py -v`
Expected: FAIL with missing module/function.

- [ ] **Step 3: Write minimal implementation**

```python
# src/syndicateclaw/api/bootstrap/connectors.py
from __future__ import annotations

from typing import Any


async def start_connector_registry(app: Any, registry: Any) -> None:
    app.state.connector_registry = registry
    await registry.start_all()


async def stop_connector_registry(registry: Any) -> None:
    await registry.stop_all()
```

```python
# src/syndicateclaw/api/main.py (lifespan excerpt)
from syndicateclaw.api.bootstrap.connectors import start_connector_registry, stop_connector_registry

connector_registry = build_registry(settings, provider_service)
await start_connector_registry(app, connector_registry)
...
await stop_connector_registry(connector_registry)
```

- [ ] **Step 4: Run tests to verify behavior parity**

Run: `pytest tests/unit/api/test_app_bootstrap_characterization.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/syndicateclaw/api/bootstrap/ src/syndicateclaw/api/main.py tests/unit/api/test_app_bootstrap_characterization.py
git commit -m "refactor: extract connector lifecycle bootstrap helpers"
```

### Task 3: Enforce Admin Governance and Register New Routes in Authz Registry

**Files:**
- Modify: `src/syndicateclaw/api/dependencies.py`
- Modify: `src/syndicateclaw/api/routers/admin.py`
- Modify: `src/syndicateclaw/authz/route_registry.py`
- Create: `tests/unit/authz/test_admin_route_registry.py`
- Test: `tests/unit/authz/test_admin_route_registry.py`

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

from syndicateclaw.authz.route_registry import get_required_permission


def test_admin_routes_are_registered() -> None:
    assert get_required_permission("GET", "/api/v1/admin/dashboard") == "admin:*"
    assert get_required_permission("GET", "/api/v1/admin/connectors") == "admin:*"
    assert get_required_permission("POST", "/api/v1/admin/approvals/abc/decide") == "admin:*"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/authz/test_admin_route_registry.py -v`
Expected: FAIL with `DENY` or mismatch.

- [ ] **Step 3: Write minimal implementation**

```python
# src/syndicateclaw/api/dependencies.py
from fastapi import HTTPException, status


def require_admin_actor(actor: str) -> str:
    if not actor.startswith(("admin:", "system:")):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin permission required")
    return actor
```

```python
# src/syndicateclaw/api/routers/admin.py
from syndicateclaw.api.dependencies import get_current_actor, require_admin_actor


def _admin_actor(actor: str = Depends(get_current_actor)) -> str:
    return require_admin_actor(actor)


router = APIRouter(prefix="/api/v1/admin", tags=["admin"], dependencies=[Depends(_admin_actor)])
```

```python
# src/syndicateclaw/authz/route_registry.py (ROUTE_REGISTRY additions)
("GET", "/api/v1/admin/dashboard"): "admin:*",
("GET", "/api/v1/admin/connectors"): "admin:*",
("GET", "/api/v1/admin/approvals"): "admin:*",
("POST", "/api/v1/admin/approvals/{id}/decide"): "admin:*",
("GET", "/api/v1/admin/workflows/runs"): "admin:*",
("GET", "/api/v1/admin/workflows/runs/{run_id}"): "admin:*",
("GET", "/api/v1/admin/memory/namespaces"): "admin:*",
("DELETE", "/api/v1/admin/memory/namespaces/{namespace}"): "admin:*",
("GET", "/api/v1/admin/audit"): "admin:*",
("GET", "/api/v1/admin/providers"): "admin:*",
("GET", "/api/v1/admin/api-keys"): "admin:*",
("POST", "/api/v1/admin/api-keys"): "admin:*",
("DELETE", "/api/v1/admin/api-keys/{key_id}"): "admin:*",
```

- [ ] **Step 4: Run tests to verify registry + guard**

Run: `pytest tests/unit/authz/test_admin_route_registry.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/syndicateclaw/api/dependencies.py src/syndicateclaw/api/routers/admin.py src/syndicateclaw/authz/route_registry.py tests/unit/authz/test_admin_route_registry.py
git commit -m "security: register and enforce admin route permissions"
```

### Task 4: Clear Quality Gates (Ruff + mypy) for Refactor Baseline

**Files:**
- Modify: `src/syndicateclaw/api/main.py`
- Modify: `src/syndicateclaw/api/routers/admin.py`
- Modify: `src/syndicateclaw/connectors/discord/bot.py`
- Modify: `src/syndicateclaw/connectors/registry.py`
- Modify: `src/syndicateclaw/connectors/telegram/bot.py`
- Modify: `src/syndicateclaw/policy/engine.py`
- Modify: `tests/unit/test_openapi_contract.py`
- Test: `tests/unit/connectors/test_parsers.py`

- [ ] **Step 1: Run failing gate checks (red)**

Run: `ruff check src/ tests/ && mypy src/syndicateclaw`
Expected: FAIL with lint/type errors.

- [ ] **Step 2: Write minimal regression tests for discord parse nullability**

```python
def test_parse_interaction_handles_missing_member_user(connector: DiscordConnector) -> None:
    msg = connector.parse_interaction(
        {
            "type": APPLICATION_COMMAND,
            "id": "i-6",
            "token": "tok-6",
            "channel_id": "c-6",
            "user": {"id": "u-6"},
            "data": {"name": "help"},
        }
    )
    assert msg is not None
    assert msg.user_id == "u-6"
```

- [ ] **Step 3: Implement lint/type-safe fixes**

```python
# src/syndicateclaw/connectors/discord/bot.py
member_raw = body.get("member")
member: dict[str, Any] = member_raw if isinstance(member_raw, dict) else {}
user_raw = member.get("user")
if isinstance(user_raw, dict):
    user_obj: dict[str, Any] = user_raw
else:
    fallback_raw = body.get("user")
    user_obj = fallback_raw if isinstance(fallback_raw, dict) else {}

options_raw = data.get("options")
options: list[dict[str, Any]] = [o for o in options_raw if isinstance(o, dict)] if isinstance(options_raw, list) else []
```

```python
# src/syndicateclaw/connectors/telegram/bot.py
from contextlib import suppress

with suppress(TypeError, ValueError):
    payload["reply_to_message_id"] = int(message.platform_message_id)
```

```python
# src/syndicateclaw/api/routers/admin.py
@router.post("/approvals/{approval_id}/decide")
async def decide_approval(approval_id: str, ...)
```

- [ ] **Step 4: Re-run gates (green)**

Run: `ruff check src/ tests/ && mypy src/syndicateclaw`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/syndicateclaw/api/main.py src/syndicateclaw/api/routers/admin.py src/syndicateclaw/connectors/discord/bot.py src/syndicateclaw/connectors/registry.py src/syndicateclaw/connectors/telegram/bot.py src/syndicateclaw/policy/engine.py tests/unit/connectors/test_parsers.py tests/unit/test_openapi_contract.py
git commit -m "chore: make refactor baseline pass lint and type gates"
```

### Task 5: Build Admin Query Service (Feature Completion Start)

**Files:**
- Create: `src/syndicateclaw/api/admin/service.py`
- Create: `src/syndicateclaw/api/admin/__init__.py`
- Modify: `src/syndicateclaw/api/dependencies.py`
- Create: `tests/unit/api/test_admin_service.py`
- Test: `tests/unit/api/test_admin_service.py`

- [ ] **Step 1: Write failing service tests**

```python
from __future__ import annotations

import pytest

from syndicateclaw.api.admin.service import AdminService


@pytest.mark.asyncio
async def test_dashboard_counts_connectors_and_errors() -> None:
    svc = AdminService()
    dashboard = await svc.dashboard_from_statuses(
        [
            {"platform": "telegram", "connected": True, "errors": 0},
            {"platform": "discord", "connected": False, "errors": 2},
        ]
    )
    assert dashboard.connectors_total == 2
    assert dashboard.connectors_connected == 1
    assert dashboard.connectors_errors == 2
```

- [ ] **Step 2: Run failing tests**

Run: `pytest tests/unit/api/test_admin_service.py -v`
Expected: FAIL with missing module/class.

- [ ] **Step 3: Write minimal implementation**

```python
# src/syndicateclaw/api/admin/service.py
from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class DashboardStatsData:
    connectors_total: int
    connectors_connected: int
    connectors_errors: int
    pending_approvals: int
    workflow_runs_active: int
    memory_namespaces: int


class AdminService:
    async def dashboard_from_statuses(self, statuses: list[dict[str, object]]) -> DashboardStatsData:
        return DashboardStatsData(
            connectors_total=len(statuses),
            connectors_connected=sum(1 for item in statuses if bool(item.get("connected"))),
            connectors_errors=sum(int(item.get("errors", 0)) for item in statuses),
            pending_approvals=0,
            workflow_runs_active=0,
            memory_namespaces=0,
        )
```

- [ ] **Step 4: Run tests and extend assertions**

Run: `pytest tests/unit/api/test_admin_service.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/syndicateclaw/api/admin/ src/syndicateclaw/api/dependencies.py tests/unit/api/test_admin_service.py
git commit -m "feat: add admin service foundation for dashboard and queries"
```

### Task 6: Replace Admin Router TODO Stubs with Real Service/Repository Wiring

**Files:**
- Modify: `src/syndicateclaw/api/routers/admin.py`
- Modify: `src/syndicateclaw/api/dependencies.py`
- Modify: `src/syndicateclaw/db/repository.py`
- Create: `tests/integration/test_admin_routes.py`
- Test: `tests/integration/test_admin_routes.py`

- [ ] **Step 1: Write failing integration tests for implemented endpoints**

```python
def test_admin_dashboard_returns_numeric_metrics(client):
    response = client.get("/api/v1/admin/dashboard", headers={"X-API-Key": "test-admin-key"})
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["connectors_total"], int)
    assert isinstance(payload["pending_approvals"], int)


def test_admin_create_api_key_returns_raw_key(client):
    response = client.post(
        "/api/v1/admin/api-keys",
        json={"name": "console-key"},
        headers={"X-API-Key": "test-admin-key"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["key"].startswith("sc-")
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/integration/test_admin_routes.py -v -m integration`
Expected: FAIL (501/empty stubs).

- [ ] **Step 3: Implement endpoint wiring**

```python
# src/syndicateclaw/api/routers/admin.py (example endpoint shape)
@router.get("/providers", response_model=list[ProviderSummary])
async def list_provider_summaries(
    request: Request,
    actor: str = Depends(get_current_actor),
    loader: Any = Depends(get_provider_loader),
) -> list[ProviderSummary]:
    _ = (request, actor)
    cfg, _ver = loader.current()
    return [
        ProviderSummary(
            provider_id=item.id,
            name=item.name,
            enabled=True,
            model_count=len(item.allowed_models),
            status="configured",
        )
        for item in cfg.providers
    ]
```

```python
# src/syndicateclaw/api/routers/admin.py (api key create)
@router.post("/api-keys", response_model=CreateApiKeyResponse)
async def create_api_key(
    body: CreateApiKeyRequest,
    actor: str = Depends(get_current_actor),
    api_key_service: ApiKeyService = Depends(get_api_key_service),
) -> CreateApiKeyResponse:
    key_id, raw_key = await api_key_service.create_api_key(actor=actor, description=body.name)
    return CreateApiKeyResponse(key_id=key_id, key=raw_key, created_at=datetime.now(UTC))
```

- [ ] **Step 4: Re-run integration and unit tests for admin**

Run: `pytest tests/integration/test_admin_routes.py -v -m integration`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/syndicateclaw/api/routers/admin.py src/syndicateclaw/api/dependencies.py src/syndicateclaw/db/repository.py tests/integration/test_admin_routes.py
git commit -m "feat: implement admin router endpoints with service wiring"
```

### Task 7: Align Console Contracts with Implemented Admin API

**Files:**
- Modify: `console/src/api/client.ts`
- Modify: `console/src/pages/Dashboard.tsx`
- Modify: `console/src/pages/Approvals.tsx`
- Modify: `console/src/pages/ApiKeys.tsx`
- Modify: `console/src/pages/Providers.tsx`
- Test: `console` build and route behavior

- [ ] **Step 1: Write failing frontend contract test (type/build gate)**

```ts
// console/src/api/client.ts
export interface CreateApiKeyResponse {
  key_id: string;
  key: string;
  created_at: string;
}

// ensure every page consumes this exact shape; no optional raw key
```

- [ ] **Step 2: Run build to verify failures before alignment**

Run: `cd console && npm run build`
Expected: FAIL if API type/usage mismatch exists.

- [ ] **Step 3: Implement API + page alignment**

```ts
// console/src/api/client.ts
export const adminApi = {
  createApiKey: async (body: CreateApiKeyRequest): Promise<CreateApiKeyResponse> => {
    const { data } = await client.post<CreateApiKeyResponse>("/api/v1/admin/api-keys", body);
    return data;
  },
};
```

```tsx
// console/src/pages/ApiKeys.tsx
const createMutation = useMutation({
  mutationFn: adminApi.createApiKey,
  onSuccess: (response) => {
    setRawKey(response.key);
    queryClient.invalidateQueries({ queryKey: ["api-keys"] });
  },
});
```

- [ ] **Step 4: Build and smoke-test console routes**

Run: `cd console && npm run build`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add console/src/api/client.ts console/src/pages/Dashboard.tsx console/src/pages/Approvals.tsx console/src/pages/ApiKeys.tsx console/src/pages/Providers.tsx
git commit -m "feat(console): align API contracts with implemented admin backend"
```

### Task 8: Connector Hardening and Failure-Path Tests

**Files:**
- Modify: `src/syndicateclaw/connectors/telegram/bot.py`
- Modify: `src/syndicateclaw/connectors/discord/bot.py`
- Modify: `src/syndicateclaw/connectors/slack/bot.py`
- Modify: `tests/unit/connectors/test_parsers.py`
- Create: `tests/unit/connectors/test_connector_handlers.py`
- Test: `tests/unit/connectors/`

- [ ] **Step 1: Write failing handler tests for denial/approval/error branches**

```python
@pytest.mark.asyncio
async def test_handle_message_denied_error_sends_denied_reply(fake_connector, denied_message):
    await fake_connector.handle_message(denied_message)
    assert fake_connector.sent_replies[-1].startswith("⛔ Request denied:")


@pytest.mark.asyncio
async def test_handle_message_approval_required(fake_connector, approval_message):
    await fake_connector.handle_message(approval_message)
    assert fake_connector.sent_replies[-1] == "⏳ Requires approval…"
```

- [ ] **Step 2: Run failing tests**

Run: `pytest tests/unit/connectors/test_connector_handlers.py -v`
Expected: FAIL on missing branch coverage hooks.

- [ ] **Step 3: Implement minimal hardening fixes**

```python
# src/syndicateclaw/connectors/base.py (already structured, keep deterministic)
except InferenceDeniedError as exc:
    await self.send_reply(message, f"⛔ Request denied: {exc}")
except InferenceApprovalRequiredError:
    await self.send_reply(message, "⏳ Requires approval…")
except Exception as exc:
    self._status.errors += 1
    logger.exception("connector.handle_message_failed", platform=self.platform.value)
    await self.send_reply(message, f"❌ Error: {exc}")
```

- [ ] **Step 4: Run full connector unit suite**

Run: `pytest tests/unit/connectors/ -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/syndicateclaw/connectors/ tests/unit/connectors/
git commit -m "test: harden connector handler failure paths and branch coverage"
```

### Task 9: Full Re-Review, Verification Matrix, and Closure Report

**Files:**
- Create: `docs/superpowers/reviews/2026-03-31-codebase-remediation-final-audit.md`
- Modify: `docs/README_CONNECTORS.md`
- Modify: `docs/api/openapi.json` (if regenerated/changed)
- Test: full matrix commands

- [ ] **Step 1: Run full quality and unit/integration verification matrix**

Run:

```bash
ruff check src/ tests/
mypy src/syndicateclaw
pytest tests/unit/ -v
pytest tests/integration/ -v -m integration
cd console && npm run build
```

Expected: all required checks pass; any skips/xfails explicitly listed.

- [ ] **Step 2: Run security/perf marker verification where environment supports it**

Run:

```bash
pytest tests/security/ -v -m pentest
pytest -m perf -v
```

Expected: pass or explicit, documented environment waiver.

- [ ] **Step 3: Write final audit report with residual-risk table**

```markdown
# Final Remediation Audit

## Verified Gates
- Ruff: PASS
- mypy: PASS
- Unit: PASS
- Integration: PASS
- Console Build: PASS

## Residual Risks
| ID | Severity | Description | Owner | ETA |
|----|----------|-------------|-------|-----|
| none | n/a | n/a | n/a | n/a |
```

- [ ] **Step 4: Reconcile docs with implemented behavior**

Run: `pytest tests/unit/test_openapi_contract.py -v`
Expected: PASS and route docs consistent.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/reviews/2026-03-31-codebase-remediation-final-audit.md docs/README_CONNECTORS.md docs/api/openapi.json
git commit -m "docs: publish final remediation audit and contract reconciliation"
```

## Plan Self-Review

### Spec Coverage Check

- Refactor-first sequence: covered by Tasks 1-4.
- Feature completion second: covered by Tasks 5-8.
- Full re-review third: covered by Task 9.
- Governance hardening and route registration: Task 3.
- Quality gates and type/lint stability: Task 4 and Task 9.

No uncovered spec requirement found.

### Placeholder Scan

- No `TODO`, `TBD`, or deferred placeholders in task instructions.
- Every coding step includes concrete code snippets and concrete commands.

### Type/Interface Consistency Check

- Admin API key response shape kept consistent between backend and console tasks.
- Route template naming uses FastAPI template conventions (`{key_id}`, `{run_id}`, `{namespace}`).
- Connector and admin service naming remains consistent across tasks.
