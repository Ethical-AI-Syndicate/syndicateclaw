"""Bootstrap CLI commands."""

from __future__ import annotations

import asyncio
import os
import sys


async def integrity_check_command(database_url: str, redis_url: str) -> int:
    """
    CLI command to run integrity checks.

    Args:
        database_url: Database connection URL
        redis_url: Redis connection URL

    Returns:
        Exit code: 0 for success, 1 for failure, 2 for check error
    """
    from syndicateclaw.db.integrity import IntegrityCheck, IntegrityCheckResult
    from syndicateclaw.db.migrate import AlembicMigrationRunner
    from syndicateclaw.db.validate import StoreValidationResult, ValidateStore
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.ext.asyncio import async_sessionmaker

    print("Running integrity checks...")
    print(f"Database: {database_url[:50]}...")
    print(f"Redis: {redis_url[:50]}...")
    print()

    all_passed = True

    # Step 1: Validate stores
    print("[1/3] Validating stores...")
    try:
        store_result = await ValidateStore(database_url, redis_url)
        if store_result.is_healthy:
            print("  OK - Stores OK")
        else:
            print("  FAIL - Store validation failed:")
            for error in store_result.errors:
                print(f"    - {error}")
            all_passed = False
    except Exception as e:
        print(f"  ERROR - Store validation error: {e}")
        all_passed = False

    # Step 2: Check schema
    print("[2/3] Checking schema version...")
    try:
        runner = AlembicMigrationRunner(database_url)
        current = await runner.current()
        is_current, head = await runner.check()
        if is_current:
            print(f"  OK - Schema OK (head: {current})")
        else:
            print(f"  FAIL - Schema not at head: current={current}, head={head}")
            all_passed = False
    except Exception as e:
        print(f"  ERROR - Schema check error: {e}")
        all_passed = False

    # Step 3: Run integrity checks
    print("[3/3] Running integrity checks...")
    try:
        engine = create_async_engine(database_url, echo=False)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

        integrity_result = await IntegrityCheck(session_factory)
        if integrity_result.is_healthy:
            print("  OK - Integrity OK")
        else:
            print("  FAIL - Integrity check failed:")
            for error in integrity_result.errors:
                print(f"    - {error}")
            all_passed = False

        await engine.dispose()
    except Exception as e:
        print(f"  ERROR - Integrity check error: {e}")
        all_passed = False

    print()
    if all_passed:
        print("All checks passed")
        return 0
    else:
        print("Some checks failed")
        return 1


def main() -> int:
    """Entry point for integrity check command."""
    database_url = os.environ.get("SYNDICATECLAW_DATABASE_URL", "")
    redis_url = os.environ.get("SYNDICATECLAW_REDIS_URL", "redis://localhost:6379/0")

    if not database_url:
        print("Error: SYNDICATECLAW_DATABASE_URL not set")
        return 2

    exit_code = asyncio.run(integrity_check_command(database_url, redis_url))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
