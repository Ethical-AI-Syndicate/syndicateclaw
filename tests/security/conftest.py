"""Fixtures for security / pentest scenarios."""

from __future__ import annotations

import importlib
import os

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import ArgumentError

_DEFAULT_DB_URL = (
    "postgresql+asyncpg://syndicateclaw:syndicateclaw@postgres:5432/syndicateclaw_test"
)


@pytest.fixture
async def asgi_client_production_no_anonymous(monkeypatch: pytest.MonkeyPatch) -> AsyncClient:
    """App with SYNDICATECLAW_ENVIRONMENT=production — no anonymous fallback on missing auth."""
    monkeypatch.setenv("SYNDICATECLAW_ENVIRONMENT", "production")
    monkeypatch.setenv(
        "SYNDICATECLAW_DATABASE_URL",
        os.environ.get("SYNDICATECLAW_DATABASE_URL") or _DEFAULT_DB_URL,
    )
    monkeypatch.setenv("SYNDICATECLAW_SECRET_KEY", "test-secret-key-not-for-production")
    monkeypatch.setenv(
        "SYNDICATECLAW_REDIS_URL",
        os.environ.get("SYNDICATECLAW_REDIS_URL") or "redis://redis:6379/0",
    )
    monkeypatch.setenv("SYNDICATECLAW_RBAC_ENFORCEMENT_ENABLED", "false")

    import syndicateclaw.api.main as main_mod

    importlib.reload(main_mod)
    app = main_mod.create_app()
    try:
        async with (
            LifespanManager(app) as manager,
            AsyncClient(
                transport=ASGITransport(app=manager.app),
                base_url="http://test",
            ) as ac,
        ):
            yield ac
    except OSError as exc:
        pytest.skip(f"Pentest infrastructure unavailable: {exc}")
    except ArgumentError as exc:
        pytest.skip(f"Pentest database URL invalid: {exc}")
    except Exception as exc:
        if "Connect call failed" in str(exc) or "Connection refused" in str(exc):
            pytest.skip(f"Pentest infrastructure unavailable: {exc}")
        raise


@pytest.fixture()
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncClient:
    """Same contract as ``tests.integration.conftest.client`` (readyz must pass)."""
    monkeypatch.setenv(
        "SYNDICATECLAW_DATABASE_URL",
        os.environ.get("SYNDICATECLAW_DATABASE_URL") or _DEFAULT_DB_URL,
    )
    monkeypatch.setenv("SYNDICATECLAW_SECRET_KEY", "test-secret-key-not-for-production")
    monkeypatch.setenv(
        "SYNDICATECLAW_REDIS_URL",
        os.environ.get("SYNDICATECLAW_REDIS_URL") or "redis://redis:6379/0",
    )
    monkeypatch.setenv("SYNDICATECLAW_ENVIRONMENT", "test")
    monkeypatch.setenv("SYNDICATECLAW_RBAC_ENFORCEMENT_ENABLED", "false")

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
        pytest.skip(f"Pentest infrastructure unavailable: {exc}")
    except ArgumentError as exc:
        pytest.skip(f"Pentest database URL invalid: {exc}")
    except Exception as exc:
        if "Connect call failed" in str(exc) or "Connection refused" in str(exc):
            pytest.skip(f"Pentest infrastructure unavailable: {exc}")
        raise
