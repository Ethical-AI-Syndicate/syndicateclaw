"""Async HTTP client for SyndicateClaw."""

from __future__ import annotations

from typing import Any

import httpx


class SyndicateClaw:
    """Minimal async client; resources will be added in later milestones."""

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | None = None,
        token: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        headers: dict[str, str] = {}
        if api_key:
            headers["X-API-Key"] = api_key
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._http = httpx.AsyncClient(base_url=base_url.rstrip("/"), headers=headers, timeout=timeout)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def health(self) -> dict[str, Any]:
        r = await self._http.get("/healthz")
        r.raise_for_status()
        return {"status_code": r.status_code, "text": r.text}
