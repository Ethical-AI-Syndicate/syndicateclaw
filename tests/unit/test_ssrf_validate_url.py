"""Regression: user-controlled URLs must not reach internal/reserved addresses."""

from __future__ import annotations

import socket
from typing import Any

import httpcore
import httpx
import pytest

from syndicateclaw.security.ssrf import PinnedIPAsyncTransport, SSRFError, validate_url


class _RecordingPool:
    def __init__(self) -> None:
        self.requests: list[httpcore.Request] = []
        self.closed = False

    async def handle_async_request(self, request: httpcore.Request) -> httpcore.Response:
        self.requests.append(request)
        return httpcore.Response(200, headers=[], content=b"ok")

    async def aclose(self) -> None:
        self.closed = True


def _install_recording_pool(transport: PinnedIPAsyncTransport) -> _RecordingPool:
    pool = _RecordingPool()
    transport._pool = pool  # type: ignore[attr-defined]
    return pool


def _header_map(request: httpcore.Request) -> dict[bytes, bytes]:
    return {name.lower(): value for name, value in request.headers}


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "https://10.0.0.1/path",
        "http://192.168.0.1/",
        "http://172.16.0.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://100.64.0.1/",
        "http://198.18.0.1/",
        "http://[::ffff:127.0.0.1]/",
        "http://[::1]/",
    ],
)
def test_validate_url_blocks_private_and_loopback(url: str) -> None:
    with pytest.raises(SSRFError):
        validate_url(url)


def test_validate_url_rejects_non_http_scheme() -> None:
    with pytest.raises(SSRFError, match="Unsupported scheme"):
        validate_url("file:///etc/passwd")


def test_validate_url_rejects_missing_hostname() -> None:
    with pytest.raises(SSRFError, match="Missing hostname"):
        validate_url("http:///nohost")


@pytest.mark.asyncio
async def test_pinned_transport_connects_to_pinned_ip_not_resolved_hostname() -> None:
    transport = PinnedIPAsyncTransport(
        pinned_ip="93.184.216.34",
        hostname="rebind.example",
        scheme="https",
        port=443,
        timeout=5.0,
    )
    pool = _install_recording_pool(transport)

    request = httpx.Request("GET", "https://rebind.example/path?x=1")
    response = await transport.handle_async_request(request)

    assert response.status_code == 200
    assert pool.requests[0].url.host == b"93.184.216.34"
    assert pool.requests[0].url.target == b"/path?x=1"
    assert _header_map(pool.requests[0])[b"host"] == b"rebind.example"
    assert pool.requests[0].extensions["sni_hostname"] == "rebind.example"


@pytest.mark.asyncio
async def test_dns_rebinding_cannot_trigger_second_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def fake_getaddrinfo(*args: Any, **kwargs: Any) -> list[Any]:
        nonlocal calls
        calls += 1
        ip = "93.184.216.34" if calls == 1 else "169.254.169.254"
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, 443))]

    monkeypatch.setattr("syndicateclaw.security.ssrf.socket.getaddrinfo", fake_getaddrinfo)

    url = "https://rebind.example/data"
    pinned_ip = validate_url(url)
    transport = PinnedIPAsyncTransport(
        pinned_ip=pinned_ip,
        hostname="rebind.example",
        scheme="https",
        port=443,
        timeout=5.0,
    )
    pool = _install_recording_pool(transport)

    await transport.handle_async_request(httpx.Request("GET", url))

    assert calls == 1
    assert pool.requests[0].url.host == b"93.184.216.34"


@pytest.mark.asyncio
async def test_pinned_transport_preserves_host_header_for_ipv6_pinned_address() -> None:
    ipv6 = "2606:2800:220:1:248:1893:25c8:1946"
    transport = PinnedIPAsyncTransport(
        pinned_ip=ipv6,
        hostname="ipv6.example.com",
        scheme="https",
        port=443,
        timeout=5.0,
    )
    pool = _install_recording_pool(transport)

    await transport.handle_async_request(httpx.Request("GET", "https://ipv6.example.com/v6"))

    assert pool.requests[0].url.host == ipv6.encode("ascii")
    assert _header_map(pool.requests[0])[b"host"] == b"ipv6.example.com"
    assert pool.requests[0].extensions["sni_hostname"] == "ipv6.example.com"


@pytest.mark.parametrize(
    "blocked_ip",
    ["127.0.0.1", "169.254.169.254", "10.0.0.1", "::1"],
)
def test_pinned_transport_rechecks_blocked_ip_at_construction(blocked_ip: str) -> None:
    with pytest.raises(SSRFError, match="Blocked private IP"):
        PinnedIPAsyncTransport(
            pinned_ip=blocked_ip,
            hostname="example.com",
            scheme="https",
            port=443,
        )


def test_dns_resolution_mixed_ipv4_ipv6_prefers_safe_public_or_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_getaddrinfo(*args: Any, **kwargs: Any) -> list[Any]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443)),
            (socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("::1", 443, 0, 0)),
        ]

    monkeypatch.setattr("syndicateclaw.security.ssrf.socket.getaddrinfo", fake_getaddrinfo)

    with pytest.raises(SSRFError, match="Blocked private IP"):
        validate_url("https://mixed.example/data")
