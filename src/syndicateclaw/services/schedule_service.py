from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from croniter import croniter  # type: ignore[import-untyped]
from sqlalchemy import CursorResult, Select, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from syndicateclaw.db.models import WorkflowSchedule

if TYPE_CHECKING:
    from ulid import ULID


class ScheduleNotFoundError(Exception):
    """Raised when a schedule record does not exist."""


class ScheduleConflictError(Exception):
    """Raised on schedule name uniqueness collisions within a namespace."""


class InvalidScheduleError(ValueError):
    """Raised when a schedule value cannot be parsed or is invalid."""


def _parse_interval(value: str) -> int | None:
    try:
        import pytimeparse  # type: ignore[import-untyped]

        result = pytimeparse.parse(value)
        if result is not None:
            return int(result)
        return None
    except Exception:
        return None


def validate_schedule_value(schedule_type: str, value: str) -> datetime:
    """Validate a schedule value and return the next run time.

    Raises InvalidScheduleError if the value is invalid.
    """
    utcnow = datetime.now(UTC)

    if schedule_type == "CRON":
        if not croniter.is_valid(value):
            raise InvalidScheduleError(
                f"Invalid CRON expression: '{value}'. "
                "Use standard 5-field CRON syntax (minute hour day month weekday)."
            )
        return croniter(value, utcnow).get_next(datetime)  # type: ignore[no-any-return]

    if schedule_type == "INTERVAL":
        parsed_seconds = _parse_interval(value)
        if parsed_seconds is None:
            raise InvalidScheduleError(
                f"Invalid INTERVAL value: '{value}'. "
                "Use a human-readable duration such as '1h', '30m', '7d', '2 weeks'."
            )
        if parsed_seconds < 60:
            raise InvalidScheduleError(
                f"INTERVAL must be at least 60 seconds, got {parsed_seconds}s for '{value}'."
            )
        return datetime.fromtimestamp(utcnow.timestamp() + parsed_seconds, tz=UTC)

    if schedule_type == "ONCE":
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise InvalidScheduleError(
                f"Invalid ONCE datetime: '{value}'. "
                "Use ISO 8601 format (e.g. 2024-12-31T23:59:59Z)."
            ) from None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        if parsed <= utcnow:
            raise InvalidScheduleError(f"ONCE datetime must be in the future, got '{value}'.")
        return parsed

    raise InvalidScheduleError(
        f"Unknown schedule_type '{schedule_type}'. Must be CRON, INTERVAL, or ONCE."
    )


def _compute_next_run(
    schedule_type: str, schedule_value: str, *, from_time: datetime | None = None
) -> datetime:
    utcnow = from_time if from_time is not None else datetime.now(UTC)
    if schedule_type == "CRON":
        return croniter(schedule_value, utcnow).get_next(datetime)  # type: ignore[no-any-return]
    if schedule_type == "INTERVAL":
        seconds = _parse_interval(schedule_value)
        if seconds is None:
            raise InvalidScheduleError(f"Could not parse INTERVAL: {schedule_value}")
        return datetime.fromtimestamp(utcnow.timestamp() + seconds, tz=UTC)
    if schedule_type == "ONCE":
        return datetime.fromisoformat(schedule_value.replace("Z", "+00:00"))
    raise InvalidScheduleError(f"Unknown schedule_type: {schedule_type}")


class ScheduleService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(
        self,
        *,
        ulid_factory: type[ULID],
        workflow_id: str,
        workflow_version: int | None,
        name: str,
        description: str | None,
        schedule_type: str,
        schedule_value: str,
        input_state: dict[str, Any],
        actor: str,
        namespace: str,
        max_runs: int | None,
    ) -> WorkflowSchedule:
        next_run_at = validate_schedule_value(schedule_type, schedule_value)
        schedule_id = str(ulid_factory())

        async with self._session_factory() as session:
            schedule = WorkflowSchedule(
                id=schedule_id,
                workflow_id=workflow_id,
                workflow_version=workflow_version,
                name=name,
                description=description,
                schedule_type=schedule_type,
                schedule_value=schedule_value,
                input_state=input_state,
                actor=actor,
                namespace=namespace,
                status="ACTIVE",
                next_run_at=next_run_at,
                max_runs=max_runs,
                run_count=0,
            )
            session.add(schedule)
            try:
                await session.commit()
            except Exception as e:
                await session.rollback()
                raise ScheduleConflictError(
                    f"A schedule named '{name}' already exists in namespace '{namespace}'."
                ) from e

            await session.refresh(schedule)
            return schedule

    async def get(self, schedule_id: str) -> WorkflowSchedule:
        async with self._session_factory() as session:
            stmt: Select[tuple[WorkflowSchedule]] = select(WorkflowSchedule).where(
                WorkflowSchedule.id == schedule_id
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if row is None:
                raise ScheduleNotFoundError(f"Schedule '{schedule_id}' not found.")
            return row

    async def list(
        self, namespace: str, *, offset: int = 0, limit: int = 100
    ) -> list[WorkflowSchedule]:
        stmt: Select[tuple[WorkflowSchedule]] = (
            select(WorkflowSchedule)
            .where(WorkflowSchedule.namespace == namespace)
            .order_by(WorkflowSchedule.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        async with self._session_factory() as session:
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def update(
        self,
        schedule_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        schedule_type: str | None = None,
        schedule_value: str | None = None,
        input_state: dict[str, Any] | None = None,
        max_runs: int | None = None,
        status: str | None = None,
    ) -> WorkflowSchedule:
        async with self._session_factory() as session:
            stmt: Select[tuple[WorkflowSchedule]] = select(WorkflowSchedule).where(
                WorkflowSchedule.id == schedule_id
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if row is None:
                raise ScheduleNotFoundError(f"Schedule '{schedule_id}' not found.")

            if name is not None:
                row.name = name
            if description is not None:
                row.description = description
            if schedule_type is not None:
                row.schedule_type = schedule_type
            if schedule_value is not None:
                row.schedule_value = schedule_value
            if input_state is not None:
                row.input_state = input_state
            if max_runs is not None:
                row.max_runs = max_runs
            if status is not None:
                row.status = status

            if schedule_type is not None or schedule_value is not None:
                effective_type = schedule_type or row.schedule_type
                effective_value = schedule_value or row.schedule_value
                row.next_run_at = validate_schedule_value(effective_type, effective_value)

            row.updated_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(row)
            return row

    async def delete(self, schedule_id: str) -> None:
        async with self._session_factory() as session:
            stmt = (
                update(WorkflowSchedule)
                .where(WorkflowSchedule.id == schedule_id)
                .values(status="DELETED", updated_at=datetime.now(UTC))
            )
            result = await session.execute(stmt)
            if cast(CursorResult[Any], result).rowcount == 0:
                raise ScheduleNotFoundError(f"Schedule '{schedule_id}' not found.")
            await session.commit()

    async def pause(self, schedule_id: str) -> WorkflowSchedule:
        return await self.update(schedule_id, status="PAUSED")

    async def resume(self, schedule_id: str) -> WorkflowSchedule:
        async with self._session_factory() as session:
            stmt: Select[tuple[WorkflowSchedule]] = select(WorkflowSchedule).where(
                WorkflowSchedule.id == schedule_id
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if row is None:
                raise ScheduleNotFoundError(f"Schedule '{schedule_id}' not found.")
            if row.schedule_type == "ONCE":
                raise InvalidScheduleError("Cannot resume an ONCE schedule.")
            row.status = "ACTIVE"
            row.next_run_at = _compute_next_run(row.schedule_type, row.schedule_value)
            row.updated_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(row)
            return row
