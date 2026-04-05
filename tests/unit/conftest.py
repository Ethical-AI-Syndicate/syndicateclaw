import pytest
import os

@pytest.fixture(autouse=True)
def _unit_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Ensure any Settings() calls in unit tests get a valid fallback
    monkeypatch.setenv(
        "SYNDICATECLAW_DATABASE_URL",
        os.environ.get("SYNDICATECLAW_DATABASE_URL") or "postgresql+asyncpg://syndicateclaw:syndicateclaw@localhost:5432/syndicateclaw_test"
    )
    monkeypatch.setenv(
        "SYNDICATECLAW_REDIS_URL",
        os.environ.get("SYNDICATECLAW_REDIS_URL") or "redis://localhost:6379/0"
    )
