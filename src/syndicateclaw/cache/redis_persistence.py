"""Redis key structure and persistence helpers."""

from __future__ import annotations


class RedisKeyStructure:
    """
    Redis key structure for syndicateclaw.

    Format: syndicateclaw:{namespace}:{resource}:{id}

    Namespaces:
    - memory: syndicateclaw:memory:{namespace}:{key}
    - rate_limit: syndicateclaw:ratelimit:{actor}
    - session: syndicateclaw:session:{session_id}
    - lock: syndicateclaw:lock:{resource}:{id}
    """

    MEMORY_TEMPLATE = "syndicateclaw:memory:{namespace}:{key}"
    RATE_LIMIT_TEMPLATE = "syndicateclaw:ratelimit:{actor}"
    SESSION_TEMPLATE = "syndicateclaw:session:{session_id}"
    LOCK_TEMPLATE = "syndicateclaw:lock:{resource}:{id}"

    @classmethod
    def memory(cls, namespace: str, key: str) -> str:
        """Generate memory cache key."""
        return cls.MEMORY_TEMPLATE.format(namespace=namespace, key=key)

    @classmethod
    def rate_limit(cls, actor: str) -> str:
        """Generate rate limit key."""
        return cls.RATE_LIMIT_TEMPLATE.format(actor=actor)

    @classmethod
    def session(cls, session_id: str) -> str:
        """Generate session key."""
        return cls.SESSION_TEMPLATE.format(session_id=session_id)

    @classmethod
    def lock(cls, resource: str, resource_id: str) -> str:
        """Generate lock key."""
        return cls.LOCK_TEMPLATE.format(resource=resource, resource_id=resource_id)


class RedisPersistenceConfig:
    """Redis persistence configuration."""

    def __init__(
        self,
        ttl_seconds: int = 300,
        max_memory: str = "256mb",
        eviction_policy: str = "allkeys-lru",
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_memory = max_memory
        self.eviction_policy = eviction_policy

    def to_redis_config(self) -> dict[str, str]:
        """Convert to Redis CONFIG SET arguments."""
        return {
            "maxmemory": self.max_memory,
            "maxmemory-policy": self.eviction_policy,
        }


class TenantRedisNamespace:
    """
    Tenant-isolated Redis key namespace.

    For multi-tenant deployments, prefixes all keys with tenant ID.
    """

    def __init__(self, tenant_id: str) -> None:
        self._tenant_id = tenant_id

    def key(self, resource: str, resource_id: str) -> str:
        """Generate tenant-isolated key."""
        return f"syndicateclaw:tenant:{self._tenant_id}:{resource}:{resource_id}"

    def memory(self, namespace: str, key: str) -> str:
        """Generate tenant-isolated memory cache key."""
        return f"syndicateclaw:tenant:{self._tenant_id}:memory:{namespace}:{key}"

    def rate_limit(self, actor: str) -> str:
        """Generate tenant-isolated rate limit key."""
        return f"syndicateclaw:tenant:{self._tenant_id}:ratelimit:{actor}"

    def session(self, session_id: str) -> str:
        """Generate tenant-isolated session key."""
        return f"syndicateclaw:tenant:{self._tenant_id}:session:{session_id}"

    def lock(self, resource: str, resource_id: str) -> str:
        """Generate tenant-isolated lock key."""
        return f"syndicateclaw:tenant:{self._tenant_id}:lock:{resource}:{resource_id}"
