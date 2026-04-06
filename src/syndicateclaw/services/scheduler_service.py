from __future__ import annotations

import asyncio
import os
import socket
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from syndicateclaw.config import Settings
from syndicateclaw.db.models import WorkflowSchedule
from syndicateclaw.services.schedule_service import _compute_next_run

logger = structlog.get_logger(__name__)


class SchedulerService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._instance_id = f"{socket.gethostname()}-{os.getpid()}"
        self._shutdown = asyncio.Event()

    @property
    def instance_id(self) -> str:
        return self._instance_id

    async def start(self) -> None:
        logger.info("scheduler.started", instance_id=self._instance_id)
        while not self._shutdown.is_set():
            try:
                await self._process_due_schedules()
            except Exception as e:
                logger.error("scheduler.poll_error", error=str(e))
            await asyncio.sleep(self._settings.scheduler_poll_interval)

    async def stop(self) -> None:
        self._shutdown.set()
        logger.info("scheduler.stopped", instance_id=self._instance_id)

    async def _process_due_schedules(self) -> None:
        batch_size = self._settings.scheduler_batch_size
        now = datetime.now(UTC)

        async with self._session_factory() as session, session.begin():
            stmt = text("""
                WITH claimed AS (
                    SELECT id FROM workflow_schedules
                    WHERE status = 'ACTIVE'
                      AND next_run_at <= :now
                      AND (locked_until IS NULL OR locked_until <= :now)
                    ORDER BY next_run_at ASC
                    LIMIT :batch_size
                    FOR UPDATE SKIP LOCKED
                )
                UPDATE workflow_schedules
                SET locked_by = :instance_id,
                    locked_until = :locked_until
                WHERE id IN (SELECT id FROM claimed)
                RETURNING id, workflow_id, workflow_version, schedule_type,
                          schedule_value, input_state, actor, namespace,
                          max_runs, run_count
            """)
            result = await session.execute(
                stmt,
                {
                    "instance_id": self._instance_id,
                    "locked_until": datetime.fromtimestamp(
                        now.timestamp() + self._settings.scheduler_lock_lease_seconds, tz=UTC
                    ),
                    "now": now,
                    "batch_size": batch_size,
                },
            )
            rows = result.fetchall()

        if not rows:
            return

        logger.info("scheduler.claimed_schedules", count=len(rows))

        tasks = [
            asyncio.create_task(
                self._execute_and_release(row, session_factory=self._session_factory)
            )
            for row in rows
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _execute_and_release(
        self,
        schedule_row: Any,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        schedule_id = schedule_row.id
        new_status: str | None = None
        next_run: datetime | None = None
        try:
            await self._execute_schedule(schedule_row, session_factory)
        except Exception as e:
            logger.error(
                "scheduler.execution_failed",
                schedule_id=schedule_id,
                error=str(e),
            )
        else:
            now = datetime.now(UTC)
            if (
                schedule_row.max_runs is not None
                and schedule_row.run_count + 1 >= schedule_row.max_runs
            ) or schedule_row.schedule_type == "ONCE":
                new_status = "COMPLETED"
                next_run = None
            else:
                next_run = _compute_next_run(
                    schedule_row.schedule_type,
                    schedule_row.schedule_value,
                    from_time=now,
                )
        finally:
            await self._release_lock(
                schedule_id,
                run_count=schedule_row.run_count,
                new_status=new_status,
                next_run=next_run,
            )

    async def _execute_schedule(
        self, schedule_row: Any, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        schedule_id = schedule_row.id
        if schedule_row.max_runs is not None and schedule_row.run_count >= schedule_row.max_runs:
            logger.info(
                "scheduler.max_runs_reached",
                schedule_id=schedule_id,
                run_count=schedule_row.run_count,
                max_runs=schedule_row.max_runs,
            )
            return

        async with session_factory() as session, session.begin():
            run_id = await self._create_run(
                session,
                workflow_id=schedule_row.workflow_id,
                workflow_version=schedule_row.workflow_version,
                input_state=schedule_row.input_state,
                actor=schedule_row.actor,
                namespace=schedule_row.namespace,
                triggered_by="SCHEDULE",
                schedule_id=schedule_id,
            )
        logger.info(
            "scheduler.run_triggered",
            schedule_id=schedule_id,
            run_id=run_id,
        )

    async def _create_run(
        self,
        session: AsyncSession,
        *,
        workflow_id: str,
        workflow_version: int | None,
        input_state: dict[str, Any],
        actor: str,
        namespace: str,
        triggered_by: str,
        schedule_id: str,
    ) -> str:
        from ulid import ULID

        from syndicateclaw.db.models import WorkflowRun

        version_str = str(workflow_version) if workflow_version is not None else "1"
        run = WorkflowRun(
            id=str(ULID()),
            workflow_id=workflow_id,
            workflow_version=version_str,
            initiated_by=actor,
            state=input_state,
            namespace=namespace,
            triggered_by=triggered_by,
            parent_schedule_id=schedule_id,
            owning_scope_type="NAMESPACE",
            owning_scope_id=namespace,
        )
        session.add(run)
        await session.flush()
        return run.id

    async def _release_lock(
        self,
        schedule_id: str,
        *,
        run_count: int,
        new_status: str | None,
        next_run: datetime | None,
    ) -> None:
        try:
            now = datetime.now(UTC)
            async with self._session_factory() as session:
                updates: dict[str, Any] = {
                    "locked_by": None,
                    "locked_until": None,
                    "updated_at": now,
                    "run_count": run_count + 1,
                    "last_run_at": now,
                }
                if next_run is not None:
                    updates["next_run_at"] = next_run
                if new_status is not None:
                    updates["status"] = new_status

                await session.execute(
                    update(WorkflowSchedule)
                    .where(WorkflowSchedule.id == schedule_id)
                    .values(**updates)
                )
                await session.commit()
        except Exception as e:
            logger.error("scheduler.release_lock_failed", schedule_id=schedule_id, error=str(e))
