"""Inference tests: set SYNDICATECLAW_TEST_DATABASE_URL for Postgres-backed integration tests.

Example (after `docker compose up -d postgres` and `alembic upgrade head`):

  export SYNDICATECLAW_TEST_DATABASE_URL=postgresql+asyncpg://syndicateclaw:syndicateclaw@127.0.0.1:5432/syndicateclaw
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def inference_session_factory() -> Any:
    url = os.environ.get("SYNDICATECLAW_TEST_DATABASE_URL")
    if not url:
        pytest.skip(
            "Set SYNDICATECLAW_TEST_DATABASE_URL to run inference integration tests",
        )
    engine = create_async_engine(url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        yield factory
    finally:
        await engine.dispose()
