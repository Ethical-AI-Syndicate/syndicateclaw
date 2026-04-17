from __future__ import annotations

import importlib

import pytest
from asgi_lifespan import LifespanManager

from syndicateclaw.security.auth import validate_hs256_secret_strength


def test_validate_hs256_secret_strength_rejects_short_key() -> None:
    with pytest.raises(ValueError, match="at least 32 bytes"):
        validate_hs256_secret_strength("too-short")


def test_validate_hs256_secret_strength_accepts_32_bytes() -> None:
    validate_hs256_secret_strength("k" * 32)


@pytest.mark.asyncio
async def test_startup_rejects_short_hs256_secret_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "SYNDICATECLAW_DATABASE_URL",
        "postgresql+asyncpg://user:pass@localhost:5432/test_db",
    )
    monkeypatch.setenv("SYNDICATECLAW_REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("SYNDICATECLAW_ENVIRONMENT", "production")
    monkeypatch.setenv("SYNDICATECLAW_JWT_ALGORITHM", "HS256")
    monkeypatch.setenv("SYNDICATECLAW_SECRET_KEY", "short-key")

    import syndicateclaw.api.main as main_mod
    import syndicateclaw.db.base as db_base

    importlib.reload(main_mod)
    monkeypatch.setattr(
        db_base,
        "get_engine",
        lambda _db_url: (_ for _ in ()).throw(RuntimeError("db-should-not-be-touched")),
    )
    app = main_mod.create_app()

    with pytest.raises(ValueError, match="SYNDICATECLAW_SECRET_KEY"):
        async with LifespanManager(app):
            pass


@pytest.mark.asyncio
async def test_startup_allows_short_hs256_secret_in_test_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "SYNDICATECLAW_DATABASE_URL",
        "postgresql+asyncpg://user:pass@localhost:5432/test_db",
    )
    monkeypatch.setenv("SYNDICATECLAW_REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("SYNDICATECLAW_ENVIRONMENT", "test")
    monkeypatch.setenv("SYNDICATECLAW_JWT_ALGORITHM", "HS256")
    monkeypatch.setenv("SYNDICATECLAW_SECRET_KEY", "short-key")

    import syndicateclaw.api.main as main_mod
    import syndicateclaw.db.base as db_base

    importlib.reload(main_mod)
    monkeypatch.setattr(
        db_base,
        "get_engine",
        lambda _db_url: (_ for _ in ()).throw(RuntimeError("db-reached")),
    )
    app = main_mod.create_app()

    with pytest.raises(RuntimeError, match="db-reached"):
        async with LifespanManager(app):
            pass
