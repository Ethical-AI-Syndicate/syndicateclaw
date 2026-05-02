from __future__ import annotations

import time
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from syndicateclaw.db.models import NodeExecution, WorkflowDefinition, WorkflowRun

pytestmark = pytest.mark.integration

NODE_EXECUTION_COUNT = 10_000
MAX_LIST_SECONDS = 1.0
MAX_LIST_RESPONSE_BYTES = 10_000


async def test_workflow_list_endpoint_does_not_load_unbounded_node_executions(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    workflow_id = f"orm-list-wf-{uuid.uuid4().hex}"
    run_id = f"orm-list-run-{uuid.uuid4().hex}"

    await _clear_anonymous_workflows(session_factory)
    await _seed_workflow_with_node_executions(session_factory, workflow_id, run_id)

    try:
        warmup = await client.get("/api/v1/workflows/?limit=1")
        assert warmup.status_code == 200

        started = time.perf_counter()
        response = await client.get("/api/v1/workflows/?limit=1")
        elapsed = time.perf_counter() - started

        assert response.status_code == 200
        assert elapsed < MAX_LIST_SECONDS
        assert len(response.content) < MAX_LIST_RESPONSE_BYTES

        payload = response.json()
        assert isinstance(payload, list)
        assert len(payload) == 1
        assert payload[0]["id"] == workflow_id
        assert "runs" not in payload[0]
        assert "node_executions" not in payload[0]
    finally:
        await _delete_workflow(session_factory, workflow_id)


async def test_run_nodes_endpoint_explicitly_returns_node_executions(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    workflow_id = f"orm-detail-wf-{uuid.uuid4().hex}"
    run_id = f"orm-detail-run-{uuid.uuid4().hex}"

    await _seed_workflow_with_node_executions(session_factory, workflow_id, run_id)

    try:
        response = await client.get(f"/api/v1/workflows/runs/{run_id}/nodes")

        assert response.status_code == 200
        payload = response.json()
        assert isinstance(payload, list)
        assert len(payload) == NODE_EXECUTION_COUNT
        assert payload[0]["run_id"] == run_id
        assert payload[0]["node_id"] == "node-0"
    finally:
        await _delete_workflow(session_factory, workflow_id)


async def _clear_anonymous_workflows(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session, session.begin():
        await session.execute(
            delete(WorkflowDefinition).where(WorkflowDefinition.owner == "anonymous")
        )


async def _delete_workflow(
    session_factory: async_sessionmaker[AsyncSession],
    workflow_id: str,
) -> None:
    async with session_factory() as session, session.begin():
        await session.execute(
            delete(WorkflowDefinition).where(WorkflowDefinition.id == workflow_id)
        )


async def _seed_workflow_with_node_executions(
    session_factory: async_sessionmaker[AsyncSession],
    workflow_id: str,
    run_id: str,
) -> None:
    async with session_factory() as session, session.begin():
        session.add(
            WorkflowDefinition(
                id=workflow_id,
                name=workflow_id,
                version="1.0.0",
                namespace="default",
                description="ORM unbounded load fixture",
                nodes=[],
                edges=[],
                owner="anonymous",
                metadata_={},
                current_version=1,
                owning_scope_type="PLATFORM",
                owning_scope_id="platform",
            )
        )
        session.add(
            WorkflowRun(
                id=run_id,
                workflow_id=workflow_id,
                workflow_version="1",
                status="COMPLETED",
                state={},
                initiated_by="anonymous",
                tags={},
                namespace="default",
                owning_scope_type="PLATFORM",
                owning_scope_id="platform",
            )
        )

    rows = [
        {
            "id": f"{run_id}-node-{idx}",
            "run_id": run_id,
            "node_id": f"node-{idx}",
            "node_name": f"Node {idx}",
            "status": "COMPLETED",
            "attempt": 1,
            "input_state": {},
            "output_state": {"idx": idx},
        }
        for idx in range(NODE_EXECUTION_COUNT)
    ]
    async with session_factory() as session, session.begin():
        await session.execute(insert(NodeExecution), rows)

    async with session_factory() as session:
        count = (
            await session.execute(
                select(NodeExecution.id).where(NodeExecution.run_id == run_id).limit(1)
            )
        ).first()
        assert count is not None
