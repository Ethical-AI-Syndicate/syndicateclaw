"""Unit tests for tasks/agent_heartbeat.py, connectors/registry.py,
streaming/connection_manager.py, tasks/agent_response_resume.py."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# tasks/agent_heartbeat.py
# ---------------------------------------------------------------------------


async def test_expire_stale_agents_returns_count() -> None:
    from syndicateclaw.tasks.agent_heartbeat import expire_stale_agents

    agent_service = AsyncMock()
    agent_service.transition_stale_to_offline = AsyncMock(return_value=3)
    result = await expire_stale_agents(agent_service)
    assert result == 3


async def test_expire_stale_agents_zero_transitioned() -> None:
    from syndicateclaw.tasks.agent_heartbeat import expire_stale_agents

    agent_service = AsyncMock()
    agent_service.transition_stale_to_offline = AsyncMock(return_value=0)
    result = await expire_stale_agents(agent_service)
    assert result == 0


async def test_run_agent_heartbeat_expiry_loop_calls_expire() -> None:
    """Run one iteration then cancel."""
    from syndicateclaw.tasks.agent_heartbeat import run_agent_heartbeat_expiry_loop

    agent_service = AsyncMock()
    agent_service.transition_stale_to_offline = AsyncMock(return_value=2)

    with (
        patch(
            "syndicateclaw.tasks.agent_heartbeat.asyncio.sleep",
            new=AsyncMock(side_effect=asyncio.CancelledError),
        ),
        pytest.raises(asyncio.CancelledError),
    ):
        await run_agent_heartbeat_expiry_loop(agent_service, interval_seconds=1)

    agent_service.transition_stale_to_offline.assert_awaited_once()


async def test_run_agent_heartbeat_expiry_loop_logs_on_exception() -> None:
    """Exception is caught and logged; loop continues until cancelled."""
    from syndicateclaw.tasks.agent_heartbeat import run_agent_heartbeat_expiry_loop

    agent_service = AsyncMock()
    agent_service.transition_stale_to_offline = AsyncMock(side_effect=RuntimeError("db down"))

    with (
        patch(
            "syndicateclaw.tasks.agent_heartbeat.asyncio.sleep",
            new=AsyncMock(side_effect=asyncio.CancelledError),
        ),
        pytest.raises(asyncio.CancelledError),
    ):
        await run_agent_heartbeat_expiry_loop(agent_service, interval_seconds=1)


# ---------------------------------------------------------------------------
# connectors/registry.py
# ---------------------------------------------------------------------------


def _make_connector(platform_value: str) -> Any:
    from syndicateclaw.connectors.base import ConnectorBase, ConnectorStatus, Platform

    platform = Platform(platform_value)
    connector = MagicMock(spec=ConnectorBase)
    connector.platform = platform
    status = ConnectorStatus(platform=platform, connected=True)
    connector.status = status
    connector.start = AsyncMock()
    connector.stop = AsyncMock()
    return connector


def test_connector_registry_register_and_get() -> None:
    from syndicateclaw.connectors.registry import ConnectorRegistry

    registry = ConnectorRegistry()
    connector = _make_connector("telegram")
    registry.register(connector)
    from syndicateclaw.connectors.base import Platform

    result = registry.get(Platform.TELEGRAM)
    assert result is connector


def test_connector_registry_get_missing_returns_none() -> None:
    from syndicateclaw.connectors.base import Platform
    from syndicateclaw.connectors.registry import ConnectorRegistry

    registry = ConnectorRegistry()
    result = registry.get(Platform.SLACK)
    assert result is None


def test_connector_registry_all_returns_list() -> None:
    from syndicateclaw.connectors.registry import ConnectorRegistry

    registry = ConnectorRegistry()
    c1 = _make_connector("telegram")
    c2 = _make_connector("discord")
    registry.register(c1)
    registry.register(c2)
    all_connectors = registry.all()
    assert len(all_connectors) == 2


def test_connector_registry_statuses() -> None:
    from syndicateclaw.connectors.registry import ConnectorRegistry

    registry = ConnectorRegistry()
    connector = _make_connector("slack")
    registry.register(connector)
    statuses = registry.statuses()
    assert len(statuses) == 1
    assert statuses[0].connected is True


async def test_connector_registry_start_all() -> None:
    from syndicateclaw.connectors.registry import ConnectorRegistry

    registry = ConnectorRegistry()
    c1 = _make_connector("telegram")
    registry.register(c1)
    await registry.start_all()
    c1.start.assert_awaited_once()


async def test_connector_registry_start_all_logs_exception() -> None:
    from syndicateclaw.connectors.registry import ConnectorRegistry

    registry = ConnectorRegistry()
    c1 = _make_connector("discord")
    c1.start = AsyncMock(side_effect=RuntimeError("start failed"))
    registry.register(c1)
    # Should not raise
    await registry.start_all()


async def test_connector_registry_stop_all() -> None:
    from syndicateclaw.connectors.registry import ConnectorRegistry

    registry = ConnectorRegistry()
    c1 = _make_connector("slack")
    registry.register(c1)
    await registry.stop_all()
    c1.stop.assert_awaited_once()


async def test_connector_registry_stop_all_logs_exception() -> None:
    from syndicateclaw.connectors.registry import ConnectorRegistry

    registry = ConnectorRegistry()
    c1 = _make_connector("telegram")
    c1.stop = AsyncMock(side_effect=RuntimeError("stop failed"))
    registry.register(c1)
    # Should not raise
    await registry.stop_all()


def test_build_registry_no_tokens_returns_empty() -> None:
    from syndicateclaw.connectors.registry import build_registry

    settings = SimpleNamespace(
        telegram_bot_token=None,
        discord_bot_token=None,
        slack_bot_token=None,
        slack_signing_secret=None,
    )
    registry = build_registry(settings, MagicMock())
    assert registry.all() == []


# ---------------------------------------------------------------------------
# streaming/connection_manager.py
# ---------------------------------------------------------------------------


async def test_connection_manager_subscribe_and_broadcast() -> None:
    from syndicateclaw.streaming.connection_manager import ConnectionManager

    cm = ConnectionManager()
    q = await cm.subscribe("run-1")
    await cm.broadcast("run-1", {"type": "event"})
    event = q.get_nowait()
    assert event["type"] == "event"


async def test_connection_manager_unsubscribe() -> None:
    from syndicateclaw.streaming.connection_manager import ConnectionManager

    cm = ConnectionManager()
    q = await cm.subscribe("run-1")
    await cm.unsubscribe("run-1", q)
    await cm.broadcast("run-1", {"type": "event"})
    assert q.empty()


async def test_connection_manager_broadcast_removes_full_queues() -> None:
    from syndicateclaw.streaming.connection_manager import ConnectionManager

    cm = ConnectionManager()
    # Create a full queue
    q = asyncio.Queue(maxsize=1)
    q.put_nowait({"existing": "item"})
    cm._connections["run-1"].add(q)

    # broadcast should detect QueueFull and discard q
    await cm.broadcast("run-1", {"type": "overflow"})
    assert q not in cm._connections["run-1"]


async def test_connection_manager_broadcast_no_subscribers() -> None:
    from syndicateclaw.streaming.connection_manager import ConnectionManager

    cm = ConnectionManager()
    # Should not raise
    await cm.broadcast("run-no-subs", {"type": "event"})


# ---------------------------------------------------------------------------
# tasks/agent_response_resume.py
# ---------------------------------------------------------------------------


def test_parse_requested_at_valid_iso() -> None:
    from syndicateclaw.tasks.agent_response_resume import _parse_requested_at

    result = _parse_requested_at("2024-01-15T10:30:00Z")
    assert result is not None
    assert result.tzinfo is not None


def test_parse_requested_at_invalid_returns_none() -> None:
    from syndicateclaw.tasks.agent_response_resume import _parse_requested_at

    result = _parse_requested_at("not-a-date")
    assert result is None


async def test_resume_waiting_runs_once_no_waiting_runs() -> None:
    from syndicateclaw.tasks.agent_response_resume import resume_waiting_runs_once

    message_service = AsyncMock()
    message_service.delivered_responses = AsyncMock(return_value=[])

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_begin = AsyncMock()
    mock_begin.__aenter__ = AsyncMock(return_value=None)
    mock_begin.__aexit__ = AsyncMock(return_value=False)
    mock_session.begin = MagicMock(return_value=mock_begin)

    scalars_mock = MagicMock()
    scalars_mock.all.return_value = []
    result_mock = MagicMock()
    result_mock.scalars.return_value = scalars_mock
    mock_session.execute = AsyncMock(return_value=result_mock)

    session_factory = MagicMock(return_value=mock_session)

    count = await resume_waiting_runs_once(session_factory, message_service)
    assert count == 0


async def test_resume_waiting_runs_once_matched_response_resumes_run() -> None:
    from syndicateclaw.tasks.agent_response_resume import resume_waiting_runs_once

    response = MagicMock()
    response.conversation_id = "conv-1"
    response.id = "msg-1"
    response.content = "agent reply"

    message_service = AsyncMock()
    message_service.delivered_responses = AsyncMock(return_value=[response])
    message_service.mark_response_consumed = AsyncMock()

    run = MagicMock()
    run.state = {
        "_waiting_agent_response": {
            "conversation_id": "conv-1",
            "timeout_seconds": 300,
            "requested_at": "2024-01-01T00:00:00Z",
            "response_key": "agent_response",
        }
    }
    run.status = "WAITING_AGENT_RESPONSE"

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_begin = AsyncMock()
    mock_begin.__aenter__ = AsyncMock(return_value=None)
    mock_begin.__aexit__ = AsyncMock(return_value=False)
    mock_session.begin = MagicMock(return_value=mock_begin)

    scalars_mock = MagicMock()
    scalars_mock.all.return_value = [run]
    result_mock = MagicMock()
    result_mock.scalars.return_value = scalars_mock
    mock_session.execute = AsyncMock(return_value=result_mock)

    session_factory = MagicMock(return_value=mock_session)

    count = await resume_waiting_runs_once(session_factory, message_service)
    assert count == 1
    assert run.status == "RUNNING"
    assert run.state["agent_response"] == "agent reply"


async def test_resume_waiting_runs_once_timeout_sets_failed() -> None:
    from syndicateclaw.tasks.agent_response_resume import resume_waiting_runs_once

    message_service = AsyncMock()
    message_service.delivered_responses = AsyncMock(return_value=[])

    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    run = MagicMock()
    run.state = {
        "_waiting_agent_response": {
            "conversation_id": "conv-1",
            "timeout_seconds": 60,
            "requested_at": past,
        }
    }
    run.status = "WAITING_AGENT_RESPONSE"

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_begin = AsyncMock()
    mock_begin.__aenter__ = AsyncMock(return_value=None)
    mock_begin.__aexit__ = AsyncMock(return_value=False)
    mock_session.begin = MagicMock(return_value=mock_begin)

    scalars_mock = MagicMock()
    scalars_mock.all.return_value = [run]
    result_mock = MagicMock()
    result_mock.scalars.return_value = scalars_mock
    mock_session.execute = AsyncMock(return_value=result_mock)

    session_factory = MagicMock(return_value=mock_session)

    count = await resume_waiting_runs_once(session_factory, message_service)
    assert count == 0
    assert run.status == "FAILED"


async def test_run_agent_response_resume_loop_calls_once_then_cancels() -> None:
    from syndicateclaw.tasks.agent_response_resume import run_agent_response_resume_loop

    message_service = AsyncMock()
    message_service.delivered_responses = AsyncMock(return_value=[])

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_begin = AsyncMock()
    mock_begin.__aenter__ = AsyncMock(return_value=None)
    mock_begin.__aexit__ = AsyncMock(return_value=False)
    mock_session.begin = MagicMock(return_value=mock_begin)
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = []
    result_mock = MagicMock()
    result_mock.scalars.return_value = scalars_mock
    mock_session.execute = AsyncMock(return_value=result_mock)

    session_factory = MagicMock(return_value=mock_session)

    with (
        patch(
            "syndicateclaw.tasks.agent_response_resume.asyncio.sleep",
            new=AsyncMock(side_effect=asyncio.CancelledError),
        ),
        pytest.raises(asyncio.CancelledError),
    ):
        await run_agent_response_resume_loop(
            session_factory, message_service, poll_interval_seconds=1
        )
