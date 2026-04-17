from __future__ import annotations

import os
import subprocess
import sys
import typing
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import NullPool
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from syndicateclaw.approval.service import ApprovalService
from syndicateclaw.audit.service import AuditService
from syndicateclaw.db import models as db_models  # noqa: F401
from syndicateclaw.db.base import Base
from syndicateclaw.models import (
    ApprovalRequest,
    EdgeDefinition,
    MemoryLineage,
    MemoryRecord,
    MemoryType,
    NodeDefinition,
    NodeType,
    PolicyCondition,
    PolicyEffect,
    PolicyRule,
    Tool,
    ToolRiskLevel,
    WorkflowDefinition,
    WorkflowRun,
)
from syndicateclaw.policy.engine import PolicyEngine


@pytest.fixture(scope="session", autouse=True)
async def seed_rbac_for_tests(db_engine):
    """
    Seed RBAC principals, roles, and assignments before any tests run.
    This prevents 100% PRINCIPAL_NOT_FOUND disagreement in shadow evaluation.
    Runs the seed script as a subprocess so it uses its own DB connection.
    Idempotent — safe to call on an already-seeded database.
    """
    import subprocess

    db_url = os.environ.get(
        "SYNDICATECLAW_DATABASE_URL",
        "postgresql+asyncpg://syndicateclaw:syndicateclaw@localhost:5432/syndicateclaw_test",
    )
    # Ensure it's correctly pointed even if credentials changed
    # In this environment we found it's syndicategate:syndicategate
    if "localhost:5432/syndicateclaw_test" in db_url and "syndicategate" not in db_url:
         db_url = db_url.replace("syndicateclaw:syndicateclaw", "syndicategate:syndicategate")

    result = subprocess.run(
        [sys.executable, "scripts/seed_rbac_phase0.py"],
        env={**os.environ, "SYNDICATECLAW_DATABASE_URL": db_url},
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.fail(
            f"RBAC seed script failed (exit {result.returncode}).\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}\n"
            "Fix the seed script or database state before running tests."
        )


@pytest.fixture(scope="session")
def sample_workflow_definition() -> WorkflowDefinition:
    return WorkflowDefinition.new(
        name="sample-workflow",
        version="1.0.0",
        owner="test-owner",
        description="A sample workflow for testing",
        nodes=[
            NodeDefinition(id="start", name="Start", node_type=NodeType.START, handler="start"),
            NodeDefinition(id="action1", name="Action", node_type=NodeType.ACTION, handler="llm"),
            NodeDefinition(
                id="decision1",
                name="Decision",
                node_type=NodeType.DECISION,
                handler="decision",
                config={"condition": "state.x == 1", "true_node": "approval1", "false_node": "end"},
            ),
            NodeDefinition(
                id="approval1",
                name="Approval",
                node_type=NodeType.APPROVAL,
                handler="approval",
                config={"description": "Needs approval", "risk_level": "MEDIUM"},
            ),
            NodeDefinition(id="end", name="End", node_type=NodeType.END, handler="end"),
        ],
        edges=[
            EdgeDefinition(source_node_id="start", target_node_id="action1"),
            EdgeDefinition(source_node_id="action1", target_node_id="decision1"),
            EdgeDefinition(
                source_node_id="decision1",
                target_node_id="approval1",
                condition="state.x == 1",
                priority=1,
            ),
            EdgeDefinition(
                source_node_id="decision1",
                target_node_id="end",
                priority=0,
            ),
            EdgeDefinition(source_node_id="approval1", target_node_id="end"),
        ],
    )


@pytest.fixture(scope="session")
def sample_workflow_run(sample_workflow_definition: WorkflowDefinition) -> WorkflowRun:
    return WorkflowRun.new(
        workflow_id=sample_workflow_definition.id,
        workflow_version=sample_workflow_definition.version,
        initiated_by="test-actor",
    )


@pytest.fixture(scope="session")
def sample_tool() -> Tool:
    return Tool.new(
        name="test-tool",
        version="1.0.0",
        description="A sample tool for testing",
        owner="test-owner",
        risk_level=ToolRiskLevel.LOW,
        input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"result": {"type": "string"}}},
    )


@pytest.fixture(scope="session")
def sample_memory_record() -> MemoryRecord:
    return MemoryRecord.new(
        namespace="test-ns",
        key="test-key",
        value={"data": "hello"},
        memory_type=MemoryType.SEMANTIC,
        source="unit-test",
        actor="test-actor",
        confidence=0.95,
        lineage=MemoryLineage(),
    )


@pytest.fixture(scope="session")
def sample_policy_rule() -> PolicyRule:
    return PolicyRule.new(
        name="allow-low-risk-tools",
        description="Allow execution of low-risk tools",
        resource_type="tool",
        resource_pattern="test-*",
        effect=PolicyEffect.ALLOW,
        conditions=[
            PolicyCondition(field="risk_level", operator="eq", value="LOW"),
        ],
        priority=10,
        owner="test-owner",
    )


