"""Bootstrap state machine states."""

from __future__ import annotations

from enum import Enum, auto


class BootstrapState(Enum):
    """
    Bootstrap state machine states.

    States:
    - Uninitialized: Initial state, no startup attempted
    - Migrating: Database migrations in progress
    - Initializing: Dependencies being verified and services initialized
    - Ready: All checks passed, ready to serve traffic
    - Running: Accepting traffic
    - Shutdown: Graceful shutdown in progress
    - Failed: Startup failed with error
    """

    UNINITIALIZED = auto()
    MIGRATING = auto()
    INITIALIZING = auto()
    READY = auto()
    RUNNING = auto()
    SHUTDOWN = auto()
    FAILED = auto()

    @property
    def can_serve_traffic(self) -> bool:
        """Returns True if the service can accept traffic."""
        return self in (BootstrapState.READY, BootstrapState.RUNNING)

    @property
    def is_terminal(self) -> bool:
        """Returns True if this is a terminal state."""
        return self in (BootstrapState.SHUTDOWN, BootstrapState.FAILED)

    @property
    def is_transitioning(self) -> bool:
        """Returns True if a transition is in progress."""
        return self in (BootstrapState.MIGRATING, BootstrapState.INITIALIZING)


class BootstrapEvent(Enum):
    """Events that trigger state transitions."""

    START = auto()
    MIGRATIONS_COMPLETE = auto()
    DEPENDENCIES_VERIFIED = auto()
    HEALTH_CHECK_PASSED = auto()
    TRAFFIC_STARTED = auto()
    SHUTDOWN_REQUESTED = auto()
    SHUTDOWN_COMPLETE = auto()
    FAILURE = auto()
    RESET = auto()
