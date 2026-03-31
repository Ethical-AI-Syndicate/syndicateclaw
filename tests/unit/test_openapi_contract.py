"""OpenAPI schema contract tests — validate schema stability and correctness."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _set_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set required env vars for Settings() construction."""
    monkeypatch.setenv("SYNDICATECLAW_DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/test")
    monkeypatch.setenv("SYNDICATECLAW_SECRET_KEY", "test-key-for-contract-tests")


def test_openapi_schema_is_valid() -> None:
    """The generated OpenAPI schema must be well-formed."""
    from syndicateclaw.api.main import create_app

    app = create_app()
    schema = app.openapi()

    assert "openapi" in schema
    assert schema["openapi"].startswith("3.")
    assert "paths" in schema
    assert "info" in schema


def test_openapi_schema_has_all_routes() -> None:
    """All registered routes must appear in the OpenAPI schema."""
    from syndicateclaw.api.main import create_app

    app = create_app()
    schema = app.openapi()
    schema_paths = set(schema["paths"].keys())

    expected_routes = [
        "/healthz",
        "/readyz",
        "/api/v1/workflows/",
        "/api/v1/tools/",
        "/api/v1/memory/",
        "/api/v1/policy/",
        "/api/v1/audit/",
        "/api/v1/agents/",
        "/api/v1/inference/",
        "/api/v1/approvals/",
    ]

    for route in expected_routes:
        assert route in schema_paths, f"Route {route} missing from OpenAPI schema"


def test_openapi_schema_stability() -> None:
    """Detect unintended schema changes by checking key properties."""
    from syndicateclaw.api.main import create_app

    app = create_app()
    schema = app.openapi()

    assert "version" in schema["info"]
    assert schema["info"]["version"] != ""
    assert len(schema["paths"]) > 10
