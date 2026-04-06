"""Unit tests for inference/idempotency.py and services/streaming_token_service.py."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session_factory(*, scalars_first=None, scalar_one=None):
    """Create a mock async_sessionmaker for idempotency tests."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    begin_ctx = AsyncMock()
    begin_ctx.__aenter__ = AsyncMock(return_value=None)
    begin_ctx.__aexit__ = AsyncMock(return_value=False)
    session.begin = MagicMock(return_value=begin_ctx)
    session.flush = AsyncMock()

    result = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.first.return_value = scalars_first
    result.scalars.return_value = scalars_mock
    result.scalar_one.return_value = scalar_one
    session.execute = AsyncMock(return_value=result)

    return MagicMock(return_value=session)


# ---------------------------------------------------------------------------
# inference/idempotency.py — IdempotencyStore
# ---------------------------------------------------------------------------


async def test_idempotency_acquire_new_row() -> None:
    from syndicateclaw.inference.idempotency import IdempotencyStore

    inserted_row = MagicMock()
    inserted_row.id = "env-1"
    factory = _make_session_factory(scalars_first=inserted_row)

    store = IdempotencyStore(factory)
    row, is_new = await store.acquire(
        idempotency_key="key-1",
        request_hash="hash-1",
        inference_id="inf-1",
        system_config_version="v1",
        trace_id="trace-1",
    )
    assert is_new is True
    assert row is inserted_row


async def test_idempotency_acquire_conflict_same_hash() -> None:
    from syndicateclaw.inference.idempotency import IdempotencyStore

    existing_row = MagicMock()
    existing_row.request_hash = "hash-1"
    existing_row.last_seen_at = None

    # scalars_first=None means INSERT returned nothing (conflict)
    factory = _make_session_factory(scalars_first=None, scalar_one=existing_row)

    store = IdempotencyStore(factory)
    row, is_new = await store.acquire(
        idempotency_key="key-1",
        request_hash="hash-1",
        inference_id="inf-2",
        system_config_version="v1",
    )
    assert is_new is False
    assert row is existing_row


async def test_idempotency_acquire_conflict_different_hash_raises() -> None:
    from syndicateclaw.inference.errors import IdempotencyConflictError
    from syndicateclaw.inference.idempotency import IdempotencyStore

    existing_row = MagicMock()
    existing_row.request_hash = "hash-different"

    factory = _make_session_factory(scalars_first=None, scalar_one=existing_row)

    store = IdempotencyStore(factory)
    with pytest.raises(IdempotencyConflictError):
        await store.acquire(
            idempotency_key="key-1",
            request_hash="hash-new",
            inference_id="inf-3",
            system_config_version="v1",
        )


async def test_idempotency_mark_executing() -> None:
    from syndicateclaw.inference.idempotency import IdempotencyStore

    factory = _make_session_factory()
    store = IdempotencyStore(factory)
    await store.mark_executing("inf-1")
    # If no exception, test passes


async def test_idempotency_update_completed() -> None:
    from syndicateclaw.inference.idempotency import IdempotencyStore

    factory = _make_session_factory()
    store = IdempotencyStore(factory)
    await store.update_completed("inf-1", result_json={"output": "text"})


async def test_idempotency_update_failed_without_result_json() -> None:
    from syndicateclaw.inference.idempotency import IdempotencyStore

    factory = _make_session_factory()
    store = IdempotencyStore(factory)
    await store.update_failed("inf-1", failure_reason="timeout")


async def test_idempotency_update_failed_with_result_json() -> None:
    from syndicateclaw.inference.idempotency import IdempotencyStore

    factory = _make_session_factory()
    store = IdempotencyStore(factory)
    await store.update_failed("inf-1", failure_reason="error", result_json={"err": "detail"})


# ---------------------------------------------------------------------------
# services/streaming_token_service.py — StreamingTokenRepository
# ---------------------------------------------------------------------------


def _make_streaming_factory(*, scalar_one_or_none=None):
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    begin_ctx = AsyncMock()
    begin_ctx.__aenter__ = AsyncMock(return_value=None)
    begin_ctx.__aexit__ = AsyncMock(return_value=False)
    session.begin = MagicMock(return_value=begin_ctx)
    session.add = MagicMock()

    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar_one_or_none
    session.execute = AsyncMock(return_value=result)

    return MagicMock(return_value=session)


async def test_streaming_token_repository_insert() -> None:
    from syndicateclaw.services.streaming_token_service import StreamingTokenRepository

    factory = _make_streaming_factory()
    repo = StreamingTokenRepository(factory)
    expires = datetime.now(UTC) + timedelta(minutes=5)
    await repo.insert("tok-1", "run-1", "user:1", "streaming", None, expires)
    # Should not raise


