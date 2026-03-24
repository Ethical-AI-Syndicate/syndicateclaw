from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import structlog

logger = structlog.get_logger(__name__)

_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fd00::/8"),
]


class SSRFError(Exception):
    """Raised when a URL targets a blocked internal/private address."""

    def __init__(self, url: str, reason: str) -> None:
        self.url = url
        self.reason = reason
        super().__init__(f"SSRF blocked: {reason} (url={url})")


def _is_private(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return any(addr in network for network in _BLOCKED_NETWORKS)


def validate_url(url: str) -> bool:
    """Validate that *url* does not point to an internal / private IP.

    Resolves DNS to defend against DNS-rebinding attacks.

    Raises:
        SSRFError: If the URL targets a blocked address.

    Returns:
        ``True`` if the URL is safe.
    """
    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        raise SSRFError(url, f"Unsupported scheme: {parsed.scheme!r}")

    hostname = parsed.hostname
    if not hostname:
        raise SSRFError(url, "Missing hostname")

    try:
        addr = ipaddress.ip_address(hostname)
        if _is_private(addr):
            raise SSRFError(url, f"Blocked private IP: {addr}")
        return True
    except ValueError:
        pass

    try:
        addrinfos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise SSRFError(url, f"DNS resolution failed: {exc}") from exc

    for family, _, _, _, sockaddr in addrinfos:
        ip_str = sockaddr[0]
        addr = ipaddress.ip_address(ip_str)
        if _is_private(addr):
            raise SSRFError(url, f"Hostname {hostname!r} resolves to blocked IP: {addr}")

    logger.debug("ssrf.url_validated", url=url, hostname=hostname)
    return True
