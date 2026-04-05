from __future__ import annotations

import os

from fastapi.routing import APIRoute

os.environ.setdefault(
    "SYNDICATECLAW_DATABASE_URL",
    "postgresql+asyncpg://syndicateclaw:syndicateclaw@127.0.0.1:5432/syndicateclaw_test",
)
os.environ.setdefault("SYNDICATECLAW_SECRET_KEY", "test-secret-key-not-for-production")

from syndicateclaw.api.main import create_app
from syndicateclaw.authz.permissions import PERMISSION_VOCABULARY
from syndicateclaw.authz.route_registry import (
    ROUTE_REGISTRY,
    _normalize_path,
    get_required_permission,
)


def test_all_registered_routes_have_permissions() -> None:
    app = create_app()
    exempt_paths = {"/docs", "/redoc", "/openapi.json", "/metrics"}

    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if route.path in exempt_paths:
            continue

        for method in route.methods:
            if method in {"HEAD", "OPTIONS"}:
                continue

            permission = get_required_permission(method, route.path)
            assert permission != "DENY", (
                f"Route missing from ROUTE_REGISTRY: {(method, route.path)} "
                f"(normalized={_normalize_path(route.path)})"
            )


def test_route_registry_permission_strings_valid() -> None:
    for key, permission in ROUTE_REGISTRY.items():
        if permission is None:
            continue
        assert permission in PERMISSION_VOCABULARY, (
            f"Invalid permission in ROUTE_REGISTRY for {key}: {permission}"
        )
