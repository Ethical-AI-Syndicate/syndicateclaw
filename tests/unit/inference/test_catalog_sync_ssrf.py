"""Unit tests for models.dev SSRF hostname / DNS policy."""

from __future__ import annotations

import pytest

from syndicateclaw.inference.catalog_sync.ssrf import (
    assert_safe_url,
    hostname_allowed_for_suffixes,
    ip_address_is_blocked,
)


def test_hostname_suffix_allowlist() -> None:
    assert hostname_allowed_for_suffixes("api.models.dev", ("models.dev",)) is True
    assert hostname_allowed_for_suffixes("models.dev", ("models.dev",)) is True
    assert hostname_allowed_for_suffixes("evilmodels.dev", ("models.dev",)) is False


@pytest.mark.asyncio
async def test_literal_loopback_v4_not_in_suffix_allowlist() -> None:
    from syndicateclaw.inference.catalog_sync.errors import SSRFBlockedError

    with pytest.raises(SSRFBlockedError) as ei:
        await assert_safe_url(
            "https://127.0.0.1/feed",
            allowed_host_suffixes=("models.dev",),
        )
    assert ei.value.args[0] == "host_not_in_allowlist"


@pytest.mark.asyncio
async def test_literal_loopback_v6_not_in_suffix_allowlist() -> None:
    from syndicateclaw.inference.catalog_sync.errors import SSRFBlockedError

    with pytest.raises(SSRFBlockedError) as ei:
        await assert_safe_url(
            "https://[::1]/x",
            allowed_host_suffixes=("models.dev",),
        )
    assert ei.value.args[0] == "host_not_in_allowlist"


@pytest.mark.asyncio
async def test_resolved_private_ip_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    from syndicateclaw.inference.catalog_sync.errors import SSRFBlockedError

    async def fake_resolve(_hostname: str) -> list[str]:
        return ["10.0.0.1"]

    monkeypatch.setattr(
        "syndicateclaw.inference.catalog_sync.ssrf.resolve_hostname_ips",
        fake_resolve,
    )

    with pytest.raises(SSRFBlockedError) as ei:
        await assert_safe_url(
            "https://cdn.models.dev/data.json",
            allowed_host_suffixes=("models.dev",),
        )
    assert str(ei.value.args[0]).startswith("blocked_resolved:")


def test_ip_address_is_blocked_covers_common_ranges() -> None:
    import ipaddress

    assert ip_address_is_blocked(ipaddress.ip_address("127.0.0.1")) is True
    assert ip_address_is_blocked(ipaddress.ip_address("::1")) is True
    assert ip_address_is_blocked(ipaddress.ip_address("169.254.169.254")) is True
    assert ip_address_is_blocked(ipaddress.ip_address("fe80::1")) is True
    assert ip_address_is_blocked(ipaddress.ip_address("8.8.8.8")) is False
