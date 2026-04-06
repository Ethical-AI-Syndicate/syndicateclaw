"""Unit tests for services/subscription_service.py and tasks/org_cleanup.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from syndicateclaw.services.agent_service import AgentNotFoundError, AgentOwnershipError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session_factory(*, scalar_one_or_none=None, scalars_return=None):
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    begin_ctx = AsyncMock()
    begin_ctx.__aenter__ = AsyncMock(return_value=None)
    begin_ctx.__aexit__ = AsyncMock(return_value=False)
    session.begin = MagicMock(return_value=begin_ctx)
    session.add = MagicMock()
    session.flush = AsyncMock()

    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar_one_or_none
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = scalars_return or []
    result.scalars.return_value = scalars_mock
    session.execute = AsyncMock(return_value=result)
    return MagicMock(return_value=session)


# ---------------------------------------------------------------------------
# SubscriptionService._ensure_owner_or_admin
# ---------------------------------------------------------------------------


async def test_ensure_owner_or_admin_owner_passes() -> None:
    from syndicateclaw.services.subscription_service import SubscriptionService

    agent_service = AsyncMock()
    factory = _make_session_factory()
    service = SubscriptionService(factory, agent_service=agent_service)

    agent = MagicMock()
    agent.registered_by = "user:1"
    await service._ensure_owner_or_admin(agent, "user:1")  # no raise


async def test_ensure_owner_or_admin_admin_passes() -> None:
    from syndicateclaw.services.subscription_service import SubscriptionService

    agent_service = AsyncMock()
    agent_service.actor_has_admin_permission = AsyncMock(return_value=True)
    factory = _make_session_factory()
    service = SubscriptionService(factory, agent_service=agent_service)

    agent = MagicMock()
    agent.registered_by = "user:2"
    await service._ensure_owner_or_admin(agent, "user:1")  # no raise


async def test_ensure_owner_or_admin_not_owner_or_admin_raises() -> None:
    from syndicateclaw.services.subscription_service import SubscriptionService

    agent_service = AsyncMock()
    agent_service.actor_has_admin_permission = AsyncMock(return_value=False)
    factory = _make_session_factory()
    service = SubscriptionService(factory, agent_service=agent_service)

    agent = MagicMock()
    agent.registered_by = "user:2"
    with pytest.raises(AgentOwnershipError):
        await service._ensure_owner_or_admin(agent, "user:1")


# ---------------------------------------------------------------------------
# SubscriptionService.subscribe — new subscription created
# ---------------------------------------------------------------------------


async def test_subscribe_creates_new_subscription() -> None:
    from syndicateclaw.services.subscription_service import SubscriptionService

    agent = MagicMock()
    agent.registered_by = "user:1"
    agent.id = "agent-1"
    agent_service = AsyncMock()
    agent_service.get = AsyncMock(return_value=agent)
    agent_service.actor_has_admin_permission = AsyncMock(return_value=False)

    # scalar_one_or_none=None → will create new subscription
    factory = _make_session_factory(scalar_one_or_none=None)
    service = SubscriptionService(factory, agent_service=agent_service)

    result = await service.subscribe("agent-1", "topic:events", "ns-1", "user:1")
    # Returns the new subscription (mocked)
    assert result is not None


async def test_subscribe_returns_existing_subscription() -> None:
    from syndicateclaw.services.subscription_service import SubscriptionService

    agent = MagicMock()
    agent.registered_by = "user:1"
    agent.id = "agent-1"
    agent_service = AsyncMock()
    agent_service.get = AsyncMock(return_value=agent)
    agent_service.actor_has_admin_permission = AsyncMock(return_value=False)

    existing_sub = MagicMock()
    factory = _make_session_factory(scalar_one_or_none=existing_sub)
    service = SubscriptionService(factory, agent_service=agent_service)

    result = await service.subscribe("agent-1", "topic:events", "ns-1", "user:1")
    assert result is existing_sub


# ---------------------------------------------------------------------------
# SubscriptionService.unsubscribe
# ---------------------------------------------------------------------------


async def test_unsubscribe_executes_delete() -> None:
    from syndicateclaw.services.subscription_service import SubscriptionService

    agent = MagicMock()
    agent.registered_by = "user:1"
    agent.id = "agent-1"
    agent_service = AsyncMock()
    agent_service.get = AsyncMock(return_value=agent)
    agent_service.actor_has_admin_permission = AsyncMock(return_value=False)

    factory = _make_session_factory()
    service = SubscriptionService(factory, agent_service=agent_service)

    await service.unsubscribe("agent-1", "topic:events", "user:1")
    # Should complete without raising


# ---------------------------------------------------------------------------
# SubscriptionService.get_agent_or_404
# ---------------------------------------------------------------------------


async def test_get_agent_or_404_found() -> None:
    from syndicateclaw.services.subscription_service import SubscriptionService

    agent = MagicMock()
    agent_service = AsyncMock()
    agent_service.get = AsyncMock(return_value=agent)
    factory = _make_session_factory()
    service = SubscriptionService(factory, agent_service=agent_service)

    result = await service.get_agent_or_404("agent-1")
    assert result is agent


async def test_get_agent_or_404_not_found_raises() -> None:
    from syndicateclaw.services.subscription_service import SubscriptionService

    agent_service = AsyncMock()
    agent_service.get = AsyncMock(side_effect=AgentNotFoundError("not found"))
    factory = _make_session_factory()
    service = SubscriptionService(factory, agent_service=agent_service)

    with pytest.raises(AgentNotFoundError):
        await service.get_agent_or_404("missing-agent")


# ---------------------------------------------------------------------------
# tasks/org_cleanup.py — _cleanup_with_session paths
# ---------------------------------------------------------------------------


async def test_org_cleanup_with_session_org_not_found() -> None:
    from syndicateclaw.tasks.org_cleanup import run_org_cleanup_with_session

    session = AsyncMock()
    session.get = AsyncMock(return_value=None)
    session.execute = AsyncMock()
    session.flush = AsyncMock()

    # Should return early with no error
    await run_org_cleanup_with_session(session, "org-missing")
    session.execute.assert_not_called()


async def test_org_cleanup_with_session_wrong_status() -> None:
    from syndicateclaw.tasks.org_cleanup import run_org_cleanup_with_session

    org = MagicMock()
    org.status = "ACTIVE"
    session = AsyncMock()
    session.get = AsyncMock(return_value=org)
    session.execute = AsyncMock()

    await run_org_cleanup_with_session(session, "org-1")
    session.execute.assert_not_called()


async def test_org_cleanup_with_session_active_runs_waits() -> None:
    from syndicateclaw.tasks.org_cleanup import run_org_cleanup_with_session

    org = MagicMock()
    org.status = "DELETING"
    org.namespace = "ns-1"

    scalar_result = MagicMock()
    scalar_result.scalar.return_value = 5  # 5 active runs

    session = AsyncMock()
    session.get = AsyncMock(return_value=org)
    session.execute = AsyncMock(return_value=scalar_result)
    session.flush = AsyncMock()

    await run_org_cleanup_with_session(session, "org-1")
    # Should not call flush (returns early due to active runs)
    session.flush.assert_not_called()


async def test_org_cleanup_with_session_deletes_when_no_active_runs() -> None:
    from syndicateclaw.tasks.org_cleanup import run_org_cleanup_with_session

    org = MagicMock()
    org.status = "DELETING"
    org.namespace = "ns-1"

    scalar_result = MagicMock()
    scalar_result.scalar.return_value = 0  # no active runs

    session = AsyncMock()
    session.get = AsyncMock(return_value=org)
    session.execute = AsyncMock(return_value=scalar_result)
    session.flush = AsyncMock()

    await run_org_cleanup_with_session(session, "org-1")
    session.flush.assert_awaited_once()
    assert org.status == "DELETED"