async def test_streaming_token_repository_get_found() -> None:
    from datetime import UTC

    from syndicateclaw.services.streaming_token_service import StreamingTokenRepository

    expires = datetime.now(UTC) + timedelta(minutes=5)
    row = MagicMock()
    row.token = "tok-1"
    row.run_id = "run-1"
    row.actor = "user:1"
    row.token_type = "streaming"
    row.workflow_id = None
    row.expires_at = expires
    row.used_at = None

    factory = _make_streaming_factory(scalar_one_or_none=row)
    repo = StreamingTokenRepository(factory)
    record = await repo.get("tok-1")
    assert record is not None
    assert record.token == "tok-1"
    assert record.actor == "user:1"


async def test_streaming_token_repository_get_not_found() -> None:
    from syndicateclaw.services.streaming_token_service import StreamingTokenRepository

    factory = _make_streaming_factory(scalar_one_or_none=None)
    repo = StreamingTokenRepository(factory)
    record = await repo.get("missing-token")
    assert record is None


async def test_streaming_token_repository_mark_used() -> None:
    from syndicateclaw.services.streaming_token_service import StreamingTokenRepository

    factory = _make_streaming_factory()
    repo = StreamingTokenRepository(factory)
    await repo.mark_used("tok-1")


# ---------------------------------------------------------------------------
# StreamingTokenService.validate_and_consume error paths
# ---------------------------------------------------------------------------


async def test_streaming_token_service_validate_token_not_found() -> None:
    from syndicateclaw.services.streaming_token_service import (
        InvalidTokenError,
        StreamingTokenRepository,
        StreamingTokenService,
    )

    repo = MagicMock(spec=StreamingTokenRepository)
    repo.get = AsyncMock(return_value=None)
    service = StreamingTokenService(repo)

    with pytest.raises(InvalidTokenError, match="Token not found"):
        await service.validate_and_consume("bad-token", "run-1")


async def test_streaming_token_service_validate_wrong_type() -> None:
    from syndicateclaw.services.streaming_token_service import (
        InvalidTokenError,
        StreamingTokenRecord,
        StreamingTokenRepository,
        StreamingTokenService,
    )

    record = StreamingTokenRecord(
        token="tok-1",
        run_id="run-1",
        actor="user:1",
        token_type="websocket",
        workflow_id=None,
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
        used_at=None,
    )
    repo = MagicMock(spec=StreamingTokenRepository)
    repo.get = AsyncMock(return_value=record)
    service = StreamingTokenService(repo)

    with pytest.raises(InvalidTokenError, match="Wrong token type"):
        await service.validate_and_consume("tok-1", "run-1")


async def test_streaming_token_service_validate_already_consumed() -> None:
    from syndicateclaw.services.streaming_token_service import (
        InvalidTokenError,
        StreamingTokenRecord,
        StreamingTokenRepository,
        StreamingTokenService,
    )

    record = StreamingTokenRecord(
        token="tok-1",
        run_id="run-1",
        actor="user:1",
        token_type="streaming",
        workflow_id=None,
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
        used_at=datetime.now(UTC),
    )
    repo = MagicMock(spec=StreamingTokenRepository)
    repo.get = AsyncMock(return_value=record)
    service = StreamingTokenService(repo)

    with pytest.raises(InvalidTokenError, match="already consumed"):
        await service.validate_and_consume("tok-1", "run-1")


async def test_streaming_token_service_validate_expired() -> None:
    from syndicateclaw.services.streaming_token_service import (
        InvalidTokenError,
        StreamingTokenRecord,
        StreamingTokenRepository,
        StreamingTokenService,
    )

    record = StreamingTokenRecord(
        token="tok-1",
        run_id="run-1",
        actor="user:1",
        token_type="streaming",
        workflow_id=None,
        expires_at=datetime.now(UTC) - timedelta(minutes=5),
        used_at=None,
    )
    repo = MagicMock(spec=StreamingTokenRepository)
    repo.get = AsyncMock(return_value=record)
    service = StreamingTokenService(repo)

    with pytest.raises(InvalidTokenError, match="expired"):
        await service.validate_and_consume("tok-1", "run-1")


async def test_streaming_token_service_validate_wrong_run() -> None:
    from syndicateclaw.services.streaming_token_service import (
        InvalidTokenError,
        StreamingTokenRecord,
        StreamingTokenRepository,
        StreamingTokenService,
    )

    record = StreamingTokenRecord(
        token="tok-1",
        run_id="run-2",
        actor="user:1",
        token_type="streaming",
        workflow_id=None,
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
        used_at=None,
    )
    repo = MagicMock(spec=StreamingTokenRepository)
    repo.get = AsyncMock(return_value=record)
    service = StreamingTokenService(repo)

    with pytest.raises(InvalidTokenError, match="not valid for this run"):
        await service.validate_and_consume("tok-1", "run-1")
