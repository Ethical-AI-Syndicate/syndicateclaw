"""Inference tests: set SYNDICATECLAW_TEST_DATABASE_URL for Postgres-backed integration tests."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.fixture
async def inference_session_factory(db_engine: Any) -> Any:
    # REUSE the global db_engine fixture from the root conftest!
    # This guarantees the tables exist, the schema is created exactly once per node/worker,
    # and connection retry logic is consolidated.
    factory = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
    yield factory
