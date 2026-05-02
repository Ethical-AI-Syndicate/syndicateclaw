from __future__ import annotations

import ipaddress
import socket
import ssl
from collections.abc import AsyncIterable, Iterable
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import urlparse

import httpcore
import httpx
import structlog
from httpx._transports.default import AsyncResponseStream

logger = structlog.get_logger(__name__)


class SSRFError(ValueError):
    """Raised when a URL or resolved address is not safe for outbound access."""

    def __init__(self, message_or_url: str, reason: str | None = None) -> None:
        if reason:
            super().__init__(f"SSRF blocked: {reason} (url={message_or_url})")
        else:
            super().__init__(message_or_url)


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
    # Allow only globally routable addresses to reduce maintenance burden and
    # cover reserved ranges (CGNAT, benchmark/test nets, mapped loopback, etc.)
    # without relying on a static blocklist.
    return not ip_obj.is_global


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


def _host_header(hostname: str, scheme: str, port: int) -> str:
    default_port = _default_port_for_scheme(scheme)
    if port == default_port:
        return hostname
    return f"{hostname}:{port}"


def assert_safe_url(url: str) -> str:
    """
    Validate a URL for outbound use and return the pinned public IP.

    This preserves the existing policy behavior:
    - only http/https
    - hostname required
    - all resolved addresses must be public / non-blocked
    """
    return resolve_safe_url(url).resolved_ip


class PinnedIPAsyncTransport(httpx.AsyncBaseTransport):
    """
    Async transport that connects to a pre-validated IP address.

    The logical request URL remains the original hostname, but the underlying
    TCP connection target is rewritten to the pinned IP. HTTPS requests preserve
    the original hostname for SNI and certificate verification.
    """

    def __init__(
        self,
        *,
        pinned_ip: str,
        hostname: str,
        scheme: str,
        port: int,
        timeout: float = 30.0,
    ) -> None:
        if scheme not in {"http", "https"}:
            raise SSRFError(f"Unsupported URL scheme '{scheme}'")

        try:
            ip_obj = ipaddress.ip_address(pinned_ip)
        except ValueError as exc:
            raise SSRFError(f"Invalid pinned IP address '{pinned_ip}'") from exc

        if _is_blocked_ip(str(ip_obj)):
            raise SSRFError(f"Blocked private IP: {ip_obj}")

        self._pinned_ip = str(ip_obj)
        self._hostname = hostname.lower().rstrip(".")
        self._scheme = scheme
        self._port = port
        self._timeout = timeout
        self._host_header = _host_header(self._hostname, self._scheme, self._port)

        ssl_context = ssl.create_default_context() if self._scheme == "https" else None
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl_context,
            max_connections=10,
            max_keepalive_connections=5,
            keepalive_expiry=15.0,
            retries=0,
            http1=True,
            http2=False,
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        request_scheme = str(request.url.scheme)
        request_host = (request.url.host or "").lower().rstrip(".")
        request_port = request.url.port or _default_port_for_scheme(request_scheme)

        if request_scheme != self._scheme:
            raise SSRFError(f"Scheme mismatch: request={request_scheme}, pinned={self._scheme}")
        if request_host != self._hostname:
            raise SSRFError(f"Host mismatch: request={request_host}, pinned={self._hostname}")
        if request_port != self._port:
            raise SSRFError(f"Port mismatch: request={request_port}, pinned={self._port}")

        request.headers["Host"] = self._host_header
        rewritten = request.url.copy_with(host=self._pinned_ip, port=self._port)
        target = rewritten.raw_path or b"/"

        extensions: dict[str, Any] = {
            "timeout": {
                "connect": self._timeout,
                "read": self._timeout,
                "write": self._timeout,
                "pool": self._timeout,
            },
        }
        if self._scheme == "https":
            extensions["sni_hostname"] = self._hostname

        core_request = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=rewritten.scheme.encode("ascii"),
                host=rewritten.host.encode("ascii"),
                port=rewritten.port,
                target=target,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=extensions,
        )

        core_response = await self._pool.handle_async_request(core_request)
        return httpx.Response(
            status_code=core_response.status,
            headers=core_response.headers,
            stream=AsyncResponseStream(cast(AsyncIterable[bytes], core_response.stream)),
            request=request,
            extensions=core_response.extensions,
        )

    async def aclose(self) -> None:
        await self._pool.aclose()


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
        raise SSRFError(url, f"Blocked private IP: {blocked[0]}")

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
