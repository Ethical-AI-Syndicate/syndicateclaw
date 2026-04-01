"""Size-bounded HTTPS fetch with manual redirects and per-hop SSRF validation."""

from __future__ import annotations

import ssl
from typing import Any
from urllib.parse import urljoin

import httpcore
import httpx

from syndicateclaw.inference.catalog_sync.errors import ModelsDevFetchError
from syndicateclaw.inference.catalog_sync.ssrf import (
    ResolvedSafeURL,
    resolve_safe_url,
)

_REDIRECT_STATUS = frozenset({301, 302, 303, 307, 308})


class PinnedHTTPSyncError(RuntimeError):
    """Raised when the pinned transport is used incorrectly."""


class PinnedIPAsyncTransport(httpx.AsyncBaseTransport):
    """
    Async transport that connects to a pre-validated, pre-resolved IP while preserving
    the original hostname for:
    - Host header
    - TLS SNI / certificate verification

    This closes the DNS TOCTOU window between validation and connection establishment.
    """

    def __init__(self, target: ResolvedSafeURL, *, timeout: float = 30.0) -> None:
        if target.scheme != "https":
            raise PinnedHTTPSyncError("PinnedIPAsyncTransport currently supports HTTPS only")

        self._target = target
        self._timeout = timeout

        ssl_context = ssl.create_default_context()
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
        if request.url.scheme != self._target.scheme:
            raise PinnedHTTPSyncError(
                f"Scheme mismatch: request={request.url.scheme}, target={self._target.scheme}"
            )

        if request.url.host != self._target.hostname:
            raise PinnedHTTPSyncError(
                f"Host mismatch: request={request.url.host}, target={self._target.hostname}"
            )

        if request.url.port not in (None, self._target.port):
            raise PinnedHTTPSyncError(
                f"Port mismatch: request={request.url.port}, target={self._target.port}"
            )

        # Preserve original logical hostname at the HTTP layer.
        request.headers["Host"] = self._target.hostname

        # Rewrite the physical connection target to the pinned IP.
        rewritten = request.url.copy_with(host=self._target.resolved_ip)

        core_request = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=rewritten.scheme.encode("ascii"),
                host=rewritten.host.encode("ascii"),
                port=rewritten.port,
                target=(rewritten.raw_path or b"/")
                + (b"?" + rewritten.query if rewritten.query else b""),
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions={
                "timeout": {
                    "connect": self._timeout,
                    "read": self._timeout,
                    "write": self._timeout,
                    "pool": self._timeout,
                },
                "sni_hostname": self._target.hostname,
            },
        )

        core_response = await self._pool.handle_async_request(core_request)

        return httpx.Response(
            status_code=core_response.status,
            headers=core_response.headers,
            stream=httpx._transports.default.AsyncResponseStream(core_response.stream),  # type: ignore
            request=request,
            extensions=core_response.extensions,
        )

    async def aclose(self) -> None:
        await self._pool.aclose()


async def fetch_https_bytes_bounded(
    *,
    url: str,
    allowed_host_suffixes: tuple[str, ...],
    timeout_seconds: float,
    max_bytes: int,
    max_redirects: int,
    transport: httpx.AsyncBaseTransport | None = None,
) -> bytes:
    """GET with manual redirects; SSRF check runs before each request (including after redirect)."""
    current = url
    redirects = 0

    while True:
        try:
            target = await resolve_safe_url(current, allowed_host_suffixes=allowed_host_suffixes)
        except Exception as e:
            from syndicateclaw.inference.catalog_sync.errors import SSRFBlockedError

            if isinstance(e, SSRFBlockedError):
                raise
            raise ModelsDevFetchError(str(e)) from e

        if target.scheme != "https":
            raise ModelsDevFetchError("only_https_allowed")

        pinned_transport = PinnedIPAsyncTransport(target, timeout=timeout_seconds)

        client_kw: dict[str, Any] = {
            "timeout": timeout_seconds,
            "transport": transport if transport is not None else pinned_transport,
            "follow_redirects": False,
        }

        async with httpx.AsyncClient(**client_kw) as client:
            try:
                async with client.stream("GET", target.original_url) as resp:
                    if resp.status_code in _REDIRECT_STATUS:
                        redirects += 1
                        if redirects > max_redirects:
                            raise ModelsDevFetchError("too_many_redirects")
                        loc = resp.headers.get("location")
                        if not loc:
                            raise ModelsDevFetchError("redirect_missing_location")
                        current = urljoin(current, loc)
                        continue

                    try:
                        resp.raise_for_status()
                    except httpx.HTTPStatusError as e:
                        raise ModelsDevFetchError(f"http_{resp.status_code}") from e

                    total = 0
                    chunks: list[bytes] = []
                    async for chunk in resp.aiter_bytes():
                        total += len(chunk)
                        if total > max_bytes:
                            raise ModelsDevFetchError("response_exceeds_max_bytes")
                        chunks.append(chunk)
                    return b"".join(chunks)
            finally:
                await pinned_transport.aclose()
