"""Integration coverage for syndicateclaw.memory — policies, cache, guardrails, retention."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from ulid import ULID

from syndicateclaw.memory.schema import (
    NamespaceSchema,
    NamespaceSchemaRegistry,
    SchemaValidationError,
)
from syndicateclaw.memory.service import MemoryService
from syndicateclaw.models import MemoryRecord, MemoryType

pytestmark = pytest.mark.integration


@pytest.fixture
async def redis_async() -> Any:
    """Real Redis for cache tests; skip if unavailable."""
    try:
        import redis.asyncio as redis
    except ImportError:
        pytest.skip("redis asyncio not installed")

    url = os.environ.get("SYNDICATECLAW_REDIS_URL", "redis://localhost:6379/0")
    client = redis.from_url(url, decode_responses=False)
    try:
        await client.ping()
    except Exception as exc:
        await client.aclose()
        pytest.skip(f"Redis unavailable: {exc}")
    yield client
    try:
        await client.aclose()
    except RuntimeError as exc:
        if "Event loop is closed" not in str(exc):
            raise


class _FailingRedis:
    """Simulates Redis errors — read path degrades to Postgres."""

    async def get(self, *_a: Any, **_k: Any) -> None:
        raise OSError("redis unavailable")

    async def setex(self, *_a: Any, **_k: Any) -> None:
        raise OSError("redis unavailable")

    async def delete(self, *_a: Any, **_k: Any) -> None:
        raise OSError("redis unavailable")


def _mk(
    *,
    namespace: str,
    key: str,
    actor: str,
    access_policy: str = "default",
    value: Any | None = None,
) -> MemoryRecord:
    return MemoryRecord.new(
        namespace=namespace,
        key=key,
        value=value if value is not None else {"data": 1},
        memory_type=MemoryType.SEMANTIC,
        source="coverage-test",
        actor=actor,
        access_policy=access_policy,
    )


@pytest.mark.asyncio
async def test_memory_read_owner_only_policy_allows_owner(session_factory) -> None:
    ns = f"cov_ns_{ULID()}"
    svc = MemoryService(session_factory)
    rec = _mk(namespace=ns, key=f"k_{ULID()}", actor="owner-a", access_policy="owner_only")
    persisted = await svc.write(rec, actor="owner-a")
    got = await svc.read(ns, rec.key, actor="owner-a")
    assert got is not None
    assert got.id == persisted.id


@pytest.mark.asyncio
async def test_memory_read_owner_only_policy_blocks_non_owner(session_factory) -> None:
    ns = f"cov_ns_{ULID()}"
    svc = MemoryService(session_factory)
    rec = _mk(namespace=ns, key=f"k_{ULID()}", actor="owner-a", access_policy="owner_only")
    await svc.write(rec, actor="owner-a")
    assert await svc.read(ns, rec.key, actor="intruder-b") is None


@pytest.mark.asyncio
async def test_memory_read_system_only_policy_allows_system_actor(session_factory) -> None:
    ns = f"cov_ns_{ULID()}"
    svc = MemoryService(session_factory)
    rec = _mk(namespace=ns, key=f"k_{ULID()}", actor="sys", access_policy="system_only")
    await svc.write(rec, actor="sys")
    got = await svc.read(ns, rec.key, actor="system:pipeline")
    assert got is not None


@pytest.mark.asyncio
async def test_memory_read_system_only_policy_blocks_regular_actor(session_factory) -> None:
    ns = f"cov_ns_{ULID()}"
    svc = MemoryService(session_factory)
    rec = _mk(namespace=ns, key=f"k_{ULID()}", actor="sys", access_policy="system_only")
    await svc.write(rec, actor="sys")
    assert await svc.read(ns, rec.key, actor="user:alice") is None


@pytest.mark.asyncio
async def test_memory_read_restricted_policy_allows_owner(session_factory) -> None:
    ns = f"cov_ns_{ULID()}"
    svc = MemoryService(session_factory)
    rec = _mk(namespace=ns, key=f"k_{ULID()}", actor="alice", access_policy="restricted")
    await svc.write(rec, actor="alice")
    got = await svc.read(ns, rec.key, actor="alice")
    assert got is not None


@pytest.mark.asyncio
async def test_memory_read_restricted_policy_blocks_others(session_factory) -> None:
    ns = f"cov_ns_{ULID()}"
    svc = MemoryService(session_factory)
    rec = _mk(namespace=ns, key=f"k_{ULID()}", actor="alice", access_policy="restricted")
    await svc.write(rec, actor="alice")
    assert await svc.read(ns, rec.key, actor="bob") is None


@pytest.mark.asyncio
async def test_memory_read_unknown_policy_fails_closed(session_factory) -> None:
    ns = f"cov_ns_{ULID()}"
    svc = MemoryService(session_factory)
    rec = _mk(
        namespace=ns,
        key=f"k_{ULID()}",
        actor="alice",
        access_policy="totally_unknown_policy",
    )
    await svc.write(rec, actor="alice")
    assert await svc.read(ns, rec.key, actor="alice") is None


@pytest.mark.asyncio
async def test_memory_cache_hit_still_checks_access_policy(
    session_factory, redis_async: Any
) -> None:
    ns = f"cov_ns_{ULID()}"
    key = f"k_{ULID()}"
    svc = MemoryService(session_factory, redis_client=redis_async)
    rec = _mk(namespace=ns, key=key, actor="owner-z", access_policy="owner_only")
    persisted = await svc.write(rec, actor="owner-z")
    cached = MemoryRecord.model_validate_json(persisted.model_dump_json())
    await redis_async.set(
        svc._cache_key(ns, key),
        cached.model_dump_json(),
        ex=300,
    )
    assert await svc.read(ns, key, actor="wrong-actor") is None


@pytest.mark.asyncio
async def test_memory_owner_only_record_not_cached(session_factory, redis_async: Any) -> None:
    ns = f"cov_ns_{ULID()}"
    key = f"k_{ULID()}"
    svc = MemoryService(session_factory, redis_client=redis_async)
    rec = _mk(namespace=ns, key=key, actor="owner", access_policy="owner_only")
    await svc.write(rec, actor="owner")
    assert await redis_async.get(svc._cache_key(ns, key)) is None


@pytest.mark.asyncio
async def test_memory_read_succeeds_when_redis_unavailable(session_factory) -> None:
    ns = f"cov_ns_{ULID()}"
    key = f"k_{ULID()}"
    svc = MemoryService(session_factory, redis_client=_FailingRedis())
    rec = _mk(namespace=ns, key=key, actor="u1", access_policy="default")
    await svc.write(rec, actor="u1")
    got = await svc.read(ns, key, actor="u1")
    assert got is not None
    assert got.key == key


@pytest.mark.asyncio
async def test_memory_write_rejects_oversized_value(session_factory) -> None:
    svc = MemoryService(session_factory, max_value_bytes=50)
    big = {"x": "y" * 200}
    rec = _mk(
        namespace=f"ns_{ULID()}",
        key=f"k_{ULID()}",
        actor="a",
        value=big,
    )
    with pytest.raises(ValueError, match="too large"):
        await svc.write(rec, actor="a")


@pytest.mark.asyncio
async def test_memory_write_rejects_key_too_long(session_factory) -> None:
    svc = MemoryService(session_factory, max_key_length=5)
    rec = _mk(
        namespace=f"n_{ULID()}",
        key="123456",
        actor="a",
    )
    with pytest.raises(ValueError, match="Key too long"):
        await svc.write(rec, actor="a")


@pytest.mark.asyncio
async def test_memory_write_rejects_namespace_too_long(session_factory) -> None:
    svc = MemoryService(session_factory, max_namespace_length=4)
    rec = _mk(namespace="abcde", key="k", actor="a")
    with pytest.raises(ValueError, match="Namespace too long"):
        await svc.write(rec, actor="a")


@pytest.mark.asyncio
async def test_memory_write_rejects_excessive_nesting_depth(session_factory) -> None:
    svc = MemoryService(session_factory, max_nesting_depth=3)
    deep: dict[str, Any] = {"a": {"b": {"c": {"d": 1}}}}
    rec = _mk(namespace=f"ns_{ULID()}", key=f"k_{ULID()}", actor="a", value=deep)
    with pytest.raises(ValueError, match="nesting"):
        await svc.write(rec, actor="a")


@pytest.mark.asyncio
async def test_memory_soft_delete_marks_for_deletion(session_factory) -> None:
    svc = MemoryService(session_factory)
    rec = _mk(namespace=f"ns_{ULID()}", key=f"k_{ULID()}", actor="a")
    persisted = await svc.write(rec, actor="a")
    await svc.delete(persisted.id, actor="a", hard=False)
    assert await svc.read(persisted.namespace, persisted.key, actor="a") is None


@pytest.mark.asyncio
async def test_memory_soft_deleted_record_excluded_from_read(session_factory) -> None:
    svc = MemoryService(session_factory)
    rec = _mk(namespace=f"ns_{ULID()}", key=f"k_{ULID()}", actor="a")
    persisted = await svc.write(rec, actor="a")
    await svc.delete(persisted.id, actor="a", hard=False)
    assert await svc.read(persisted.namespace, persisted.key, actor="a") is None


@pytest.mark.asyncio
async def test_memory_soft_deleted_record_excluded_from_search(session_factory) -> None:
    svc = MemoryService(session_factory)
    ns = f"ns_{ULID()}"
    rec = _mk(namespace=ns, key=f"k_{ULID()}", actor="a")
    persisted = await svc.write(rec, actor="a")
    await svc.delete(persisted.id, actor="a", hard=False)
    found = await svc.search(ns, {}, actor="a")
    assert all(r.id != persisted.id for r in found)


@pytest.mark.asyncio
async def test_memory_search_scoped_to_namespace(session_factory) -> None:
    svc = MemoryService(session_factory)
    ns1 = f"ns1_{ULID()}"
    ns2 = f"ns2_{ULID()}"
    r1 = _mk(namespace=ns1, key=f"k_{ULID()}", actor="a")
    r2 = _mk(namespace=ns2, key=f"k_{ULID()}", actor="a")
    await svc.write(r1, actor="a")
    await svc.write(r2, actor="a")
    res = await svc.search(ns1, {}, actor="a")
    keys = {x.key for x in res}
    assert r1.key in keys
    assert r2.key not in keys


@pytest.mark.asyncio
async def test_memory_cross_namespace_read_blocked(session_factory) -> None:
    svc = MemoryService(session_factory)
    ns = f"ns_{ULID()}"
    rec = _mk(namespace=ns, key=f"k_{ULID()}", actor="a")
    await svc.write(rec, actor="a")
    assert await svc.read(f"other_{ns}", rec.key, actor="a") is None


@pytest.mark.asyncio
async def test_memory_write_creates_lineage_record(session_factory) -> None:
    svc = MemoryService(session_factory)
    rec = _mk(namespace=f"ns_{ULID()}", key=f"k_{ULID()}", actor="a")
    persisted = await svc.write(rec, actor="a")
    assert persisted.lineage.parent_ids == []


@pytest.mark.asyncio
async def test_memory_update_appends_parent_id_to_lineage(session_factory) -> None:
    svc = MemoryService(session_factory)
    rec = _mk(namespace=f"ns_{ULID()}", key=f"k_{ULID()}", actor="a")
    persisted = await svc.write(rec, actor="a")
    updated = await svc.update(persisted.id, {"value": {"x": 2}}, actor="a")
    assert persisted.id in updated.lineage.parent_ids


@pytest.mark.asyncio
async def test_memory_lineage_traversal_endpoint(session_factory) -> None:
    svc = MemoryService(session_factory)
    first = _mk(namespace=f"ns_{ULID()}", key=f"k_{ULID()}", actor="a")
    p1 = await svc.write(first, actor="a")
    p2 = await svc.update(p1.id, {"value": {"step": 2}}, actor="a")
    chain = await svc.get_lineage(p2.id)
    ids = {c.id for c in chain}
    assert p2.id in ids
    assert p1.id in ids


@pytest.mark.asyncio
async def test_memory_write_passes_namespace_schema_validation(session_factory) -> None:
    reg = NamespaceSchemaRegistry()
    ns_pat = f"typed_{ULID()}"
    reg.register(ns_pat, NamespaceSchema(required_fields={"a"}, field_types={"a": "int"}))
    svc = MemoryService(session_factory, schema_registry=reg)
    rec = _mk(namespace=ns_pat, key=f"k_{ULID()}", actor="a", value={"a": 1})
    out = await svc.write(rec, actor="a")
    assert out.value == {"a": 1}


@pytest.mark.asyncio
async def test_memory_write_fails_namespace_schema_validation(session_factory) -> None:
    reg = NamespaceSchemaRegistry()
    ns_pat = f"typed_{ULID()}"
    reg.register(ns_pat, NamespaceSchema(required_fields={"a"}, field_types={"a": "int"}))
    svc = MemoryService(session_factory, schema_registry=reg)
    rec = _mk(namespace=ns_pat, key=f"k_{ULID()}", actor="a", value={"wrong": True})
    with pytest.raises(SchemaValidationError):
        await svc.write(rec, actor="a")


@pytest.mark.asyncio
async def test_memory_write_no_schema_registered_is_noop(session_factory) -> None:
    svc = MemoryService(session_factory, schema_registry=NamespaceSchemaRegistry())
    rec = _mk(namespace=f"untyped_{ULID()}", key=f"k_{ULID()}", actor="a", value={"any": True})
    out = await svc.write(rec, actor="a")
    assert out.value == {"any": True}


@pytest.mark.asyncio
async def test_retention_enforcer_purges_expired_records(session_factory) -> None:
    svc = MemoryService(session_factory)
    rec = MemoryRecord.new(
        namespace=f"ns_{ULID()}",
        key=f"k_{ULID()}",
        value={"x": 1},
        memory_type=MemoryType.SEMANTIC,
        source="t",
        actor="a",
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    persisted = await svc.write(rec, actor="a")
    n = await svc.enforce_retention()
    assert n >= 1
    assert await svc.read(persisted.namespace, persisted.key, actor="a") is None


@pytest.mark.asyncio
async def test_retention_enforcer_purges_soft_deleted_records(session_factory) -> None:
    svc = MemoryService(session_factory)
    rec = _mk(namespace=f"ns_{ULID()}", key=f"k_{ULID()}", actor="a")
    persisted = await svc.write(rec, actor="a")
    await svc.delete(persisted.id, actor="a", hard=False)
    n = await svc.enforce_retention()
    assert n >= 1
