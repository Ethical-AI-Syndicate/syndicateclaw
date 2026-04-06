"""Unit tests for services/organization_service.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from syndicateclaw.services.organization_service import (
    OrganizationService,
    active_nonterminal_runs_for_namespace,
    add_storage_bytes_used,
    count_agents_for_org,
    count_memory_records_for_org,
    count_schedules_for_org,
    count_workflows_for_org,
    derive_namespace,
    get_storage_bytes_used,
)


def _scalar_session(value):
    """Return a mock session where execute().scalar() returns value."""
    result = MagicMock()
    result.scalar.return_value = value
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    return session


def _first_session(row):
    """Return a mock session where execute().first() returns row."""
    result = MagicMock()
    result.first.return_value = row
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    return session


# ---------------------------------------------------------------------------
# derive_namespace (pure)
# ---------------------------------------------------------------------------


def test_derive_namespace_lowercases_and_slugifies() -> None:
    assert derive_namespace("My Org") == "my-org"


def test_derive_namespace_replaces_underscores() -> None:
    assert derive_namespace("my_org_name") == "my-org-name"


def test_derive_namespace_strips_special_chars() -> None:
    assert derive_namespace("Org! @#123") == "org---123"


def test_derive_namespace_fallback_on_empty() -> None:
    assert derive_namespace("!!!!") == "org"


# ---------------------------------------------------------------------------
# OrganizationService.get_by_id
# ---------------------------------------------------------------------------


async def test_get_by_id_returns_org() -> None:
    org = MagicMock()
    session = AsyncMock()
    session.get = AsyncMock(return_value=org)
    svc = OrganizationService(session)
    result = await svc.get_by_id("org-1")
    assert result is org


async def test_get_by_id_returns_none_when_missing() -> None:
    session = AsyncMock()
    session.get = AsyncMock(return_value=None)
    svc = OrganizationService(session)
    assert await svc.get_by_id("missing") is None


# ---------------------------------------------------------------------------
# OrganizationService.get_actor_org
# ---------------------------------------------------------------------------


async def test_get_actor_org_returns_none_when_table_missing() -> None:
    result = MagicMock()
    result.first.return_value = None
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    svc = OrganizationService(session)
    assert await svc.get_actor_org("actor-1") is None


async def test_get_actor_org_returns_none_when_no_membership() -> None:
    # First call (table check) returns a row; second (membership) returns None
    chk_result = MagicMock()
    chk_result.first.return_value = MagicMock()  # table exists
    mem_result = MagicMock()
    mem_result.first.return_value = None  # no membership

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[chk_result, mem_result])
    svc = OrganizationService(session)
    assert await svc.get_actor_org("actor-1") is None


async def test_get_actor_org_returns_org_when_member() -> None:
    chk_result = MagicMock()
    chk_result.first.return_value = MagicMock()

    mem_row = MagicMock()
    mem_row.__getitem__ = MagicMock(return_value="org-1")
    mem_result = MagicMock()
    mem_result.first.return_value = mem_row

    org = MagicMock()
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[chk_result, mem_result])
    session.get = AsyncMock(return_value=org)

    svc = OrganizationService(session)
    result = await svc.get_actor_org("actor-1")
    assert result is org


# ---------------------------------------------------------------------------
# OrganizationService.resolve_actor_permissions
# ---------------------------------------------------------------------------


async def test_resolve_actor_permissions_known_role() -> None:
    row = MagicMock()
    row.__getitem__ = MagicMock(return_value="viewer")
    result = MagicMock()
    result.first.return_value = row
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    svc = OrganizationService(session)
    perms = await svc.resolve_actor_permissions("actor-1")
    assert "org:read" in perms


async def test_resolve_actor_permissions_no_row() -> None:
    result = MagicMock()
    result.first.return_value = None
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    svc = OrganizationService(session)
    perms = await svc.resolve_actor_permissions("actor-1")
    assert perms == set()


# ---------------------------------------------------------------------------
# OrganizationService.create_org
# ---------------------------------------------------------------------------


async def test_create_org_returns_organization() -> None:
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.execute = AsyncMock()
    svc = OrganizationService(session)
    org = await svc.create_org("Test Org", "Test", "owner-1")
    assert org.name == "Test Org"
    assert org.status == "ACTIVE"
    assert org.namespace == "test-org"
    session.add.assert_called_once()
    assert session.flush.await_count == 2


# ---------------------------------------------------------------------------
# OrganizationService.handle_org_deleting
# ---------------------------------------------------------------------------


async def test_handle_org_deleting_does_nothing_if_missing() -> None:
    session = AsyncMock()
    session.get = AsyncMock(return_value=None)
    svc = OrganizationService(session)
    await svc.handle_org_deleting("missing-org")
    session.execute.assert_not_awaited()


async def test_handle_org_deleting_marks_deleting() -> None:
    org = MagicMock()
    org.namespace = "ns-1"
    org.status = "ACTIVE"
    session = AsyncMock()
    session.get = AsyncMock(return_value=org)
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    svc = OrganizationService(session)
    with patch(
        "syndicateclaw.services.organization_service.asyncio.get_running_loop",
        side_effect=RuntimeError,
    ):
        await svc.handle_org_deleting("org-1")
    assert org.status == "DELETING"
    session.flush.assert_awaited_once()


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


async def test_count_workflows_for_org() -> None:
    session = _scalar_session(5)
    assert await count_workflows_for_org(session, "ns") == 5


async def test_count_agents_for_org() -> None:
    session = _scalar_session(3)
    assert await count_agents_for_org(session, "ns") == 3


async def test_count_schedules_for_org() -> None:
    session = _scalar_session(0)
    assert await count_schedules_for_org(session, "ns") == 0


async def test_count_memory_records_for_org() -> None:
    session = _scalar_session(None)
    assert await count_memory_records_for_org(session, "ns") == 0


async def test_get_storage_bytes_used_with_row() -> None:
    row = MagicMock()
    row.__getitem__ = MagicMock(return_value=1024)
    session = _first_session(row)
    assert await get_storage_bytes_used(session, "org-1") == 1024


async def test_get_storage_bytes_used_no_row() -> None:
    session = _first_session(None)
    assert await get_storage_bytes_used(session, "org-1") == 0


async def test_add_storage_bytes_used() -> None:
    session = AsyncMock()
    await add_storage_bytes_used(session, "org-1", 512)
    session.execute.assert_awaited_once()


async def test_active_nonterminal_runs_for_namespace() -> None:
    session = _scalar_session(7)
    assert await active_nonterminal_runs_for_namespace(session, "ns") == 7
