"""Redis-backed cache for workflow run state JSON (not full ORM rows)."""

from __future__ import annotations

import json
from typing import Any, cast

from redis.asyncio import Redis

TTL_BY_STATUS: dict[str, int] = {
    "RUNNING": 3600,
    "WAITING_APPROVAL": 3600,
    "WAITING_AGENT_RESPONSE": 3600,
    "PAUSED": 600,
    "COMPLETED": 60,
    "FAILED": 60,
    "CANCELLED": 60,
    "PENDING": 3600,
}


class StateCache:
    """Status-aware TTL for serialized run ``state`` dicts."""

    def __init__(self, redis_client: Redis | None) -> None:
        self._redis = redis_client

    def _key(self, run_id: str) -> str:
        return f"syndicateclaw:run_state:{run_id}"

    async def set(self, run_id: str, state: dict[str, Any], status: str) -> None:
        if self._redis is None:
            return
        ttl = TTL_BY_STATUS.get(status, 3600)
        await self._redis.set(
            self._key(run_id),
            json.dumps(state, default=str),
            ex=ttl,
        )

    async def get(self, run_id: str) -> dict[str, Any] | None:
        if self._redis is None:
            return None
        raw = await self._redis.get(self._key(run_id))
        if raw is None:
            return None
        return cast(dict[str, Any], json.loads(raw))

    async def invalidate(self, run_id: str) -> None:
        if self._redis is None:
            return
        await self._redis.delete(self._key(run_id))
