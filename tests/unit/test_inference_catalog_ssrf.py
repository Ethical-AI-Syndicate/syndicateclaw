"""Unit tests for inference/catalog_sync/ssrf.py — covers missing lines."""

from __future__ import annotations

import ipaddress
from unittest.mock import AsyncMock, patch

import pytest

from syndicateclaw.inference.catalog_sync.errors import SSRFBlockedError
from syndicateclaw.inference.catalog_sync.ssrf import (
    assert_safe_url,
    ip_address_is_blocked,
    resolve_hostname_ips,
)

_ALLOWED = ("models.dev",)


# ── ip_address_is_blocked ───────────────────────────────────────────────────


def test_ip_blocked_reserved() -> None:
    # Line 28: ip.is_reserved path (240.0.0.0/4 is reserved)
    assert ip_address_is_blocked(ipaddress.ip_address("240.0.0.0"))


def test_ip_blocked_unspecified() -> None:
    # Line 28: ip.is_unspecified path
    assert ip_address_is_blocked(ipaddress.ip_address("0.0.0.0"))


def test_ip_blocked_ipv6_mapped_private() -> None:
    # Lines 30-32: IPv6-mapped IPv4 private address triggers recursive check
    assert ip_address_is_blocked(ipaddress.ip_address("::ffff:192.168.1.1"))


def test_ip_not_blocked_public() -> None:
    assert not ip_address_is_blocked(ipaddress.ip_address("8.8.8.8"))


# ── resolve_hostname_ips ─────────────────────────────────────────────────────


async def test_resolve_hostname_ips_returns_list() -> None:
    # Lines 40-47, 49: calls socket.getaddrinfo via asyncio.to_thread
    addrs = await resolve_hostname_ips("localhost")
    assert isinstance(addrs, list)
    assert len(addrs) >= 1


# ── assert_safe_url ──────────────────────────────────────────────────────────


async def test_assert_safe_url_rejects_http_scheme() -> None:
    # Line 63: raises SSRFBlockedError for non-https
    with pytest.raises(SSRFBlockedError, match="only_https"):
        await assert_safe_url("http://api.models.dev/", allowed_host_suffixes=_ALLOWED)


async def test_assert_safe_url_rejects_missing_hostname() -> None:
    # Line 65: raises SSRFBlockedError when hostname is absent
    with pytest.raises(SSRFBlockedError):
        await assert_safe_url("https:///path", allowed_host_suffixes=_ALLOWED)


async def test_assert_safe_url_rejects_blocked_literal_ip() -> None:
    # Lines 73-75: literal private IP passes suffix check but is blocked
    with pytest.raises(SSRFBlockedError, match="blocked_address_literal"):
        await assert_safe_url("https://10.0.0.1/", allowed_host_suffixes=("10.0.0.1",))


async def test_assert_safe_url_dns_failure_raises() -> None:
    # Lines 81-82: OSError from resolve_hostname_ips becomes SSRFBlockedError
    with (
        patch(
            "syndicateclaw.inference.catalog_sync.ssrf.resolve_hostname_ips",
            AsyncMock(side_effect=OSError("name not found")),
        ),
        pytest.raises(SSRFBlockedError, match="dns_resolution_failed"),
    ):
        await assert_safe_url("https://api.models.dev/", allowed_host_suffixes=_ALLOWED)


async def test_assert_safe_url_no_addresses_raises() -> None:
    # Line 85: empty address list raises SSRFBlockedError
    with (
        patch(
            "syndicateclaw.inference.catalog_sync.ssrf.resolve_hostname_ips",
            AsyncMock(return_value=[]),
        ),
        pytest.raises(SSRFBlockedError, match="no_addresses"),
    ):
        await assert_safe_url("https://api.models.dev/", allowed_host_suffixes=_ALLOWED)
