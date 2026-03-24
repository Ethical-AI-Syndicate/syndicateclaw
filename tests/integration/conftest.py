"""Shared fixtures for integration tests (DB, Redis, full app lifespan)."""

from __future__ import annotations

import os

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _integration_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure required env vars are set for Settings() construction."""
    monkeypatch.setenv(
        "SYNDICATECLAW_DATABASE_URL",
        os.environ.get(
            "SYNDICATECLAW_DATABASE_URL",
            "postgresql+asyncpg://syndicateclaw:syndicateclaw@localhost:5432/syndicateclaw_test",
        ),
    )
    monkeypatch.setenv(
        "SYNDICATECLAW_SECRET_KEY",
        os.environ.get("SYNDICATECLAW_SECRET_KEY", "test-secret-key-not-for-production"),
    )
    monkeypatch.setenv("SYNDICATECLAW_ENVIRONMENT", "test")


@pytest.fixture()
async def integration_app_client(_integration_env: None) -> AsyncClient:
    """ASGI client with full lifespan; does not require /readyz (DB/Redis may be down)."""
    import importlib

    import syndicateclaw.api.main as main_mod

    importlib.reload(main_mod)

    app = main_mod.create_app()
    try:
        async with LifespanManager(app) as manager, AsyncClient(
            transport=ASGITransport(app=manager.app), base_url="http://test"
        ) as ac:
            yield ac
    except OSError as exc:
        pytest.skip(f"Integration test infrastructure unavailable: {exc}")
    except Exception as exc:
        if "Connect call failed" in str(exc) or "Connection refused" in str(exc):
            pytest.skip(f"Integration test infrastructure unavailable: {exc}")
        raise


@pytest.fixture()
async def client(_integration_env: None) -> AsyncClient:
    """Test client with full app lifespan; skips if Postgres/Redis are not healthy."""
    import importlib

    import syndicateclaw.api.main as main_mod

    importlib.reload(main_mod)

    app = main_mod.create_app()
    try:
        async with LifespanManager(app) as manager, AsyncClient(
            transport=ASGITransport(app=manager.app), base_url="http://test"
        ) as ac:
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
