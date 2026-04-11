# SyndicateClaw — Web Console & Chat Connectors

This document covers the three new feature areas added to syndicateclaw:

1. **Web Management Console** — React SPA at `/console`
2. **Chat Platform Connectors** — Telegram, Discord, Slack
3. **Admin REST API** — `/api/v1/admin/` consumed by both the console and external tooling

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        FastAPI Application                          │
│                                                                     │
│  /api/v1/inference/…   ← existing inference routes                 │
│  /api/v1/providers/…   ← existing provider routes                  │
│  /api/v1/admin/…       ← NEW: admin API (console backend)          │
│  /webhooks/telegram/…  ← NEW: Telegram webhook receiver            │
│  /webhooks/discord/…   ← NEW: Discord interactions endpoint        │
│  /webhooks/slack/…     ← NEW: Slack Events API + slash commands    │
│  /console/*            ← NEW: React SPA (StaticFiles mount)        │
└─────────────────────────────────────────────────────────────────────┘
         │                          │
         │ ConnectorRegistry        │ Admin REST API
         │                          │
  ┌──────┴──────┐           ┌──────┴──────────┐
  │  Connectors │           │  React Console  │
  │  (3 bots)   │           │  (browser SPA)  │
  └──────┬──────┘           └─────────────────┘
         │
  ┌──────▼──────────────────────────────────────┐
  │           ProviderService                   │
  │   (existing inference routing + policy)     │
  └─────────────────────────────────────────────┘
```

---

## Quick Start

### 1. Add Settings fields

In `src/syndicateclaw/config.py`, add to your `Settings` class
(or inherit from `ConnectorSettings` in `config_connectors.py`):

```python
# Public URL (required for Telegram webhook auto-registration)
public_base_url: str = ""

# Telegram
telegram_bot_token: str | None = None
telegram_webhook_secret: str | None = None

# Discord
discord_bot_token: str | None = None
discord_app_id: str = ""
discord_public_key: str = ""
discord_guild_ids: str = ""   # comma-separated, empty = global

# Slack
slack_bot_token: str | None = None
slack_signing_secret: str | None = None

# Shared connector defaults
connector_default_model_id: str | None = None
connector_default_provider_id: str | None = None
connector_system_prompt: str | None = None

# Console
console_enabled: bool = True
console_static_dir: str = "console/dist"
```

### 2. Patch `main.py`

See `src/syndicateclaw/api/MAIN_PATCH.py` for exact insertion points.
In summary:

```python
# ── imports ──
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from syndicateclaw.connectors.registry import build_registry
from syndicateclaw.connectors.telegram.bot import router as telegram_router
from syndicateclaw.connectors.discord.bot import router as discord_router
from syndicateclaw.connectors.slack.bot import router as slack_router
from syndicateclaw.api.routers.admin import router as admin_router

# ── inside lifespan(), after provider_service is ready ──
connector_registry = build_registry(settings, provider_service)
app.state.connector_registry = connector_registry
await connector_registry.start_all()

yield  # existing yield

await connector_registry.stop_all()  # add to teardown

# ── inside create_app(), after existing routers ──
app.include_router(admin_router)
app.include_router(telegram_router, prefix="/webhooks/telegram")
app.include_router(discord_router,  prefix="/webhooks/discord")
app.include_router(slack_router,    prefix="/webhooks/slack")

console_dist = Path(settings.console_static_dir)
if settings.console_enabled and console_dist.exists():
    app.mount("/console", StaticFiles(directory=console_dist, html=True), name="console")
```

### 3. Build the console

```bash
cd console
npm install
npm run build          # outputs to console/dist/
# dev mode with hot-reload + API proxy:
npm run dev            # http://localhost:5173/console
```

### 4. Set env vars and run

```bash
# .env
SYNDICATECLAW_DATABASE_URL=postgresql+asyncpg://...
SYNDICATECLAW_SECRET_KEY=your-secret

# Telegram
SYNDICATECLAW_TELEGRAM_BOT_TOKEN=123456:AAH...
SYNDICATECLAW_PUBLIC_BASE_URL=https://api.yourdomain.com
SYNDICATECLAW_TELEGRAM_WEBHOOK_SECRET=random-secret

# Discord
SYNDICATECLAW_DISCORD_BOT_TOKEN=MTI...
SYNDICATECLAW_DISCORD_APP_ID=1234567890
SYNDICATECLAW_DISCORD_PUBLIC_KEY=abc123...
SYNDICATECLAW_DISCORD_GUILD_IDS=111111,222222   # dev; remove for global

# Slack
SYNDICATECLAW_SLACK_BOT_TOKEN=xoxb-...
SYNDICATECLAW_SLACK_SIGNING_SECRET=abc...

# Shared
SYNDICATECLAW_CONNECTOR_DEFAULT_MODEL_ID=gpt-4o
SYNDICATECLAW_CONNECTOR_SYSTEM_PROMPT="You are a helpful assistant."
```

---

## Connector Setup

### Telegram

1. Message `@BotFather` → `/newbot` → copy token
2. Set `SYNDICATECLAW_TELEGRAM_BOT_TOKEN` and `SYNDICATECLAW_PUBLIC_BASE_URL`
3. Start the server — webhook is registered automatically at startup
4. Webhook endpoint: `POST /webhooks/telegram/update`

**Behaviour:**
- `/help` — show commands
- `/status` — connector health
- `/run <workflow>` — trigger a workflow by name
- Any other message → routed to `ProviderService.stream_chat()`
- Replies stream as Telegram message edits (live typing effect)

### Discord

1. Create app at [discord.com/developers](https://discord.com/developers/applications)
2. Under **Bot**: create bot, copy token
3. Under **General Information**: copy Application ID + Public Key
4. Set **Interactions Endpoint URL** to `https://your-host/webhooks/discord/interactions`
5. Under **OAuth2**: invite bot with `bot` + `applications.commands` scopes
6. Set env vars, restart — slash commands register automatically

**Slash commands registered:**
| Command | Description |
|---|---|
| `/chat <message>` | Chat with the AI |
| `/run <workflow>` | Trigger a named workflow |
| `/status` | Show connector health |
| `/help` | List commands |

**Note:** Set `SYNDICATECLAW_DISCORD_GUILD_IDS` for instant command sync during dev;
remove for global registration in production.

### Slack

1. Create app at [api.slack.com/apps](https://api.slack.com/apps) → **From scratch**
2. **OAuth & Permissions** → add scopes: `chat:write`, `app_mentions:read`, `im:read`, `im:write`, `commands`
3. Install to workspace, copy **Bot User OAuth Token**
4. **Basic Information** → copy **Signing Secret**
5. **Event Subscriptions** → Request URL: `https://your-host/webhooks/slack/events`
   → Subscribe to `app_mention` + `message.im`
6. **Slash Commands** → add `/syndicateclaw` → URL: `https://your-host/webhooks/slack/command`
7. Set env vars, restart

---

## Web Console

Access at `http://localhost:8000/console` (production) or `http://localhost:5173/console` (dev).

### Login

Enter any API key created via `/api/v1/admin/api-keys` (or the first key you create
directly in the DB during bootstrap). The key is stored in `localStorage` and sent
as `X-API-Key` on every request.

### Pages

| Page | Route | Description |
|---|---|---|
| Dashboard | `/console` | Connector status plus persisted admin aggregates for active runs, pending approvals, and memory namespaces |
| Connectors | `/console/connectors` | Per-platform connection status, event/error counters |
| Approvals | `/console/approvals` | Review and approve/deny pending workflow steps |
| Workflows | `/console/workflows` | Run history with status badges |
| Providers | `/console/providers` | Inference provider registry, model catalog sync |
| Policies | `/console/policies` | RBAC rules: create, enable/disable, delete |
| Memory | `/console/memory` | Namespace browser with purge capability |
| Audit Log | `/console/audit` | Filterable decision ledger |
| API Keys | `/console/api-keys` | Create/revoke keys, view last-used timestamps |
| Settings | `/console/settings` | Connector setup guides, env var reference, .env snippets |

---

## Admin API Reference

All routes are under `/api/v1/admin/`.

```
GET  /dashboard                    Aggregate stats
GET  /connectors                   Live connector statuses

GET  /approvals                    Pending approval queue
POST /approvals/{id}/decide        { "decision": "approve"|"deny", "reason": "..." }

GET  /workflows/runs               ?limit=50&status=RUNNING
GET  /workflows/runs/{run_id}      Single run detail

GET  /memory/namespaces            ?prefix=connector:
DEL  /memory/namespaces/{ns}       Purge all records in namespace

GET  /audit                        ?limit=100&actor=…&domain=…&effect=…&since=…

GET  /providers                    Provider registry

GET  /api-keys                     List all keys
POST /api-keys                     Create key → returns raw key (once only)
DEL  /api-keys/{key_id}            Revoke key
```

---

## File Structure

```
src/syndicateclaw/
├── connectors/
│   ├── __init__.py          Public API surface
│   ├── base.py              ConnectorBase ABC, ConnectorMessage, ConnectorStatus
│   ├── registry.py          ConnectorRegistry + build_registry() factory
│   ├── telegram/
│   │   ├── __init__.py
│   │   └── bot.py           TelegramConnector + FastAPI router
│   ├── discord/
│   │   ├── __init__.py
│   │   └── bot.py           DiscordConnector + interactions router
│   └── slack/
│       ├── __init__.py
│       └── bot.py           SlackConnector + events + command routers
├── api/
│   ├── routers/
│   │   └── admin.py         /api/v1/admin/* endpoints
│   ├── MAIN_PATCH.py        Annotated patch guide for main.py
│   └── main_patch.py        (alternate patch file from prior run)
└── config_connectors.py     Settings mixin with all connector fields

console/
├── index.html
├── package.json
├── vite.config.ts           Dev proxy → localhost:8000
├── tailwind.config.js
├── tsconfig.json
├── src/
│   ├── main.tsx             React entry point
│   ├── App.tsx              Router + auth guard
│   ├── index.css            Tailwind + JetBrains Mono
│   ├── api/
│   │   └── client.ts        Typed axios client for all API endpoints
│   ├── components/
│   │   └── Layout.tsx       Sidebar shell + Badge/Card/StatCard/PageHeader
│   └── pages/
│       ├── Login.tsx
│       ├── Dashboard.tsx
│       ├── Approvals.tsx
│       ├── Memory.tsx
│       ├── ApiKeys.tsx
│       ├── Policies.tsx
│       ├── ConsoleSettings.tsx
│       └── index.tsx        Connectors, Workflows, AuditLog, Providers

tests/
└── unit/
    └── connectors/
        └── test_parsers.py  38 pure unit tests, no network/DB required
```

---

## Testing

```bash
# Run just connector tests (no infrastructure needed)
pytest tests/unit/connectors/ -v

# Run all unit tests
pytest tests/unit/ -v

# Run integration tests (requires Postgres + Redis)
pytest tests/integration/ -v -m integration
```

### What the connector tests cover

- `_parse_command()` — 5 cases (plain text, no-arg command, args, bot mention, whitespace)
- `TelegramConnector.parse_update()` — 8 cases (plain, command, non-message, empty, actor format, namespace format, edited message)
- `DiscordConnector.parse_interaction()` — 7 cases (chat, run, followup token, status, ping, component, platform)
- `SlackConnector.parse_event()` — 8 cases (mention, DM, bot message ignored, command, empty, non-message, platform, thread_ts)
- `SlackConnector.parse_slash_command()` — 2 cases
- `ConnectorMessage` properties — 3 parametrized platform cases

---

## Implementation Notes

### Why raw httpx instead of platform SDKs?

- Zero additional mandatory runtime dependencies
- All three platforms have stable, well-documented REST APIs
- Async-native without adapter layers
- Easier to test (mock httpx responses directly)
- Smaller Docker image

### Streaming reply pattern

Each connector implements streaming differently to match platform constraints:

| Platform | Streaming mechanism |
|---|---|
| Telegram | `sendMessage` → store `message_id` → `editMessageText` every ~80 chars |
| Discord | Immediate `DEFERRED_CHANNEL_MESSAGE` (→ "thinking...") → `PATCH /messages/@original` |
| Slack | `chat.postMessage` → store `ts` → `chat.update` every ~80 chars |

### Security

- **Telegram**: `X-Telegram-Bot-Api-Secret-Token` header verified against configured secret
- **Discord**: Ed25519 signature verified against the app's public key (required by Discord)
- **Slack**: HMAC-SHA256 signature verified against signing secret + 5-minute replay window
- All connectors: actor strings (`connector:platform:user_id`) flow through the existing RBAC policy engine

### Memory namespacing

Each connector message carries a `memory_namespace` of the form
`connector:{platform}:{channel_id}`. This means per-conversation memory is
isolated by channel and platform, while still being accessible to the existing
`MemoryService` and visible in the console's Memory browser.

---

## Wiring TODO (stub implementations)

The following admin API endpoints return empty lists or 501 until wired to
real service/DB calls. Each is annotated with `# TODO:` in the source:

- `GET /admin/dashboard` — replace zeros with DB aggregates
- `GET /admin/approvals` — wire to `ApprovalRequest` table
- `POST /admin/approvals/{id}/decide` — wire to `ApprovalService.decide()`
- `GET /admin/workflows/runs` — wire to `WorkflowRun` table
- `GET /admin/memory/namespaces` — wire to `MemoryRecord` grouped query
- `GET /admin/audit` — wire to `DecisionRecord` table
- `GET /admin/providers` — wire to `ProviderService.list_providers()`
- `GET /admin/api-keys` — wire to `ApiKey` table
- `POST /admin/api-keys` — wire to `ApiKeyService.create()`
- `DELETE /admin/api-keys/{id}` — wire to `ApiKeyService.revoke()`
