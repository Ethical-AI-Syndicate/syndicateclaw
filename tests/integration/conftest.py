"""Shared fixtures for integration tests (DB, Redis, full app lifespan)."""

from __future__ import annotations

import importlib
import os

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import ArgumentError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

pytestmark = pytest.mark.integration


_DEFAULT_DB_URL = (
    "postgresql+asyncpg://syndicateclaw:syndicateclaw@localhost:5432/syndicateclaw_test"
)


@pytest.fixture(scope="session", autouse=True)
async def _wait_for_services() -> None:
    """Wait for database and redis to be reachable before starting tests."""
    import asyncio
    import os

    import redis.asyncio as redis
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    db_url = os.environ.get("SYNDICATECLAW_DATABASE_URL") or _DEFAULT_DB_URL
    redis_url = os.environ.get("SYNDICATECLAW_REDIS_URL") or "redis://localhost:6379/0"

    # Wait for Postgres
    engine = create_async_engine(db_url, future=True)
    for _ in range(15):
        try:
            async with engine.begin() as conn:
                await conn.execute(text("SELECT 1"))
            break
        except Exception as e:
            print(f"Postgres wait failed: {e}")
            await asyncio.sleep(2)
    else:
        await engine.dispose()
        pytest.skip("Postgres failed to become reachable in time.")
    await engine.dispose()

    # Wait for Redis
    client = redis.from_url(redis_url)
    for _ in range(15):
        try:
            await client.ping()
            break
        except Exception as e:
            print(f"Redis wait failed: {e}")
            await asyncio.sleep(2)
    else:
        await client.aclose()
        pytest.skip("Redis failed to become reachable in time.")
    await client.aclose()


@pytest.fixture(scope="session")
def _session_env() -> None:
    """Set required env vars once for the entire session; restore on teardown."""
    _default_secret = "test-secret-key-not-for-production"
    _default_redis = "redis://localhost:6379/0"
    _db_url = os.environ.get("SYNDICATECLAW_DATABASE_URL") or _DEFAULT_DB_URL
    _secret = os.environ.get("SYNDICATECLAW_SECRET_KEY") or _default_secret
    _redis = os.environ.get("SYNDICATECLAW_REDIS_URL") or _default_redis
    env_overrides = {
        "SYNDICATECLAW_DATABASE_URL": _db_url,
        "SYNDICATECLAW_SECRET_KEY": _secret,
        "SYNDICATECLAW_REDIS_URL": _redis,
        "SYNDICATECLAW_ENVIRONMENT": "test",
        "SYNDICATECLAW_RBAC_ENFORCEMENT_ENABLED": "false",
    }
    old_values = {k: os.environ.get(k) for k in env_overrides}
    os.environ.update(env_overrides)
    yield
    for k, v in old_values.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@pytest.fixture(autouse=True)
def _integration_env(monkeypatch: pytest.MonkeyPatch, db_engine: AsyncEngine) -> None:
    """Ensure required env vars are set for Settings() construction."""
    monkeypatch.setenv(
        "SYNDICATECLAW_DATABASE_URL",
        os.environ.get("SYNDICATECLAW_DATABASE_URL") or _DEFAULT_DB_URL,
    )
    monkeypatch.setenv(
        "SYNDICATECLAW_SECRET_KEY",
        os.environ.get("SYNDICATECLAW_SECRET_KEY") or "test-secret-key-not-for-production",
    )
    monkeypatch.setenv(
        "SYNDICATECLAW_REDIS_URL",
        os.environ.get("SYNDICATECLAW_REDIS_URL") or "redis://localhost:6379/0",
    )
    monkeypatch.setenv("SYNDICATECLAW_ENVIRONMENT", "test")
    monkeypatch.setenv("SYNDICATECLAW_RBAC_ENFORCEMENT_ENABLED", "false")


@pytest.fixture(scope="session")
async def session_factory(_session_env: None) -> async_sessionmaker[AsyncSession]:
    """Real ``session_factory`` from the app (Postgres). Skips if DB unavailable."""
    import syndicateclaw.api.main as main_mod

    importlib.reload(main_mod)
    app = main_mod.create_app()
    try:
        async with LifespanManager(app):
            # LifespanManager wraps the ASGI app; session_factory lives on the real app.
            sf = app.state.session_factory
            async with sf() as session:
                await session.execute(text("SELECT 1"))
            yield sf
    except OSError as exc:
        pytest.skip(f"Integration test infrastructure unavailable: {exc}")
    except ArgumentError as exc:
        pytest.skip(f"Integration test database URL invalid: {exc}")
    except Exception as exc:
        if "Connect call failed" in str(exc) or "Connection refused" in str(exc):
            pytest.skip(f"Integration test infrastructure unavailable: {exc}")
        if "password authentication failed" in str(exc).lower():
            pytest.skip(f"Integration test database auth failed: {exc}")
        if "does not exist" in str(exc).lower() and "database" in str(exc).lower():
            pytest.skip(f"Integration test database missing: {exc}")
        raise


@pytest.fixture()
async def integration_app_client(_integration_env: None) -> AsyncClient:
    """ASGI client with full lifespan; does not require /readyz (DB/Redis may be down)."""
    import importlib

    import syndicateclaw.api.main as main_mod

    importlib.reload(main_mod)

    app = main_mod.create_app()
    try:
        async with (
            LifespanManager(app) as manager,
            AsyncClient(transport=ASGITransport(app=manager.app), base_url="http://test") as ac,
        ):
            yield ac
    except OSError as exc:
        pytest.skip(f"Integration test infrastructure unavailable: {exc}")
    except Exception as exc:
        if "Connect call failed" in str(exc) or "Connection refused" in str(exc):
            pytest.skip(f"Integration test infrastructure unavailable: {exc}")
        raise


@pytest.fixture(scope="session")
async def client(_session_env: None) -> AsyncClient:
    """Test client with full app lifespan; skips if Postgres/Redis are not healthy."""
    import importlib

    import syndicateclaw.api.main as main_mod

    importlib.reload(main_mod)

    app = main_mod.create_app()
    try:
        async with (
            LifespanManager(app) as manager,
            AsyncClient(transport=ASGITransport(app=manager.app), base_url="http://test") as ac,
        ):
            resp = await ac.get("/readyz")
            if resp.status_code != 200:
                pytest.skip(f"Integration dependencies not ready: {resp.json()}")
            yield ac
    except OSError as exc:
        pytest.skip(f"Integration test infrastructure unavailable: {exc}")
    except Exception as exc:
        if "Connect call failed" in str(exc) or "Connection refused" in str(exc):
            pytest.skip(f"Integration test infrastructure unavailable: {exc}")
        raise


@pytest.fixture(autouse=True)
async def _cancel_stale_runs(_integration_env: None) -> None:
    """Cancel stale PENDING/RUNNING runs before each test (avoids concurrency limit)."""
    import os

    from sqlalchemy.ext.asyncio import create_async_engine

    url = os.environ.get("SYNDICATECLAW_DATABASE_URL") or ""
    if not url:
        return
    try:
        engine = create_async_engine(url)
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE workflow_runs SET status='CANCELLED' "
                    "WHERE status IN ('PENDING','RUNNING','WAITING_APPROVAL',"
                    "'WAITING_AGENT_RESPONSE')"
                )
            )
        await engine.dispose()
    except Exception:
        pass  # DB not available — integration tests will skip anyway
