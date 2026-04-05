from __future__ import annotations

import inspect
import os


def test_startup_configures_system_engine_permissions() -> None:
    os.environ.setdefault(
        "SYNDICATECLAW_DATABASE_URL",
        "postgresql+asyncpg://syndicateclaw:syndicateclaw@127.0.0.1:5432/syndicateclaw_test",
    )
    os.environ.setdefault("SYNDICATECLAW_SECRET_KEY", "test-secret-key-not-for-production")
    import syndicateclaw.api.main as main_mod

    source = inspect.getsource(main_mod.configure_system_engine)
    assert "system:engine" in source
    assert "run:control" in source
    assert "tool:execute" in source
