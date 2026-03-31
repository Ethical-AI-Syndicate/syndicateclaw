from __future__ import annotations

import asyncio
import contextlib
import os
from typing import Any

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from ulid import ULID

from syndicateclaw.db.models import (
    WorkflowDefinition,
    WorkflowRun,
    WorkflowVersion,
    WorkflowVersionArchive,
)
from syndicateclaw.services.versioning_service import VersioningService


@pytest.fixture()
async def engine() -> AsyncEngine:
    url = os.environ.get(
        "SYNDICATECLAW_DATABASE_URL",
        "postgresql+asyncpg://syndicateclaw:syndicateclaw@127.0.0.1:5432/syndicateclaw_test",
    )
    db_engine = None
    try:
        db_engine = create_async_engine(url)
        async with db_engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        if db_engine is not None:
            with contextlib.suppress(Exception):
                await db_engine.dispose()
        pytest.skip(f"Database unavailable: {exc}")
    try:
        yield db_engine
    finally:
        await db_engine.dispose()


@pytest.fixture()
async def versioning_service(engine: AsyncEngine) -> VersioningService:
    sf = async_sessionmaker(engine, expire_on_commit=False)
    async with sf() as session, session.begin():
        await session.execute(delete(WorkflowVersionArchive))
        await session.execute(delete(WorkflowVersion))
        await session.execute(delete(WorkflowRun))
        await session.execute(delete(WorkflowDefinition))
    return VersioningService(sf)


async def _workflow_id(service: VersioningService) -> str:
    sf = service._session_factory  # noqa: SLF001
    async with sf() as session, session.begin():
        wf = WorkflowDefinition(
            name=f"wf-{ULID()}",
            version="1",
            current_version=1,
            nodes=[],
            edges=[],
            metadata_={},
            namespace="default",
        )
        session.add(wf)
        await session.flush()
        return wf.id


@pytest.mark.asyncio
async def test_workflow_update_creates_version_row(versioning_service: VersioningService) -> None:
    workflow_id = await _workflow_id(versioning_service)
    version = await versioning_service.create_version(
        workflow_id,
        {"nodes": [{"id": "n1"}], "edges": [], "metadata": {}},
        "actor-a",
        "update",
    )
    assert version == 2


@pytest.mark.asyncio
async def test_concurrent_update_atomic(versioning_service: VersioningService) -> None:
    workflow_id = await _workflow_id(versioning_service)

    async def _create(i: int) -> int:
        return await versioning_service.create_version(
            workflow_id,
            {"nodes": [{"id": f"n{i}"}], "edges": [], "metadata": {}},
            f"actor-{i}",
            f"comment-{i}",
        )

    v1, v2 = await asyncio.gather(_create(1), _create(2))
    assert {v1, v2} == {2, 3}


@pytest.mark.asyncio
async def test_version_pinning_on_run(versioning_service: VersioningService) -> None:
    workflow_id = await _workflow_id(versioning_service)
    await versioning_service.create_version(
        workflow_id,
        {"nodes": [{"id": "n2"}], "edges": [], "metadata": {}},
        "actor",
        None,
    )
    sf = versioning_service._session_factory  # noqa: SLF001
    async with sf() as session, session.begin():
        run = WorkflowRun(
            workflow_id=workflow_id,
            workflow_version="2",
            status="PENDING",
            state={},
            namespace="default",
        )
        session.add(run)
        await session.flush()
        assert run.workflow_version == "2"


@pytest.mark.asyncio
async def test_rollback_creates_new_version(versioning_service: VersioningService) -> None:
    workflow_id = await _workflow_id(versioning_service)
    await versioning_service.create_version(
        workflow_id,
        {"nodes": [{"id": "n2"}], "edges": [], "metadata": {}},
        "actor",
        None,
    )
    created = await versioning_service.rollback(workflow_id, 2, "actor", "rollback")
    assert created == 3


@pytest.mark.asyncio
async def test_pinned_run_unaffected_by_rollback(versioning_service: VersioningService) -> None:
    workflow_id = await _workflow_id(versioning_service)
    await versioning_service.create_version(
        workflow_id,
        {"nodes": [{"id": "n2"}], "edges": [], "metadata": {}},
        "actor",
        None,
    )
    sf = versioning_service._session_factory  # noqa: SLF001
    async with sf() as session, session.begin():
        run = WorkflowRun(
            workflow_id=workflow_id,
            workflow_version="2",
            status="RUNNING",
            state={},
            namespace="default",
        )
        session.add(run)
        await session.flush()
        run_id = run.id

    await versioning_service.rollback(workflow_id, 2, "actor", None)

    async with sf() as session:
        refreshed = await session.get(WorkflowRun, run_id)
        assert refreshed is not None
        assert refreshed.workflow_version == "2"


@pytest.mark.asyncio
async def test_version_cap_archives_oldest(versioning_service: VersioningService) -> None:
    workflow_id = await _workflow_id(versioning_service)
    for i in range(101):
        await versioning_service.create_version(
            workflow_id,
            {"nodes": [{"id": f"n{i}"}], "edges": [], "metadata": {}},
            "actor",
            None,
        )

    sf = versioning_service._session_factory  # noqa: SLF001
    async with sf() as session:
        active = await session.execute(
            select(WorkflowVersion).where(WorkflowVersion.workflow_id == workflow_id)
        )
        archived = await session.execute(
            select(WorkflowVersionArchive).where(WorkflowVersionArchive.workflow_id == workflow_id)
        )
        assert len(list(active.scalars().all())) <= 100
        assert len(list(archived.scalars().all())) >= 1


@pytest.mark.asyncio
async def test_version_diff(versioning_service: VersioningService) -> None:
    workflow_id = await _workflow_id(versioning_service)
    await versioning_service.create_version(
        workflow_id,
        {"nodes": [{"id": "a"}], "edges": [], "metadata": {"x": 1}},
        "actor",
        None,
    )
    await versioning_service.create_version(
        workflow_id,
        {"nodes": [{"id": "a"}, {"id": "b"}], "edges": [], "metadata": {"x": 2}},
        "actor",
        None,
    )

    diff: dict[str, Any] = await versioning_service.diff(workflow_id, 2, 3)
    assert diff["from_version"] == 2
    assert diff["to_version"] == 3
    assert "b" in diff["nodes_added"]
