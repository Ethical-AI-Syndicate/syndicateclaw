from __future__ import annotations

import ast
import uuid
from pathlib import Path

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from syndicateclaw.db.models import (
    NodeExecution,
    WorkflowDefinition,
    WorkflowRun,
)
from syndicateclaw.orchestrator.engine import WorkflowEngine

MODELS_PATH = Path("src/syndicateclaw/db/models.py")
GUARDED_RELATIONSHIPS = {
    ("WorkflowDefinition", "runs"),
    ("WorkflowRun", "node_executions"),
}
BANNED_LAZY_VALUES = {"selectin", "joined"}


def _relationship_call(stmt: ast.stmt) -> tuple[str, ast.Call] | None:
    target: ast.expr | None
    value: ast.expr | None
    if isinstance(stmt, ast.AnnAssign):
        target = stmt.target
        value = stmt.value
    elif isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
        target = stmt.targets[0]
        value = stmt.value
    else:
        return None

    if not isinstance(target, ast.Name) or not isinstance(value, ast.Call):
        return None
    if isinstance(value.func, ast.Name) and value.func.id == "relationship":
        return target.id, value
    return None


def _lazy_value(call: ast.Call) -> str | None:
    for keyword in call.keywords:
        if keyword.arg == "lazy" and isinstance(keyword.value, ast.Constant):
            value = keyword.value.value
            return value if isinstance(value, str) else None
    return None


def test_guarded_workflow_relationships_do_not_use_unbounded_eager_loading() -> None:
    tree = ast.parse(MODELS_PATH.read_text())
    seen: dict[tuple[str, str], str | None] = {}

    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for stmt in node.body:
            relationship_call = _relationship_call(stmt)
            if relationship_call is None:
                continue
            attr_name, call = relationship_call
            key = (node.name, attr_name)
            if key in GUARDED_RELATIONSHIPS:
                seen[key] = _lazy_value(call)

    assert set(seen) == GUARDED_RELATIONSHIPS
    for key, lazy in seen.items():
        assert lazy == "raise", f"{key[0]}.{key[1]} must use lazy='raise'"
        assert lazy not in BANNED_LAZY_VALUES


def test_workflow_engine_max_steps_control_ceiling_still_constructs() -> None:
    engine = WorkflowEngine({}, max_steps=1000)
    assert isinstance(engine, WorkflowEngine)


async def test_unloaded_workflow_definition_runs_raises_invalid_request(
    db_engine: AsyncEngine,
) -> None:
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    suffix = uuid.uuid4().hex
    workflow_id = f"orm-raise-wf-{suffix}"
    run_id = f"orm-raise-run-{suffix}"

    await _seed_workflow_run(session_factory, workflow_id, run_id)

    try:
        async with session_factory() as session:
            result = await session.execute(
                select(WorkflowDefinition).where(WorkflowDefinition.id == workflow_id).limit(1)
            )
            workflow = result.scalar_one()

            with pytest.raises(InvalidRequestError):
                _ = workflow.runs

            explicit_result = await session.execute(
                select(WorkflowDefinition)
                .options(selectinload(WorkflowDefinition.runs))
                .where(WorkflowDefinition.id == workflow_id)
                .limit(1)
            )
            explicitly_loaded = explicit_result.scalar_one()
            assert [run.id for run in explicitly_loaded.runs] == [run_id]
    finally:
        await _delete_workflow(session_factory, workflow_id)


async def test_unloaded_workflow_run_node_executions_raises_invalid_request(
    db_engine: AsyncEngine,
) -> None:
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    suffix = uuid.uuid4().hex
    workflow_id = f"orm-raise-wf-{suffix}"
    run_id = f"orm-raise-run-{suffix}"
    node_execution_id = f"orm-raise-node-{suffix}"

    await _seed_workflow_run(session_factory, workflow_id, run_id, node_execution_id)

    try:
        async with session_factory() as session:
            result = await session.execute(
                select(WorkflowRun).where(WorkflowRun.id == run_id).limit(1)
            )
            run = result.scalar_one()

            with pytest.raises(InvalidRequestError):
                _ = run.node_executions

            explicit_result = await session.execute(
                select(WorkflowRun)
                .options(selectinload(WorkflowRun.node_executions))
                .where(WorkflowRun.id == run_id)
                .limit(1)
            )
            explicitly_loaded = explicit_result.scalar_one()
            assert [node.id for node in explicitly_loaded.node_executions] == [node_execution_id]
    finally:
        await _delete_workflow(session_factory, workflow_id)


async def _seed_workflow_run(
    session_factory: async_sessionmaker[AsyncSession],
    workflow_id: str,
    run_id: str,
    node_execution_id: str | None = None,
) -> None:
    async with session_factory() as session, session.begin():
        session.add(
            WorkflowDefinition(
                id=workflow_id,
                name=workflow_id,
                version="1.0.0",
                namespace="default",
                description="ORM relationship enforcement fixture",
                nodes=[],
                edges=[],
                owner="orm-test",
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
                initiated_by="orm-test",
                tags={},
                namespace="default",
                owning_scope_type="PLATFORM",
                owning_scope_id="platform",
            )
        )
        if node_execution_id is not None:
            session.add(
                NodeExecution(
                    id=node_execution_id,
                    run_id=run_id,
                    node_id="node-a",
                    node_name="Node A",
                    status="COMPLETED",
                    attempt=1,
                    input_state={},
                    output_state={},
                )
            )


async def _delete_workflow(
    session_factory: async_sessionmaker[AsyncSession],
    workflow_id: str,
) -> None:
    async with session_factory() as session, session.begin():
        await session.execute(
            delete(WorkflowDefinition).where(WorkflowDefinition.id == workflow_id)
        )
