from __future__ import annotations

import ipaddress
import socket
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import structlog

logger = structlog.get_logger(__name__)


class SSRFError(ValueError):
    """Raised when a URL or resolved address is not safe for outbound access."""

    def __init__(self, message_or_url: str, reason: str | None = None) -> None:
        if reason:
            super().__init__(f"SSRF blocked: {reason} (url={message_or_url})")
        else:
            super().__init__(message_or_url)


_BLOCKED_NETWORKS = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fd00::/8"),
    ipaddress.ip_network("fe80::/10"),
)


@dataclass(frozen=True)
class ResolvedSafeURL:
    original_url: str
    scheme: str
    hostname: str
    port: int
    resolved_ip: str
    path_and_query: str


def _is_blocked_ip(ip_str: str) -> bool:
    ip_obj = ipaddress.ip_address(ip_str)
    return any(ip_obj in network for network in _BLOCKED_NETWORKS)


def _iter_resolved_ips(hostname: str, port: int) -> Iterable[str]:
    try:
        infos = socket.getaddrinfo(
            hostname,
            port,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
    except socket.gaierror as exc:
        raise SSRFError(f"DNS resolution failed for host '{hostname}': {exc}") from exc

    seen: set[str] = set()
    for info in infos:
        sockaddr = info[4]
        ip = str(sockaddr[0])
        if ip not in seen:
            seen.add(ip)
            yield ip


def _default_port_for_scheme(scheme: str) -> int:
    if scheme == "https":
        return 443
    if scheme == "http":
        return 80
    raise SSRFError(f"Unsupported URL scheme '{scheme}'")


def _path_and_query_from_parsed(parsed: Any) -> str:
    path = parsed.path or "/"
    if parsed.query:
        return f"{path}?{parsed.query}"
    return path


def assert_safe_url(url: str) -> bool:
    """
    Validate a URL for outbound use.

    This preserves the existing policy behavior:
    - only http/https
    - hostname required
    - all resolved addresses must be public / non-blocked
    """
    parsed = urlparse(url)

    if parsed.scheme not in {"http", "https"}:
        raise SSRFError(url, f"Unsupported scheme: {parsed.scheme!r}")

    if not parsed.hostname:
        raise SSRFError(url, "Missing hostname")

    port = parsed.port or _default_port_for_scheme(parsed.scheme)

    resolved_any = False
    for ip in _iter_resolved_ips(parsed.hostname, port):
        resolved_any = True
        if _is_blocked_ip(ip):
            raise SSRFError(url, f"Blocked private IP: {ip}")

    if not resolved_any:
        raise SSRFError(f"No IP addresses resolved for host '{parsed.hostname}'")

    return True


def resolve_safe_url(url: str) -> ResolvedSafeURL:
    """
    Resolve once, validate once, and return a pinned outbound target.

    This is the primitive callers must use when they need TOCTOU-safe outbound fetches.
    """
    parsed = urlparse(url)

    if parsed.scheme not in {"http", "https"}:
        raise SSRFError(url, f"Unsupported scheme: {parsed.scheme!r}")

    if not parsed.hostname:
        raise SSRFError(url, "Missing hostname")

    port = parsed.port or _default_port_for_scheme(parsed.scheme)

    resolved_ips = list(_iter_resolved_ips(parsed.hostname, port))
    if not resolved_ips:
        raise SSRFError(f"No IP addresses resolved for host '{parsed.hostname}'")

    blocked = [ip for ip in resolved_ips if _is_blocked_ip(ip)]
    if blocked:
        raise SSRFError(
            f"Resolved host '{parsed.hostname}' to blocked address(es): {', '.join(blocked)}"
        )

    # Deterministic selection. This intentionally trades some CDN flexibility
    # for a stable, single-resolution security boundary.
    pinned_ip = sorted(resolved_ips)[0]

    return ResolvedSafeURL(
        original_url=url,
        scheme=parsed.scheme,
        hostname=parsed.hostname,
        port=port,
        resolved_ip=pinned_ip,
        path_and_query=_path_and_query_from_parsed(parsed),
    )


validate_url = assert_safe_url
