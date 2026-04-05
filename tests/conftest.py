from __future__ import annotations

import os
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


@pytest.fixture()
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


@pytest.fixture()
def sample_workflow_run(sample_workflow_definition: WorkflowDefinition) -> WorkflowRun:
    return WorkflowRun.new(
        workflow_id=sample_workflow_definition.id,
        workflow_version=sample_workflow_definition.version,
        initiated_by="test-actor",
    )


@pytest.fixture()
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


@pytest.fixture()
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


@pytest.fixture()
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


@pytest.fixture()
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


@pytest.fixture()
async def db_engine(worker_id: str) -> typing.AsyncGenerator[AsyncEngine, None]:
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
                        await conn.run_sync(Base.metadata.create_all)

                    from alembic import command
                    from alembic.config import Config

                    alembic_cfg = Config("alembic.ini")
                    alembic_cfg.set_main_option("sqlalchemy.url", database_url)

                    def stamp_head(cfg: Config = alembic_cfg) -> None:
                        command.stamp(cfg, "head")

                    await asyncio.to_thread(stamp_head)
                else:
                    # Wait for master worker to create tables. We poll for "principals" table.
                    from sqlalchemy import text

                    for _ in range(60):
                        try:
                            # Wait until both alembic_version AND principals exist and are queried.
                            async with engine.begin() as conn:
                                await conn.execute(text("SELECT 1 FROM principals LIMIT 1"))
                                await conn.execute(text("SELECT 1 FROM alembic_version LIMIT 1"))
                            break
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
        await engine.dispose()


@pytest.fixture()
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


@pytest.fixture()
def policy_engine(db_engine: AsyncEngine) -> PolicyEngine:
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    return PolicyEngine(session_factory)


@pytest.fixture()
def audit_service(db_engine: AsyncEngine) -> AuditService:
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    return AuditService(session_factory)


@pytest.fixture()
def approval_service(db_engine: AsyncEngine) -> ApprovalService:
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    return ApprovalService(session_factory, notification_callback=None)


@pytest.fixture()
def test_actor() -> str:
    return "test-actor-operator"


@pytest.fixture()
def admin_actor() -> str:
    return "test-actor-admin"


@pytest.fixture()
def rbac_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYNDICATECLAW_RBAC_ENFORCEMENT_ENABLED", "false")
