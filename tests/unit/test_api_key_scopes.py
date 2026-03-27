from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syndicateclaw.security.api_keys import (
    ApiKeyService,
    UnscopedApiKeyNotPermittedError,
)


def _session_factory(session: MagicMock) -> MagicMock:
    tx = MagicMock()
    tx.__aenter__ = AsyncMock(return_value=None)
    tx.__aexit__ = AsyncMock(return_value=False)
    session.begin = MagicMock(return_value=tx)

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=cm)


@pytest.mark.asyncio
async def test_create_api_key_rejects_scope_globs() -> None:
    session = MagicMock()
    service = ApiKeyService(_session_factory(session))

    with pytest.raises(ValueError, match="must not include wildcard"):
        await service.create_api_key(actor="user:alice", scopes=["workflow:*"])


@pytest.mark.asyncio
async def test_create_api_key_rejects_unknown_scope() -> None:
    session = MagicMock()
    service = ApiKeyService(_session_factory(session))

    with pytest.raises(ValueError, match="not in vocabulary"):
        await service.create_api_key(actor="user:alice", scopes=["workflow:unknown"])


@pytest.mark.asyncio
async def test_create_api_key_enforces_privilege_ceiling() -> None:
    session = MagicMock()
    service = ApiKeyService(_session_factory(session))
    service._resolve_actor_permissions = AsyncMock(  # type: ignore[method-assign]
        return_value={"workflow:read"}
    )

    with pytest.raises(ValueError, match="privilege ceiling"):
        await service.create_api_key(actor="user:alice", scopes=["workflow:manage"])


@pytest.mark.asyncio
async def test_create_api_key_persists_scopes() -> None:
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    service = ApiKeyService(_session_factory(session))
    service._resolve_actor_permissions = AsyncMock(  # type: ignore[method-assign]
        return_value={"admin:*"}
    )

    with patch("syndicateclaw.security.api_keys.ApiKeyRow") as row_cls:
        row = MagicMock()
        row.id = "key-001"
        row_cls.return_value = row

        key_id, _raw = await service.create_api_key(
            actor="admin:ops",
            scopes=["tool:execute", "workflow:read"],
        )

    assert key_id == "key-001"
    assert row_cls.call_args.kwargs["scopes"] == ["tool:execute", "workflow:read"]


@pytest.mark.asyncio
async def test_verify_key_details_rejects_unscoped_when_disabled() -> None:
    row = MagicMock()
    row.id = "key-001"
    row.actor = "user:bob"
    row.revoked = False
    row.expires_at = None
    row.key_prefix = "sc-xxxx"
    row.scopes = []

    session = MagicMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = row
    session.execute = AsyncMock(return_value=result_mock)

    service = ApiKeyService(_session_factory(session))

    with pytest.raises(UnscopedApiKeyNotPermittedError):
        await service.verify_key_details("sc-test-key", allow_unscoped_keys=False)


@pytest.mark.asyncio
async def test_scopes_endpoint_returns_sorted_vocabulary_and_flag() -> None:
    from syndicateclaw.api.routes.api_keys import list_scopes

    payload = await list_scopes(
        _actor="user:alice",
        settings=SimpleNamespace(allow_unscoped_keys=False),
    )

    assert payload["scopes"] == sorted(payload["scopes"])
    assert payload["unscoped_keys_allowed"] is False
