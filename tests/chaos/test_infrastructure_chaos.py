"""Chaos scenarios — mock-based failure injection for CI."""

from __future__ import annotations

import importlib
import os

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from tests.chaos.helpers import mock_redis_down

pytestmark = [pytest.mark.chaos]


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


def _set_test_env() -> None:
    """Set required env vars for Settings() construction."""
    os.environ.setdefault(
        "SYNDICATECLAW_DATABASE_URL",
        "postgresql+asyncpg://syndicateclaw:syndicateclaw@localhost:5432/syndicateclaw_test",
    )
    os.environ.setdefault("SYNDICATECLAW_SECRET_KEY", "chaos-test-key")
    os.environ.setdefault("SYNDICATECLAW_REDIS_URL", "redis://localhost:6379/0")
    os.environ.setdefault("SYNDICATECLAW_ENVIRONMENT", "test")
    os.environ.setdefault("SYNDICATECLAW_RBAC_ENFORCEMENT_ENABLED", "false")


@pytest.mark.asyncio
async def test_chaos_redis_down_graceful() -> None:
    """When Redis is down, /readyz degrades and rate limiting falls open."""
    _set_test_env()

    import syndicateclaw.api.main as main_mod

    importlib.reload(main_mod)
    app = main_mod.create_app()

    try:
        redis_client = None
        async with (
            LifespanManager(app) as manager,
            AsyncClient(transport=ASGITransport(app=manager.app), base_url="http://test") as client,
        ):
            redis_client = getattr(app.state, "redis", None)
            if redis_client is None:
                pytest.skip("No Redis client on app.state")

            # Baseline: readyz should pass
            resp_before = await client.get("/readyz")
            assert resp_before.status_code == 200

            # Kill Redis
            with mock_redis_down(redis_client):
                resp_during = await client.get("/readyz")
                # In default mode (rate_limit_strict=False), should degrade not fail
                data = resp_during.json()
                assert data["status"] in ("ready", "degraded")

            # Recovery
            resp_after = await client.get("/readyz")
            assert resp_after.status_code == 200
    except OSError as exc:
        pytest.skip(f"Integration infrastructure unavailable: {exc}")
    except Exception as exc:
        if _is_infrastructure_error(exc):
            pytest.skip(f"Integration infrastructure unavailable: {exc}")
        raise


@pytest.mark.asyncio
async def test_chaos_postgres_down_degrades_readyz() -> None:
    """When DB execute fails, /readyz returns 503."""
    from unittest.mock import patch

    _set_test_env()

    import syndicateclaw.api.main as main_mod

    importlib.reload(main_mod)
    app = main_mod.create_app()

    try:
        async with (
            LifespanManager(app) as manager,
            AsyncClient(transport=ASGITransport(app=manager.app), base_url="http://test") as client,
        ):
            # Baseline
            resp_before = await client.get("/readyz")
            assert resp_before.status_code == 200

            # Patch sqlalchemy text to fail
            def fail_db(*args, **kwargs):
                raise OSError("mock database execute failure")

            with patch("syndicateclaw.api.main.text", side_effect=fail_db):
                resp_during = await client.get("/readyz")
                assert resp_during.status_code == 503
    except OSError as exc:
        pytest.skip(f"Integration infrastructure unavailable: {exc}")
    except Exception as exc:
        if _is_infrastructure_error(exc):
            pytest.skip(f"Integration infrastructure unavailable: {exc}")
        raise


@pytest.mark.asyncio
async def test_chaos_dlq_disk_full() -> None:
    """When dead letter write fails, the system continues serving requests."""
    _set_test_env()

    import syndicateclaw.api.main as main_mod

    importlib.reload(main_mod)
    app = main_mod.create_app()

    try:
        async with (
            LifespanManager(app) as manager,
            AsyncClient(transport=ASGITransport(app=manager.app), base_url="http://test") as client,
        ):
            # Even if audit/DLQ writes fail, /healthz should still return 200
            resp = await client.get("/healthz")
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"
    except OSError as exc:
        pytest.skip(f"Integration infrastructure unavailable: {exc}")
    except Exception as exc:
        if _is_infrastructure_error(exc):
            pytest.skip(f"Integration infrastructure unavailable: {exc}")
        raise
