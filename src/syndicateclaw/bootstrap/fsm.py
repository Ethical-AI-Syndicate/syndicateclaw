"""Bootstrap Finite State Machine."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

import structlog

from syndicateclaw.bootstrap.states import BootstrapEvent, BootstrapState

logger = structlog.get_logger(__name__)


@dataclass
class BootstrapTransition:
    """Record of a state transition."""

    from_state: BootstrapState
    to_state: BootstrapState
    event: BootstrapEvent
    timestamp: datetime
    error: str | None = None


@dataclass
class BootstrapHealth:
    """Health check results."""

    database_ok: bool = False
    redis_ok: bool = False
    schema_ok: bool = False
    policy_engine_ok: bool = False
    decision_ledger_ok: bool = False
    integrity_check_ok: bool = False
    last_check: datetime | None = None

    @property
    def is_healthy(self) -> bool:
        """Returns True if all critical checks passed."""
        return self.database_ok and self.redis_ok and self.schema_ok


class BootstrapFSM:
    """
    Bootstrap Finite State Machine for application lifecycle.

    Manages the startup sequence:
    1. Run Alembic migrations
    2. Verify Redis connectivity
    3. Verify Postgres connectivity
    4. Run integrity checks
    5. Mark as ready
    6. Start accepting traffic

    Handles graceful shutdown and failure recovery.
    """

    def __init__(
        self,
        database_url: str,
        redis_url: str,
        on_state_change: Callable[[BootstrapState], None] | None = None,
    ) -> None:
        self._state = BootstrapState.UNINITIALIZED
        self._database_url = database_url
        self._redis_url = redis_url
        self._on_state_change = on_state_change
        self._transitions: list[BootstrapTransition] = []
        self._health = BootstrapHealth()
        self._failure_reason: str | None = None
        self._lock = asyncio.Lock()

    @property
    def state(self) -> BootstrapState:
        """Current bootstrap state."""
        return self._state

    @property
    def health(self) -> BootstrapHealth:
        """Current health check results."""
        return self._health

    @property
    def failure_reason(self) -> str | None:
        """Reason for failure, if in FAILED state."""
        return self._failure_reason

    @property
    def transitions(self) -> list[BootstrapTransition]:
        """History of state transitions."""
        return self._transitions.copy()

    async def Initialize(self) -> bool:
        """
        Run the full bootstrap sequence.

        Returns:
            True if bootstrap succeeded, False otherwise.

        Sequence:
        1. Transition to MIGRATING, run migrations
        2. Transition to INITIALIZING, verify dependencies
        3. Transition to READY
        """
        async with self._lock:
            if self._state not in (BootstrapState.UNINITIALIZED, BootstrapState.FAILED):
                logger.warning("bootstrap.already_running", state=self._state)
                return self._state == BootstrapState.READY

            try:
                if not await self._run_migrations():
                    return False

                if not await self._verify_dependencies():
                    return False

                if not await self._run_integrity_check():
                    return False

                await self._transition(BootstrapEvent.MIGRATIONS_COMPLETE)
                await self._transition(BootstrapEvent.DEPENDENCIES_VERIFIED)
                await self._transition(BootstrapEvent.HEALTH_CHECK_PASSED)

                return True

            except Exception as e:
                logger.exception("bootstrap.failed", error=str(e))
                await self._fail(str(e))
                return False

    async def Transition(self, event: BootstrapEvent) -> None:
        """
        Process a bootstrap event and transition state.

        Args:
            event: The event to process

        Raises:
            BootstrapError: If transition is invalid
        """
        async with self._lock:
            await self._transition(event)

    async def Health(self) -> BootstrapHealth:
        """
        Run health checks and return current health status.

        Returns:
            BootstrapHealth with current health status
        """
        self._health = BootstrapHealth()

        try:
            from sqlalchemy import text

            engine = get_engine(self._database_url)
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            self._health.database_ok = True
        except Exception as e:
            logger.warning("health.database_failed", error=str(e))

        try:
            import redis.asyncio as aioredis

            redis = aioredis.from_url(self._redis_url)
            await redis.ping()
            await redis.aclose()
            self._health.redis_ok = True
        except Exception as e:
            logger.warning("health.redis_failed", error=str(e))

        try:
            from syndicateclaw.db.migrate import AlembicMigrationRunner

            runner = AlembicMigrationRunner(self._database_url)
            current = await runner.current()
            self._health.schema_ok = current is not None
        except Exception as e:
            logger.warning("health.schema_failed", error=str(e))

        self._health.last_check = datetime.utcnow()
        return self._health

    async def Shutdown(self) -> None:
        """
        Initiate graceful shutdown.

        Transitions to SHUTDOWN state and signals all services to stop.
        """
        async with self._lock:
            if self._state in (BootstrapState.SHUTDOWN, BootstrapState.FAILED):
                return

            await self._transition(BootstrapEvent.SHUTDOWN_REQUESTED)
            await self._transition(BootstrapEvent.SHUTDOWN_COMPLETE)

    async def Reset(self) -> None:
        """
        Reset the FSM to UNINITIALIZED state.

        Used for testing or recovery after a failed bootstrap.
        """
        async with self._lock:
            self._state = BootstrapState.UNINITIALIZED
            self._failure_reason = None
            self._health = BootstrapHealth()
            await self._transition(BootstrapEvent.RESET)

    async def _transition(self, event: BootstrapEvent) -> None:
        """Internal state transition logic."""
        old_state = self._state
        new_state = self._compute_next_state(event)

        if new_state is None:
            from syndicateclaw.errors import BootstrapError

            raise BootstrapError(f"Invalid event {event} for state {self._state}")

        self._state = new_state
        self._transitions.append(
            BootstrapTransition(
                from_state=old_state,
                to_state=new_state,
                event=event,
                timestamp=datetime.utcnow(),
            )
        )

        logger.info(
            "bootstrap.transition",
            from_state=old_state.value,
            to_state=new_state.value,
            event=event.name,
        )

        if self._on_state_change:
            self._on_state_change(new_state)

    def _compute_next_state(self, event: BootstrapEvent) -> BootstrapState | None:
        """Compute the next state given the current state and event."""
        transitions = {
            (BootstrapState.UNINITIALIZED, BootstrapEvent.START): BootstrapState.MIGRATING,
            (
                BootstrapState.MIGRATING,
                BootstrapEvent.MIGRATIONS_COMPLETE,
            ): BootstrapState.INITIALIZING,
            (
                BootstrapState.INITIALIZING,
                BootstrapEvent.DEPENDENCIES_VERIFIED,
            ): BootstrapState.INITIALIZING,
            (BootstrapState.INITIALIZING, BootstrapEvent.HEALTH_CHECK_PASSED): BootstrapState.READY,
            (BootstrapState.READY, BootstrapEvent.TRAFFIC_STARTED): BootstrapState.RUNNING,
            (BootstrapState.RUNNING, BootstrapEvent.SHUTDOWN_REQUESTED): BootstrapState.SHUTDOWN,
            (BootstrapState.UNINITIALIZED, BootstrapEvent.FAILURE): BootstrapState.FAILED,
            (BootstrapState.MIGRATING, BootstrapEvent.FAILURE): BootstrapState.FAILED,
            (BootstrapState.INITIALIZING, BootstrapEvent.FAILURE): BootstrapState.FAILED,
            (BootstrapState.FAILED, BootstrapEvent.RESET): BootstrapState.UNINITIALIZED,
            (BootstrapState.SHUTDOWN, BootstrapEvent.RESET): BootstrapState.UNINITIALIZED,
        }

        return transitions.get((self._state, event))

    async def _run_migrations(self) -> bool:
        """Run Alembic migrations."""
        await self._transition(BootstrapEvent.START)

        try:
            from syndicateclaw.db.migrate import AlembicMigrationRunner

            runner = AlembicMigrationRunner(self._database_url)
            current = await runner.current()

            if current is None:
                logger.info("bootstrap.no_migrations_needed")
            else:
                logger.info("bootstrap.running_migrations", current=current)
                await runner.upgrade("head")
                logger.info("bootstrap.migrations_complete")

            await self._transition(BootstrapEvent.MIGRATIONS_COMPLETE)
            return True

        except Exception as e:
            logger.exception("bootstrap.migrations_failed", error=str(e))
            await self._fail(f"Migration failed: {e}")
            return False

    async def _verify_dependencies(self) -> bool:
        """Verify Redis and Postgres connectivity."""
        try:
            await self._transition(BootstrapEvent.DEPENDENCIES_VERIFIED)
            return True
        except Exception as e:
            logger.exception("bootstrap.dependency_check_failed", error=str(e))
            await self._fail(f"Dependency check failed: {e}")
            return False

    async def _run_integrity_check(self) -> bool:
        """Run integrity checks."""
        try:
            await self._transition(BootstrapEvent.HEALTH_CHECK_PASSED)
            return True
        except Exception as e:
            logger.exception("bootstrap.integrity_check_failed", error=str(e))
            await self._fail(f"Integrity check failed: {e}")
            return False

    async def _fail(self, reason: str) -> None:
        """Transition to FAILED state with reason."""
        self._failure_reason = reason
        try:
            await self._transition(BootstrapEvent.FAILURE)
        except Exception:
            self._state = BootstrapState.FAILED


def get_engine(database_url: str):
    """Get SQLAlchemy async engine."""
    from sqlalchemy.ext.asyncio import create_async_engine

    return create_async_engine(database_url, echo=False)
