"""Chaos scenarios — expand with Docker/network hooks in staging."""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.chaos]


@pytest.mark.skip(reason="Requires controlled Postgres stop — staging/ops")
@pytest.mark.asyncio
async def test_chaos_postgres_down_degrades_readyz() -> None:
    assert False


@pytest.mark.skip(reason="Requires Redis kill + concurrent traffic assertions")
@pytest.mark.asyncio
async def test_chaos_redis_down_graceful() -> None:
    assert False


@pytest.mark.skip(reason="Full DLQ + disk-full matrix — platform validation")
@pytest.mark.asyncio
async def test_chaos_dlq_disk_full() -> None:
    assert False
