"""Database validation helpers."""

from __future__ import annotations

import redis.asyncio as aioredis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from syndicateclaw.errors import ValidationError


class StoreValidationResult:
    """Result of store validation checks."""

    def __init__(
        self,
        database_ok: bool,
        redis_ok: bool,
        schema_ok: bool,
        errors: list[str],
    ) -> None:
        self.database_ok = database_ok
        self.redis_ok = redis_ok
        self.schema_ok = schema_ok
        self.errors = errors

    @property
    def is_healthy(self) -> bool:
        """Returns True if all checks passed."""
        return self.database_ok and self.redis_ok and self.schema_ok


async def ValidateStore(
    database_url: str,
    redis_url: str,
    check_schema: bool = True,
) -> StoreValidationResult:
    """
    Validate database and Redis connectivity.

    Checks:
    1. Database connectivity via SELECT 1
    2. Redis connectivity via PING
    3. Schema version matches expected (if check_schema=True)

    Args:
        database_url: PostgreSQL connection URL
        redis_url: Redis connection URL
        check_schema: Whether to check schema version

    Returns:
        StoreValidationResult with per-check status.
    """
    errors: list[str] = []
    database_ok = False
    redis_ok = False
    schema_ok = False

    # Check database
    try:
        engine = create_async_engine(database_url, echo=False)
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        database_ok = True
        await engine.dispose()
    except Exception as e:
        errors.append(f"Database error: {e}")

    # Check Redis
    try:
        redis = aioredis.from_url(redis_url, decode_responses=True)
        await redis.ping()
        await redis.aclose()
        redis_ok = True
    except Exception as e:
        errors.append(f"Redis error: {e}")

    # Check schema (via alembic)
    if database_ok and check_schema:
        try:
            from syndicateclaw.db.migrate import AlembicMigrationRunner

            runner = AlembicMigrationRunner(database_url)
            current = await runner.current()
            is_current, _ = await runner.check()
            schema_ok = is_current
            if not is_current:
                errors.append(f"Schema not at head: current={current}")
        except Exception as e:
            errors.append(f"Schema check error: {e}")

    return StoreValidationResult(
        database_ok=database_ok,
        redis_ok=redis_ok,
        schema_ok=schema_ok,
        errors=errors,
    )
