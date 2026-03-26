"""Unit tests for bounded HTTPS fetch (redirects, size cap, HTTP errors)."""

from __future__ import annotations

import httpx
import pytest

from syndicateclaw.inference.catalog_sync.errors import ModelsDevFetchError, SSRFBlockedError
from syndicateclaw.inference.catalog_sync.fetch import fetch_https_bytes_bounded


@pytest.mark.asyncio
async def test_post_redirect_dns_safe_then_second_hop_literal_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_resolve(host: str) -> list[str]:
        if host == "a.models.dev":
            return ["8.8.8.8"]
        return []

    monkeypatch.setattr(
        "syndicateclaw.inference.catalog_sync.ssrf.resolve_hostname_ips",
        fake_resolve,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "a.models.dev":
            return httpx.Response(302, headers={"Location": "https://127.0.0.1/y"})
        return httpx.Response(200, content=b"[]")

    transport = httpx.MockTransport(handler)
    with pytest.raises(SSRFBlockedError):
        await fetch_https_bytes_bounded(
            url="https://a.models.dev/start",
            allowed_host_suffixes=("models.dev",),
            timeout_seconds=5.0,
            max_bytes=1024,
            max_redirects=8,
            transport=transport,
        )


@pytest.mark.asyncio
async def test_response_exceeds_max_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_resolve(_host: str) -> list[str]:
        return ["8.8.8.8"]

    monkeypatch.setattr(
        "syndicateclaw.inference.catalog_sync.ssrf.resolve_hostname_ips",
        fake_resolve,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 5000)

    transport = httpx.MockTransport(handler)
    with pytest.raises(ModelsDevFetchError) as ei:
        await fetch_https_bytes_bounded(
            url="https://b.models.dev/huge",
            allowed_host_suffixes=("models.dev",),
            timeout_seconds=5.0,
            max_bytes=100,
            max_redirects=8,
            transport=transport,
        )
    assert ei.value.args[0] == "response_exceeds_max_bytes"


@pytest.mark.asyncio
async def test_http_error_wraps(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_resolve(_host: str) -> list[str]:
        return ["8.8.8.8"]

    monkeypatch.setattr(
        "syndicateclaw.inference.catalog_sync.ssrf.resolve_hostname_ips",
        fake_resolve,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, content=b"no")

    transport = httpx.MockTransport(handler)
    with pytest.raises(ModelsDevFetchError) as ei:
        await fetch_https_bytes_bounded(
            url="https://c.models.dev/down",
            allowed_host_suffixes=("models.dev",),
            timeout_seconds=5.0,
            max_bytes=1024,
            max_redirects=8,
            transport=transport,
        )
    assert "http_503" in ei.value.args[0]


@pytest.mark.asyncio
async def test_too_many_redirects(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_resolve(_host: str) -> list[str]:
        return ["8.8.8.8"]

    monkeypatch.setattr(
        "syndicateclaw.inference.catalog_sync.ssrf.resolve_hostname_ips",
        fake_resolve,
    )

    n = [0]

    def handler(request: httpx.Request) -> httpx.Response:
        n[0] += 1
        return httpx.Response(302, headers={"Location": f"https://d.models.dev/r{n[0]}"})

    transport = httpx.MockTransport(handler)
    with pytest.raises(ModelsDevFetchError) as ei:
        await fetch_https_bytes_bounded(
            url="https://d.models.dev/r0",
            allowed_host_suffixes=("models.dev",),
            timeout_seconds=5.0,
            max_bytes=1024,
            max_redirects=2,
            transport=transport,
        )
    assert ei.value.args[0] == "too_many_redirects"
