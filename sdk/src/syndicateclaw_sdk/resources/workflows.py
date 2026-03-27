"""Workflows resource (minimal)."""

from __future__ import annotations

from typing import Any

import httpx


class WorkflowsResource:
    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http

    async def list(self) -> list[dict[str, Any]]:
        r = await self._http.get("/api/v1/workflows")
        r.raise_for_status()
        return list(r.json())
