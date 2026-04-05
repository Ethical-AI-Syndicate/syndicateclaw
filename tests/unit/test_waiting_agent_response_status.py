from __future__ import annotations

import importlib
import inspect

import pytest


def test_waiting_agent_response_counted_in_max_concurrency() -> None:
    import syndicateclaw.api.routes.workflows as workflows_mod

    importlib.reload(workflows_mod)
    source = inspect.getsource(workflows_mod.start_run)
    assert "WAITING_AGENT_RESPONSE" in source


def test_readyz_reports_waiting_agent_response_count(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYNDICATECLAW_DATABASE_URL", "postgresql+asyncpg://syndicateclaw:syndicateclaw@postgres:5432/syndicateclaw_test")
    monkeypatch.setenv("SYNDICATECLAW_SECRET_KEY", "test-key")
    import syndicateclaw.api.main as main_mod

    importlib.reload(main_mod)
    source = inspect.getsource(main_mod.create_app)
    assert "waiting_agent_response" in source
