"""Fixtures for security / pentest scenarios."""

from __future__ import annotations

import importlib
import os

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import ArgumentError

_DEFAULT_DB_URL = (
    "postgresql+asyncpg://syndicateclaw:syndicateclaw@localhost:5432/syndicateclaw_test"
)


def _is_infrastructure_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(
        marker in msg
        for marker in (
            "connect call failed",
            "connection refused",
            "password authentication failed",
            "could not connect to server",
            "name or service not known",
            "temporary failure in name resolution",
        )
    )


async def _safe_lifespan_exit(manager: LifespanManager) -> None:
    """Exit a LifespanManager, ignoring 'Event loop is closed' on session teardown."""
    try:
        await manager.__aexit__(None, None, None)
    except RuntimeError as exc:
        if "Event loop is closed" not in str(exc):
            raise


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Force asyncio security tests to use the session event loop (see integration/conftest.py)."""
    for item in items:
        asyncio_marker = item.get_closest_marker("asyncio")
        if asyncio_marker is not None and asyncio_marker.kwargs.get("loop_scope") is None:
            item.own_markers = [m for m in item.own_markers if m.name != "asyncio"]
            item.add_marker(pytest.mark.asyncio(loop_scope="session"), append=False)


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
        os.environ.get("SYNDICATECLAW_REDIS_URL") or "redis://localhost:6379/0",
    )
    monkeypatch.setenv("SYNDICATECLAW_RBAC_ENFORCEMENT_ENABLED", "false")

    import syndicateclaw.api.main as main_mod

    importlib.reload(main_mod)
    app = main_mod.create_app()
    manager = LifespanManager(app)
    try:
        await manager.__aenter__()
    except OSError as exc:
        pytest.skip(f"Pentest infrastructure unavailable: {exc}")
    except ArgumentError as exc:
        pytest.skip(f"Pentest database URL invalid: {exc}")
    except Exception as exc:
        if _is_infrastructure_error(exc):
            pytest.skip(f"Pentest infrastructure unavailable: {exc}")
        raise

    ac = AsyncClient(
        transport=ASGITransport(app=manager.app),
        base_url="http://test",
    )
    await ac.__aenter__()
    try:
        yield ac
    finally:
        try:
            await ac.__aexit__(None, None, None)
        except RuntimeError as exc:
            if "Event loop is closed" not in str(exc):
                raise
        await _safe_lifespan_exit(manager)


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
        os.environ.get("SYNDICATECLAW_REDIS_URL") or "redis://localhost:6379/0",
    )
    monkeypatch.setenv("SYNDICATECLAW_ENVIRONMENT", "test")
    monkeypatch.setenv("SYNDICATECLAW_RBAC_ENFORCEMENT_ENABLED", "false")

    import syndicateclaw.api.main as main_mod

    importlib.reload(main_mod)
    app = main_mod.create_app()
    manager = LifespanManager(app)
    try:
        await manager.__aenter__()
    except OSError as exc:
        pytest.skip(f"Pentest infrastructure unavailable: {exc}")
    except ArgumentError as exc:
        pytest.skip(f"Pentest database URL invalid: {exc}")
    except Exception as exc:
        if _is_infrastructure_error(exc):
            pytest.skip(f"Pentest infrastructure unavailable: {exc}")
        raise

    ac = AsyncClient(transport=ASGITransport(app=manager.app), base_url="http://test")
    await ac.__aenter__()
    try:
        resp = await ac.get("/readyz")
        if resp.status_code != 200:
            await ac.__aexit__(None, None, None)
            await _safe_lifespan_exit(manager)
            pytest.skip(f"Integration dependencies not ready: {resp.json()}")
        yield ac
    finally:
        try:
            await ac.__aexit__(None, None, None)
        except RuntimeError as exc:
            if "Event loop is closed" not in str(exc):
                raise
        await _safe_lifespan_exit(manager)
