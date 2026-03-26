"""Size-bounded HTTPS fetch with manual redirects and per-hop SSRF validation."""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

import httpx

from syndicateclaw.inference.catalog_sync.errors import ModelsDevFetchError
from syndicateclaw.inference.catalog_sync.ssrf import assert_safe_url

_REDIRECT_STATUS = frozenset({301, 302, 303, 307, 308})


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
    timeout = httpx.Timeout(timeout_seconds, connect=min(30.0, timeout_seconds))
    current = url
    redirects = 0

    client_kw: dict[str, Any] = {"timeout": timeout, "verify": True, "http2": False}
    if transport is not None:
        client_kw["transport"] = transport

    async with httpx.AsyncClient(**client_kw) as client:
        while True:
            # SSRF-hardened: assert_safe_url before each hop (incl. redirects)
            await assert_safe_url(current, allowed_host_suffixes=allowed_host_suffixes)

            async with client.stream("GET", current) as resp:
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
