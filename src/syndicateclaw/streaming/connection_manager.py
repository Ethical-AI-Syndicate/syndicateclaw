from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)

    async def subscribe(self, run_id: str) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
        self._connections[run_id].add(q)
        return q

    async def unsubscribe(self, run_id: str, q: asyncio.Queue[dict[str, Any]]) -> None:
        self._connections[run_id].discard(q)

    async def broadcast(self, run_id: str, event: dict[str, Any]) -> None:
        dead: set[asyncio.Queue[dict[str, Any]]] = set()
        for q in list(self._connections.get(run_id, set())):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                dead.add(q)
        for q in dead:
            self._connections[run_id].discard(q)


connection_manager = ConnectionManager()
