"""Async HTTP client for SyndicateClaw."""

from __future__ import annotations

from typing import Any

import httpx
from packaging.version import Version

from syndicateclaw_sdk.exceptions import IncompatibleServerError


class SyndicateClaw:
    """Async API client with optional server version gate."""

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | None = None,
        token: str | None = None,
        timeout: float = 30.0,
        min_server_version: str = "1.5.0",
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if http_client is not None:
            self._http = http_client
        else:
            headers: dict[str, str] = {}
            if api_key:
                headers["X-API-Key"] = api_key
            if token:
                headers["Authorization"] = f"Bearer {token}"
            self._http = httpx.AsyncClient(
                base_url=base_url.rstrip("/"), headers=headers, timeout=timeout
            )
        self._min_server_version = min_server_version

    async def aclose(self) -> None:
        await self._http.aclose()

    async def ensure_compatible(self) -> None:
        """Call GET /api/v1/info and raise if server is older than ``min_server_version``."""
        r = await self._http.get("/api/v1/info")
        r.raise_for_status()
        body = r.json()
        server_version = str(body.get("version", "0.0.0"))
        if Version(server_version) < Version(self._min_server_version):
            raise IncompatibleServerError(
                required=self._min_server_version,
                actual=server_version,
            )

    async def health(self) -> dict[str, Any]:
        r = await self._http.get("/healthz")
        r.raise_for_status()
        return {"status_code": r.status_code, "text": r.text}
