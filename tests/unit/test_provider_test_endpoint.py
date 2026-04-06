from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from syndicateclaw.api.dependencies import get_current_actor, get_provider_loader
from syndicateclaw.api.routes.providers_ops import router as providers_router


@pytest.mark.asyncio
async def test_provider_test_endpoint_returns_generic_unreachable_on_error(monkeypatch) -> None:
    app = FastAPI()
    app.include_router(providers_router)

    loader = SimpleNamespace(
        current=lambda: (
            SimpleNamespace(
                providers=[
                    SimpleNamespace(
                        id="p1",
                        name="provider-1",
                        adapter_protocol="OPENAI_COMPATIBLE",
                        auth=None,
                    )
                ]
            ),
            "1",
        )
    )

    class _Adapter:
        async def infer_chat(self, provider, req, *, api_key=None, bearer_token=None):
            raise RuntimeError("network details should not leak")

    monkeypatch.setattr("syndicateclaw.api.routes.providers_ops.adapter_for", lambda _p: _Adapter())

    app.dependency_overrides[get_current_actor] = lambda: "admin:ops"
    app.dependency_overrides[get_provider_loader] = lambda: loader

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/providers/provider-1/test")

    assert response.status_code == 502
    assert response.json() == {"status": "unreachable", "provider": "provider-1"}
