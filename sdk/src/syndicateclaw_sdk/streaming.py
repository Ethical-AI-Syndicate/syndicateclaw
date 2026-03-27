"""SSE streaming using short-lived streaming tokens (never primary JWT in URL)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from syndicateclaw_sdk.exceptions import SyndicateClawError


class StreamingSession:
    """Acquires a streaming token per connection attempt; reconnects with a new token."""

    def __init__(self, client: httpx.AsyncClient, run_id: str) -> None:
        self._http = client
        self._run_id = run_id

    async def stream_events(self) -> AsyncIterator[dict[str, Any]]:
        while True:
            tok_resp = await self._http.post(f"/api/v1/runs/{self._run_id}/streaming-token")
            tok_resp.raise_for_status()
            streaming_token = tok_resp.json().get("streaming_token")
            if not streaming_token:
                raise SyndicateClawError("streaming_token missing in response")
            url = f"/api/v1/runs/{self._run_id}/stream?token={streaming_token}"
            async with self._http.stream("GET", url) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if not payload:
                        continue
                    try:
                        event = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    yield event
                    if str(event.get("type")) == "run_complete":
                        return
