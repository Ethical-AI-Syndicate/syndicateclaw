"""SSRF checks: post-redirect URL validation and resolved address blocking."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

from syndicateclaw.inference.catalog_sync.errors import SSRFBlockedError


def hostname_allowed_for_suffixes(hostname: str, allowed_suffixes: tuple[str, ...]) -> bool:
    """Host must equal or end with ``.<suffix>`` for some suffix (e.g. api.models.dev)."""
    h = hostname.lower().rstrip(".")
    for raw in allowed_suffixes:
        s = raw.lower().strip().lstrip(".")
        if h == s or h.endswith("." + s):
            return True
    return False


def ip_address_is_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Block loopback, link-local, private, multicast, reserved; block IPv4-mapped abuse."""
    if ip.is_loopback or ip.is_link_local or ip.is_private or ip.is_multicast:
        return True
    if ip.is_reserved or ip.is_unspecified:
        return True
    if ip.version == 6:
        mapped = getattr(ip, "ipv4_mapped", None)
        if mapped is not None and ip_address_is_blocked(mapped):
            return True
    # AWS metadata endpoint (also link-local; explicit for reviewers)
    return ip.version == 4 and str(ip) == "169.254.169.254"


async def resolve_hostname_ips(hostname: str) -> list[str]:
    """Resolve all A/AAAA records (async via thread pool)."""

    def _resolve() -> list[str]:
        infos = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
        out: list[str] = []
        for _fam, _type, _proto, _canon, sockaddr in infos:
            ip_s = str(sockaddr[0])
            if ip_s not in out:
                out.append(ip_s)
        return out

    return await asyncio.to_thread(_resolve)


async def assert_safe_url(
    url: str,
    *,
    allowed_host_suffixes: tuple[str, ...],
) -> None:
    """Validate scheme, host suffix, and that no resolved IP is blocked.

    Call again after every HTTP redirect with the new absolute URL.
    """
    parsed = urlparse(url)
    if parsed.scheme.lower() != "https":
        raise SSRFBlockedError("only_https_allowed")
    if not parsed.hostname:
        raise SSRFBlockedError("missing_hostname")
    host = parsed.hostname.lower().rstrip(".")
    if not hostname_allowed_for_suffixes(host, allowed_host_suffixes):
        raise SSRFBlockedError("host_not_in_allowlist")

    # Literal IP in URL
    try:
        ip = ipaddress.ip_address(host)
        if ip_address_is_blocked(ip):
            raise SSRFBlockedError("blocked_address_literal")
        return
    except ValueError:
        pass

    try:
        addrs = await resolve_hostname_ips(host)
    except OSError as e:
        raise SSRFBlockedError(f"dns_resolution_failed:{e!s}") from e

    if not addrs:
        raise SSRFBlockedError("no_addresses")

    for a in addrs:
        ip = ipaddress.ip_address(a)
        if ip_address_is_blocked(ip):
            raise SSRFBlockedError(f"blocked_resolved:{a}")
