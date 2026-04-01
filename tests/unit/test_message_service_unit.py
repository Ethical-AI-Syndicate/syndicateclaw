"""Unit tests for MessageService paths not covered by integration tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from syndicateclaw.services.message_service import (
    BroadcastPermissionDeniedError,
    MessageNotFoundError,
    MessageService,
)


def _make_factory(*, get_return=None, scalars_return=None):
    """Return a mock session factory with configurable results."""
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_begin = AsyncMock()
    mock_begin.__aenter__ = AsyncMock(return_value=None)
    mock_begin.__aexit__ = AsyncMock(return_value=False)
    mock_session.begin = MagicMock(return_value=mock_begin)

    mock_session.get = AsyncMock(return_value=get_return)

    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = scalars_return or []
    result.scalars.return_value = scalars
    mock_session.execute = AsyncMock(return_value=result)
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()

    return MagicMock(return_value=mock_session), mock_session


def _make_svc(factory, *, redis=None):
    agent_svc = AsyncMock()
    sub_svc = AsyncMock()
    router = AsyncMock()
    router.route = AsyncMock()
    router.relay_payload = MagicMock(return_value={"hop_count": 1})
    return MessageService(
        factory,
        agent_service=agent_svc,
        subscription_service=sub_svc,
        router=router,
        redis_client=redis,
    )


# ---------------------------------------------------------------------------
# _enforce_broadcast_rate_limit (redis path)
# ---------------------------------------------------------------------------


async def test_enforce_broadcast_rate_limit_under_cap() -> None:
    redis = AsyncMock()
    pipe = MagicMock()
    pipe.execute = AsyncMock(return_value=[None, None, 5, None])  # count=5, under 10
    redis.pipeline = MagicMock(return_value=pipe)

    factory, _ = _make_factory()
    svc = _make_svc(factory, redis=redis)
    # Should not raise
    await svc._enforce_broadcast_rate_limit("actor-1")
    pipe.zremrangebyscore.assert_called_once()
    pipe.zadd.assert_called_once()
    pipe.zcard.assert_called_once()
    pipe.expire.assert_called_once()


async def test_enforce_broadcast_rate_limit_over_cap_raises() -> None:
    redis = AsyncMock()
    pipe = MagicMock()
    pipe.execute = AsyncMock(return_value=[None, None, 11, None])  # count=11, over 10
    redis.pipeline = MagicMock(return_value=pipe)

    factory, _ = _make_factory()
    svc = _make_svc(factory, redis=redis)
    with pytest.raises(BroadcastPermissionDeniedError, match="rate limit"):
        await svc._enforce_broadcast_rate_limit("actor-1")


async def test_enforce_broadcast_rate_limit_skips_when_no_redis() -> None:
    factory, _ = _make_factory()
    svc = _make_svc(factory, redis=None)
    # Should return immediately without touching anything
    await svc._enforce_broadcast_rate_limit("actor-1")


# ---------------------------------------------------------------------------
# list_for_actor
# ---------------------------------------------------------------------------


async def test_list_for_actor_returns_messages() -> None:
    msg1 = MagicMock()
    msg2 = MagicMock()
    factory, _ = _make_factory(scalars_return=[msg1, msg2])
    svc = _make_svc(factory)
    result = await svc.list_for_actor("actor-1")
    assert result == [msg1, msg2]


async def test_list_for_actor_empty() -> None:
    factory, _ = _make_factory(scalars_return=[])
    svc = _make_svc(factory)
    result = await svc.list_for_actor("actor-1")
    assert result == []


# ---------------------------------------------------------------------------
# get_for_actor
# ---------------------------------------------------------------------------


async def test_get_for_actor_returns_message_when_sender() -> None:
    msg = MagicMock()
    msg.sender = "actor-1"
    msg.recipient = "other"
    factory, _ = _make_factory(get_return=msg)
    svc = _make_svc(factory)
    result = await svc.get_for_actor("actor-1", "msg-1")
    assert result is msg


async def test_get_for_actor_returns_message_when_recipient() -> None:
    msg = MagicMock()
    msg.sender = "other"
    msg.recipient = "actor-1"
    factory, _ = _make_factory(get_return=msg)
    svc = _make_svc(factory)
    result = await svc.get_for_actor("actor-1", "msg-1")
    assert result is msg


async def test_get_for_actor_raises_when_not_found() -> None:
    factory, _ = _make_factory(get_return=None)
    svc = _make_svc(factory)
    with pytest.raises(MessageNotFoundError, match="not found"):
        await svc.get_for_actor("actor-1", "missing")


async def test_get_for_actor_raises_when_wrong_actor() -> None:
    msg = MagicMock()
    msg.sender = "alice"
    msg.recipient = "bob"
    factory, _ = _make_factory(get_return=msg)
    svc = _make_svc(factory)
    with pytest.raises(MessageNotFoundError, match="not found"):
        await svc.get_for_actor("eve", "msg-1")


# ---------------------------------------------------------------------------
# ack
# ---------------------------------------------------------------------------


async def test_ack_updates_status_and_returns_row() -> None:
    from datetime import UTC, datetime

    msg = MagicMock()
    msg.recipient = "actor-1"
    factory, _ = _make_factory(get_return=msg)
    svc = _make_svc(factory)
    result = await svc.ack("actor-1", "msg-1")
    assert result is msg
    assert msg.status == "ACKED"
    assert isinstance(msg.acked_at, datetime)
    assert msg.acked_at.tzinfo == UTC


async def test_ack_raises_when_not_found() -> None:
    factory, _ = _make_factory(get_return=None)
    svc = _make_svc(factory)
    with pytest.raises(MessageNotFoundError, match="not found"):
        await svc.ack("actor-1", "missing")


async def test_ack_raises_when_wrong_recipient() -> None:
    msg = MagicMock()
    msg.recipient = "bob"
    factory, _ = _make_factory(get_return=msg)
    svc = _make_svc(factory)
    with pytest.raises(MessageNotFoundError, match="not found"):
        await svc.ack("alice", "msg-1")
