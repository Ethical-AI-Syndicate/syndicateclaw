import os

import pytest


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        item.add_marker(pytest.mark.unit)
        if "db_engine" in getattr(item, "fixturenames", ()):
            item.add_marker(pytest.mark.integration)


@pytest.fixture(scope="session", autouse=True)
async def seed_rbac_for_tests() -> None:
    """Unit tests must not run the live PostgreSQL RBAC seed subprocess."""
    return None


@pytest.fixture(autouse=True)
def _unit_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Ensure any Settings() calls in unit tests get a valid fallback
    monkeypatch.setenv(
        "SYNDICATECLAW_DATABASE_URL",
        os.environ.get("SYNDICATECLAW_DATABASE_URL")
        or "postgresql+asyncpg://syndicateclaw:syndicateclaw@localhost:5432/syndicateclaw_test",
    )
    monkeypatch.setenv(
        "SYNDICATECLAW_REDIS_URL",
        os.environ.get("SYNDICATECLAW_REDIS_URL") or "redis://localhost:6379/0",
    )
