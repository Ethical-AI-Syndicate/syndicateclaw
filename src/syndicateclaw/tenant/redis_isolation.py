"""Tenant-isolated Redis operations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import redis.asyncio


class TenantRedisIsolator:
    """
    Provides tenant-isolated Redis operations.

    All keys are prefixed with tenant ID to ensure isolation.
    """

    def __init__(self, redis_client: Any, tenant_id: str) -> None:
        self._redis = redis_client
        self._tenant_id = tenant_id

    def _key(self, resource: str, resource_id: str) -> str:
        """Generate tenant-isolated key."""
        return f"syndicateclaw:tenant:{self._tenant_id}:{resource}:{resource_id}"

    def _memory_key(self, namespace: str, key: str) -> str:
        """Generate tenant-isolated memory cache key."""
        return f"syndicateclaw:tenant:{self._tenant_id}:memory:{namespace}:{key}"

    def _rate_limit_key(self, actor: str) -> str:
        """Generate tenant-isolated rate limit key."""
        return f"syndicateclaw:tenant:{self._tenant_id}:ratelimit:{actor}"

    async def get_memory(self, namespace: str, key: str) -> str | None:
        """Get a value from tenant-isolated memory cache."""
        redis_key = self._memory_key(namespace, key)
        return await self._redis.get(redis_key)

    async def set_memory(
        self,
        namespace: str,
        key: str,
        value: str,
        ttl_seconds: int = 300,
    ) -> None:
        """Set a value in tenant-isolated memory cache."""
        redis_key = self._memory_key(namespace, key)
        await self._redis.setex(redis_key, ttl_seconds, value)

    async def delete_memory(self, namespace: str, key: str) -> None:
        """Delete a value from tenant-isolated memory cache."""
        redis_key = self._memory_key(namespace, key)
        await self._redis.delete(redis_key)

    async def get_rate_limit(self, actor: str) -> int:
        """Get rate limit counter for actor."""
        redis_key = self._rate_limit_key(actor)
        value = await self._redis.get(redis_key)
        return int(value) if value else 0

    async def increment_rate_limit(
        self,
        actor: str,
        window_seconds: int = 60,
    ) -> int:
        """Increment rate limit counter, returns new value."""
        redis_key = self._rate_limit_key(actor)
        pipe = self._redis.pipeline()
        pipe.incr(redis_key)
        pipe.expire(redis_key, window_seconds)
        results = await pipe.execute()
        return results[0]

    async def acquire_lock(
        self,
        resource: str,
        resource_id: str,
        lease_seconds: int = 30,
    ) -> bool:
        """
        Acquire a distributed lock for the given resource.

        Returns True if lock acquired, False if already held.
        """
        import uuid

        lock_key = self._key("lock", f"{resource}:{resource_id}")
        lock_value = str(uuid.uuid4())

        acquired = await self._redis.set(
            lock_key,
            lock_value,
            nx=True,
            ex=lease_seconds,
        )
        return acquired is not None

    async def release_lock(
        self,
        resource: str,
        resource_id: str,
        lock_value: str,
    ) -> bool:
        """
        Release a distributed lock.

        Only releases if the lock value matches (prevents releasing someone else's lock).
        """
        lock_key = self._key("lock", f"{resource}:{resource_id}")

        lua_script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        else
            return 0
        end
        """

        result = await self._redis.eval(lua_script, 1, lock_key, lock_value)
        return result == 1
