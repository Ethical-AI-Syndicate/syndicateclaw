"""Chaos / failure injection helpers (v2.0.0).

When Docker or privileged ops are unavailable, tests use mocks instead.
"""

from __future__ import annotations

import contextlib
from typing import Any
from unittest.mock import patch


def restore_all() -> None:
    """No-op placeholder — extend with cleanup when using real infra hooks."""
    return None


@contextlib.contextmanager
def mock_redis_down(redis_client: Any) -> Any:
    """Temporarily make Redis ping fail."""
    async def fail_ping() -> None:
        raise OSError("mock redis down")

    with patch.object(redis_client, "ping", fail_ping):
        yield


@contextlib.contextmanager
def mock_db_execute_failure(session: Any) -> Any:
    """Inject failure on session.execute for targeted tests."""

    async def boom(*args: Any, **kwargs: Any) -> Any:
        raise OSError("mock database execute failure")

    with patch.object(session, "execute", boom):
        yield
