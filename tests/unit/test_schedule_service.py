from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from syndicateclaw.config import Settings
from syndicateclaw.db.models import WorkflowDefinition, WorkflowSchedule
from syndicateclaw.services.schedule_service import (
    InvalidScheduleError,
    ScheduleNotFoundError,
    ScheduleService,
    _compute_next_run,
    validate_schedule_value,
)
from syndicateclaw.services.scheduler_service import SchedulerService


def _is_valid_ulid(value: str) -> bool:
    return len(value) == 26 and value.isalnum()


@pytest.fixture()
async def engine() -> AsyncEngine:
    url = os.environ.get(
        "SYNDICATECLAW_DATABASE_URL",
        "postgresql+asyncpg://syndicateclaw:syndicateclaw@127.0.0.1:5432/syndicateclaw_test",
    )
    db_engine = create_async_engine(url)
    try:
        yield db_engine
    finally:
        await db_engine.dispose()


@pytest.fixture()
async def session_factory(engine: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture()
async def schedule_service(session_factory: async_sessionmaker) -> ScheduleService:
    async with session_factory() as session, session.begin():
        await session.execute(delete(WorkflowSchedule))
    return ScheduleService(session_factory)


@pytest.fixture(autouse=True)
async def clean_scheduler_tables(session_factory: async_sessionmaker) -> None:
    async with session_factory() as session, session.begin():
        await session.execute(text("DELETE FROM workflow_runs"))
        await session.execute(delete(WorkflowSchedule))


@pytest.fixture()
def mock_settings() -> Settings:
    return MagicMock(  # type: ignore[return-value]
        scheduler_enabled=True,
        scheduler_poll_interval=10,
        scheduler_max_concurrent=50,
        scheduler_lock_lease_seconds=120,
        scheduler_batch_size=20,
    )


@pytest.mark.asyncio
async def test_validate_cron_valid(schedule_service: ScheduleService) -> None:
    next_run = validate_schedule_value("CRON", "0 9 * * MON-FRI")
    assert next_run > datetime.now(UTC)


@pytest.mark.asyncio
async def test_validate_cron_invalid(schedule_service: ScheduleService) -> None:
    with pytest.raises(InvalidScheduleError, match="Invalid CRON expression"):
        validate_schedule_value("CRON", "not a cron")


@pytest.mark.asyncio
async def test_validate_interval_valid(schedule_service: ScheduleService) -> None:
    next_run = validate_schedule_value("INTERVAL", "1h")
    assert next_run > datetime.now(UTC)


@pytest.mark.asyncio
async def test_validate_interval_too_short(
    schedule_service: ScheduleService,
) -> None:
    with pytest.raises(InvalidScheduleError, match="at least 60 seconds"):
        validate_schedule_value("INTERVAL", "30s")


@pytest.mark.asyncio
async def test_validate_interval_invalid(schedule_service: ScheduleService) -> None:
    with pytest.raises(InvalidScheduleError, match="Invalid INTERVAL value"):
        validate_schedule_value("INTERVAL", "foobar")


@pytest.mark.asyncio
async def test_validate_once_valid(schedule_service: ScheduleService) -> None:
    future = datetime.now(UTC) + timedelta(days=1)
    next_run = validate_schedule_value("ONCE", future.isoformat())
    assert next_run == future.replace(tzinfo=UTC)


@pytest.mark.asyncio
async def test_validate_once_past(schedule_service: ScheduleService) -> None:
    past = datetime.now(UTC) - timedelta(days=1)
    past_iso = past.isoformat()
    past_iso = past_iso.replace("+00:00", "Z")
    with pytest.raises(InvalidScheduleError, match="must be in the future"):
        validate_schedule_value("ONCE", past_iso)


@pytest.mark.asyncio
async def test_validate_once_invalid_format(
    schedule_service: ScheduleService,
) -> None:
    with pytest.raises(InvalidScheduleError, match="Invalid ONCE datetime"):
        validate_schedule_value("ONCE", "not a date")


@pytest.mark.asyncio
async def test_create_schedule(session_factory: async_sessionmaker) -> None:
    from ulid import ULID
    svc = ScheduleService(session_factory)
    schedule = await svc.create(
        ulid_factory=ULID,
        workflow_id="wf-001",
        workflow_version=1,
        name="daily-run",
        description="Run daily",
        schedule_type="CRON",
        schedule_value="0 9 * * *",
        input_state={"key": "value"},
        actor="admin",
        namespace="default",
        max_runs=10,
    )
    assert _is_valid_ulid(schedule.id)
    assert schedule.workflow_id == "wf-001"
    assert schedule.schedule_type == "CRON"
    assert schedule.status == "ACTIVE"
    assert schedule.run_count == 0


@pytest.mark.asyncio
async def test_create_schedule_interval(
    session_factory: async_sessionmaker,
) -> None:
    from ulid import ULID
    svc = ScheduleService(session_factory)
    schedule = await svc.create(
        ulid_factory=ULID,
        workflow_id="wf-002",
        workflow_version=None,
        name="hourly-check",
        description=None,
        schedule_type="INTERVAL",
        schedule_value="1h",
        input_state={},
        actor="system",
        namespace="monitoring",
        max_runs=None,
    )
    assert schedule.namespace == "monitoring"
    assert schedule.max_runs is None


@pytest.mark.asyncio
async def test_get_schedule(session_factory: async_sessionmaker) -> None:
    from ulid import ULID
    svc = ScheduleService(session_factory)
    schedule = await svc.create(
        ulid_factory=ULID,
        workflow_id="wf-003",
        workflow_version=1,
        name="get-test",
        description=None,
        schedule_type="ONCE",
        schedule_value=(datetime.now(UTC) + timedelta(days=1)).isoformat(),
        input_state={},
        actor="admin",
        namespace="default",
        max_runs=None,
    )
    found = await svc.get(schedule.id)
    assert found.id == schedule.id
    assert found.name == "get-test"


@pytest.mark.asyncio
async def test_get_schedule_not_found(session_factory: async_sessionmaker) -> None:
    svc = ScheduleService(session_factory)
    with pytest.raises(ScheduleNotFoundError):
        await svc.get("nonexistent")


@pytest.mark.asyncio
async def test_pause_schedule(session_factory: async_sessionmaker) -> None:
    from ulid import ULID
    svc = ScheduleService(session_factory)
    schedule = await svc.create(
        ulid_factory=ULID,
        workflow_id="wf-005",
        workflow_version=1,
        name="pause-test",
        description=None,
        schedule_type="CRON",
        schedule_value="0 9 * * *",
        input_state={},
        actor="admin",
        namespace="default",
        max_runs=None,
    )
    paused = await svc.pause(schedule.id)
    assert paused.status == "PAUSED"


@pytest.mark.asyncio
async def test_delete_schedule(session_factory: async_sessionmaker) -> None:
    from ulid import ULID
    svc = ScheduleService(session_factory)
    schedule = await svc.create(
        ulid_factory=ULID,
        workflow_id="wf-006",
        workflow_version=1,
        name="delete-test",
        description=None,
        schedule_type="CRON",
        schedule_value="0 9 * * *",
        input_state={},
        actor="admin",
        namespace="default",
        max_runs=None,
    )
    schedule_id = schedule.id
    await svc.delete(schedule_id)
    async with session_factory() as session:
        result = await session.execute(
            text(
                "SELECT status FROM workflow_schedules WHERE id = :id"
            ),
            {"id": schedule_id},
        )
        row = result.fetchone()
        assert row is not None
        assert row.status == "DELETED"


@pytest.mark.asyncio
async def test_compute_next_run_cron() -> None:
    from_time = datetime(2024, 1, 1, 8, 0, 0, tzinfo=UTC)
    next_run = _compute_next_run("CRON", "0 9 * * *", from_time=from_time)
    assert next_run == datetime(2024, 1, 1, 9, 0, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_compute_next_run_interval() -> None:
    from_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
    next_run = _compute_next_run("INTERVAL", "1h", from_time=from_time)
    assert next_run == datetime(2024, 1, 1, 13, 0, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_resume_once_requires_interval_type(
    session_factory: async_sessionmaker,
) -> None:
    from ulid import ULID
    svc = ScheduleService(session_factory)
    future = datetime.now(UTC) + timedelta(days=1)
    schedule = await svc.create(
        ulid_factory=ULID,
        workflow_id="wf-007",
        workflow_version=1,
        name="resume-once",
        description=None,
        schedule_type="ONCE",
        schedule_value=future.isoformat(),
        input_state={},
        actor="admin",
        namespace="default",
        max_runs=None,
    )
    with pytest.raises(InvalidScheduleError, match="Cannot resume an ONCE"):
        await svc.resume(schedule.id)


@pytest.fixture()
async def wf_definitions(session_factory: async_sessionmaker) -> None:
    async with session_factory() as session, session.begin():
        wf_ids = ["wf-sched-claim", "wf-sched-max", "wf-sched-concurrent"]
        await session.execute(
            delete(WorkflowDefinition).where(WorkflowDefinition.id.in_(wf_ids))
        )
        for wf_id in wf_ids:
            wf = WorkflowDefinition(id=wf_id, name=f"test-{wf_id}", version="1")
            session.add(wf)


@pytest.mark.asyncio
async def test_scheduler_claims_due_schedule(
    session_factory: async_sessionmaker,
    mock_settings: Settings,
    wf_definitions: None,
) -> None:
    from ulid import ULID
    svc = SchedulerService(session_factory, mock_settings)
    now = datetime.now(UTC)

    async with session_factory() as session, session.begin():
        schedule = WorkflowSchedule(
            id=str(ULID()),
            workflow_id="wf-sched-claim",
            workflow_version=1,
            name="claim-test",
            description=None,
            schedule_type="CRON",
            schedule_value="0 9 * * *",
            input_state={},
            actor="admin",
            namespace="default",
            status="ACTIVE",
            next_run_at=now - timedelta(minutes=1),
            run_count=0,
        )
        session.add(schedule)

    await svc._process_due_schedules()

    async with session_factory() as session, session.begin():
        result = await session.execute(
            text(
                "SELECT locked_by, locked_until, status, run_count FROM workflow_schedules "
                "WHERE workflow_id = 'wf-sched-claim'"
            )
        )
        rows = result.fetchall()
        assert len(rows) == 1
        assert rows[0].locked_by is None
        assert rows[0].locked_until is None
        assert rows[0].status == "ACTIVE"
        assert rows[0].run_count == 1


@pytest.mark.asyncio
async def test_scheduler_releases_lock_on_exception(
    session_factory: async_sessionmaker,
    mock_settings: Settings,
    wf_definitions: None,
) -> None:
    from ulid import ULID
    svc = SchedulerService(session_factory, mock_settings)
    now = datetime.now(UTC)

    async with session_factory() as session, session.begin():
        schedule = WorkflowSchedule(
            id=str(ULID()),
            workflow_id="wf-nonexistent",
            workflow_version=1,
            name="exception-lock-test",
            description=None,
            schedule_type="CRON",
            schedule_value="0 9 * * *",
            input_state={},
            actor="admin",
            namespace="default",
            status="ACTIVE",
            next_run_at=now - timedelta(minutes=1),
            run_count=0,
        )
        session.add(schedule)

    await svc._process_due_schedules()

    async with session_factory() as session, session.begin():
        result = await session.execute(
            text(
                "SELECT locked_by FROM workflow_schedules "
                "WHERE workflow_id = 'wf-nonexistent'"
            )
        )
        row = result.fetchone()
        assert row is not None
        assert row.locked_by is None


@pytest.mark.asyncio
async def test_scheduler_max_runs_stops(
    session_factory: async_sessionmaker,
    mock_settings: Settings,
    wf_definitions: None,
) -> None:
    from ulid import ULID
    svc = SchedulerService(session_factory, mock_settings)
    now = datetime.now(UTC)

    async with session_factory() as session, session.begin():
        schedule = WorkflowSchedule(
            id=str(ULID()),
            workflow_id="wf-sched-max",
            workflow_version=1,
            name="max-runs-test",
            description=None,
            schedule_type="CRON",
            schedule_value="0 9 * * *",
            input_state={},
            actor="admin",
            namespace="default",
            status="ACTIVE",
            next_run_at=now - timedelta(minutes=1),
            run_count=9,
            max_runs=10,
        )
        session.add(schedule)

    await svc._process_due_schedules()

    async with session_factory() as session, session.begin():
        result = await session.execute(
            text(
                "SELECT status, locked_by, run_count FROM workflow_schedules "
                "WHERE workflow_id = 'wf-sched-max'"
            )
        )
        row = result.fetchone()
        assert row is not None
        assert row.status == "COMPLETED"
        assert row.locked_by is None
        assert row.run_count == 10


@pytest.mark.asyncio
async def test_scheduler_concurrent_lock_no_duplicate(
    session_factory: async_sessionmaker,
    mock_settings: Settings,
    wf_definitions: None,
) -> None:
    from ulid import ULID
    now = datetime.now(UTC)
    schedule_id = str(ULID())

    async with session_factory() as session, session.begin():
        schedule = WorkflowSchedule(
            id=schedule_id,
            workflow_id="wf-sched-concurrent",
            workflow_version=1,
            name="concurrent-test",
            description=None,
            schedule_type="CRON",
            schedule_value="0 9 * * *",
            input_state={},
            actor="admin",
            namespace="default",
            status="ACTIVE",
            next_run_at=now - timedelta(minutes=1),
            run_count=0,
        )
        session.add(schedule)

    svc1 = SchedulerService(session_factory, mock_settings)
    svc2 = SchedulerService(session_factory, mock_settings)

    await asyncio.gather(
        svc1._process_due_schedules(),
        svc2._process_due_schedules(),
    )

    async with session_factory() as session, session.begin():
        result = await session.execute(
            text(
                "SELECT locked_by, run_count FROM workflow_schedules WHERE id = :id"
            ),
            {"id": schedule_id},
        )
        row = result.fetchone()
        assert row is not None
        assert row.locked_by is None
        assert row.run_count == 1

    async with session_factory() as session, session.begin():
        result = await session.execute(
            text(
                "SELECT COUNT(*) FROM workflow_runs WHERE parent_schedule_id = :id"
            ),
            {"id": schedule_id},
        )
        count = result.scalar()
        assert count == 1
