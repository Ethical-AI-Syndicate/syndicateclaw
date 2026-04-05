"""Postgres integration tests for IdempotencyStore.acquire (requires live DB + migrations)."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys

import pytest
from ulid import ULID

from syndicateclaw.inference.errors import IdempotencyConflictError
from syndicateclaw.inference.idempotency import IdempotencyStore


@pytest.mark.integration
@pytest.mark.skip(reason="xdist DB race with Alembic")
@pytest.mark.asyncio
async def test_concurrent_acquire_single_winner(inference_session_factory) -> None:
    store = IdempotencyStore(inference_session_factory, stale_after_seconds=3600.0)
    key = f"idem-{ULID()}"
    h = "a" * 64
    inf = str(ULID())

    async def one() -> bool:
        _row, is_new = await store.acquire(
            idempotency_key=key,
            request_hash=h,
            inference_id=inf,
            system_config_version="v1",
            trace_id="t1",
        )
        return is_new

    results = await asyncio.gather(*[one() for _ in range(20)])
    assert sum(1 for x in results if x) == 1
    assert sum(1 for x in results if not x) == 19


@pytest.mark.integration
@pytest.mark.skip(reason="xdist DB race with Alembic")
@pytest.mark.asyncio
async def test_idempotency_hash_conflict(inference_session_factory) -> None:
    store = IdempotencyStore(inference_session_factory, stale_after_seconds=3600.0)
    key = f"idem-{ULID()}"
    h1 = "b" * 64
    h2 = "c" * 64
    inf = str(ULID())

    await store.acquire(
        idempotency_key=key,
        request_hash=h1,
        inference_id=inf,
        system_config_version="v1",
        trace_id="t1",
    )
    with pytest.raises(IdempotencyConflictError):
        await store.acquire(
            idempotency_key=key,
            request_hash=h2,
            inference_id=inf,
            system_config_version="v1",
            trace_id="t1",
        )


@pytest.mark.integration
@pytest.mark.skip(reason="xdist DB race with Alembic")
@pytest.mark.asyncio
async def test_stale_in_progress_marked_failed(inference_session_factory) -> None:
    """After stale_after, PENDING row is failed so evidence is terminal for that key."""
    store = IdempotencyStore(inference_session_factory, stale_after_seconds=0.01)
    key = f"idem-{ULID()}"
    h = "d" * 64
    inf = str(ULID())

    row1, is_new = await store.acquire(
        idempotency_key=key,
        request_hash=h,
        inference_id=inf,
        system_config_version="v1",
        trace_id="t1",
    )
    assert is_new is True
    assert row1.status == "pending"

    await asyncio.sleep(0.05)

    row2, is_new2 = await store.acquire(
        idempotency_key=key,
        request_hash=h,
        inference_id=inf,
        system_config_version="v1",
        trace_id="t1",
    )
    assert is_new2 is False
    assert row2.status == "failed"
    assert row2.failure_reason == "stale_in_progress"


def test_migration_upgrade_downgrade_script_exists() -> None:
    """Ensure migration file is present (upgrade/downgrade verified manually or in CI with DB)."""
    # Fix for mutmut testing: if running from mutants/, look at the real root
    if "mutants" in __file__:
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
    else:
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    mig = os.path.join(root, "migrations", "versions", "005_inference_tables.py")
    assert os.path.isfile(mig)


@pytest.mark.integration
@pytest.mark.skip(reason="xdist DB race with Alembic")
def test_alembic_downgrade_004_shadow_upgrade_head_roundtrip() -> None:
    """Exercise explicit downgrade() in 005_inference_tables and upgrade back to head."""
    url = os.environ.get("SYNDICATECLAW_TEST_DATABASE_URL")
    if not url:
        pytest.skip(
            "Set SYNDICATECLAW_TEST_DATABASE_URL to run Alembic round-trip integration test",
        )
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    env = os.environ.copy()
    env["SYNDICATECLAW_DATABASE_URL"] = url

    def run_alembic(*args: str) -> None:
        try:
            subprocess.run(
                [sys.executable, "-m", "alembic", *args],
                cwd=root,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            print("Alembic error! stderr:", e.stderr)
            print("Alembic stdout:", e.stdout)
            raise

    run_alembic("upgrade", "head")
    run_alembic("downgrade", "004_shadow")
    run_alembic("upgrade", "head")