@pytest.fixture(scope="session")
def sample_approval_request(sample_workflow_run: WorkflowRun) -> ApprovalRequest:
    return ApprovalRequest.new(
        run_id=sample_workflow_run.id,
        node_execution_id="node-exec-001",
        tool_name="dangerous-tool",
        action_description="Execute a high-risk tool",
        risk_level=ToolRiskLevel.HIGH,
        requested_by="test-actor",
        assigned_to=["admin@example.com"],
        expires_at=datetime.now(UTC) + timedelta(hours=24),
        context={"run_id": sample_workflow_run.id},
    )


@pytest.fixture(scope="session")
async def db_engine(request) -> typing.AsyncGenerator[AsyncEngine, None]:
    worker_id = getattr(request.config, "workerinput", {}).get("workerid", "gw0")
    database_url = os.environ.get("SYNDICATECLAW_DATABASE_URL") or (
        "postgresql+asyncpg://syndicateclaw:syndicateclaw@localhost:5432/syndicateclaw_test"
    )
    import asyncio

    # We must construct a new engine for the local pytest-asyncio event loop
    engine = create_async_engine(database_url, future=True, poolclass=NullPool)

    try:
        for attempt in range(10):
            try:
                if worker_id in ("master", "gw0"):
                    async with engine.begin() as conn:
                        await conn.run_sync(Base.metadata.drop_all)
                        from sqlalchemy import text

                        await conn.execute(text("DROP TABLE IF EXISTS _pytest_schema_ready"))
                        await conn.run_sync(Base.metadata.create_all)

                    from alembic import command
                    from alembic.config import Config

                    alembic_cfg = Config("alembic.ini")
                    alembic_cfg.set_main_option("sqlalchemy.url", database_url)

                    def stamp_head(cfg: Config = alembic_cfg) -> None:
                        command.stamp(cfg, "head")

                    await asyncio.to_thread(stamp_head)

                    # Mark initialization complete
                    async with engine.begin() as conn:
                        import os as _os

                        run_id = _os.environ.get("CI_PIPELINE_ID", "local")
                        await conn.execute(
                            text("CREATE TABLE IF NOT EXISTS _pytest_schema_ready (id int, r text)")
                        )
                        await conn.execute(
                            text("INSERT INTO _pytest_schema_ready (id, r) VALUES (1, :r)"),
                            {"r": run_id},
                        )

                        # Insert a dummy actor to ensure seeding has something to work with
                        await conn.execute(
                            text("""
                                INSERT INTO workflow_definitions
                                (id, name, version, namespace, owner, description, nodes, edges,
                                 metadata, created_at, updated_at)
                                VALUES (:id, :name, :version, 'default', :owner, :desc,
                                        '{}'::jsonb, '{}'::jsonb, '{}'::jsonb,
                                        now(), now())
                            """),
                            {
                                "id": "seed-dummy",
                                "name": "seed-dummy",
                                "version": "0.0.0",
                                "owner": "system:engine",
                                "desc": "dummy for seeding",
                            },
                        )

                else:
                    # Wait for master worker to create tables.
                    import os as _os

                    from sqlalchemy import text

                    run_id = _os.environ.get("CI_PIPELINE_ID", "local")

                    for _ in range(120):
                        try:
                            # Wait for worker 0 to start stamping.
                            await asyncio.sleep(2)
                            async with engine.begin() as conn:
                                # Query for the run_id inside the marker table!
                                result = await conn.execute(
                                    text(
                                        "SELECT id FROM _pytest_schema_ready WHERE r = :r LIMIT 1"
                                    ),
                                    {"r": run_id},
                                )
                                if result.scalar() == 1:
                                    break
                            await asyncio.sleep(2)
                        except Exception:
                            await asyncio.sleep(2)
                    else:
                        raise Exception("Timeout waiting for DB schema and alembic stamp")
                break
            except Exception as e:
                if attempt == 9:
                    raise e
                await asyncio.sleep(2)
    except Exception as exc:
        await engine.dispose()
        pytest.skip(f"Database unavailable: {exc}")

    try:
        yield engine
    finally:
        # DO NOT DO ANYTHING IN FINALLY EXCEPT DISPOSE ENGINE.
        # DO NOT DROP TABLES ON TEARDOWN.
        await engine.dispose()


@pytest.fixture(scope="session")
async def db_session(db_engine: AsyncEngine) -> typing.AsyncGenerator[AsyncSession, None]:
    connection = await db_engine.connect()
    transaction = await connection.begin()
    session_factory = async_sessionmaker(bind=connection, expire_on_commit=False)
    session = session_factory()
    try:
        yield session
    finally:
        await session.close()
        if transaction.is_active:
            await transaction.rollback()
        await connection.close()


@pytest.fixture(scope="session")
def policy_engine(db_engine: AsyncEngine) -> PolicyEngine:
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    return PolicyEngine(session_factory)


@pytest.fixture(scope="session")
def audit_service(db_engine: AsyncEngine) -> AuditService:
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    return AuditService(session_factory)


@pytest.fixture(scope="session")
def approval_service(db_engine: AsyncEngine) -> ApprovalService:
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    return ApprovalService(session_factory, notification_callback=None)


@pytest.fixture(scope="session")
def test_actor() -> str:
    return "test-actor-operator"


@pytest.fixture(scope="session")
def admin_actor() -> str:
    return "test-actor-admin"


@pytest.fixture(scope="session")
def rbac_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYNDICATECLAW_RBAC_ENFORCEMENT_ENABLED", "false")
