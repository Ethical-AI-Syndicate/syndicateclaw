from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from syndicateclaw.services.streaming_token_service import (
    InvalidTokenError,
    StreamingTokenRecord,
    StreamingTokenService,
)


@dataclass
class _FakeRepo:
    records: dict[str, StreamingTokenRecord]

    async def insert(
        self,
        token: str,
        run_id: str | None,
        actor: str,
        token_type: str,
        workflow_id: str | None,
        expires_at: datetime,
    ) -> None:
        self.records[token] = StreamingTokenRecord(
            token=token,
            run_id=run_id,
            actor=actor,
            token_type=token_type,
            workflow_id=workflow_id,
            expires_at=expires_at,
            used_at=None,
        )

    async def get(self, token: str) -> StreamingTokenRecord | None:
        return self.records.get(token)

    async def mark_used(self, token: str) -> None:
        row = self.records[token]
        self.records[token] = StreamingTokenRecord(
            token=row.token,
            run_id=row.run_id,
            actor=row.actor,
            token_type=row.token_type,
            workflow_id=row.workflow_id,
            expires_at=row.expires_at,
            used_at=datetime.now(UTC),
        )


@pytest.mark.asyncio
async def test_streaming_token_single_use() -> None:
    repo = _FakeRepo(records={})
    service = StreamingTokenService(repo, streaming_token_ttl_seconds=300)

    issued = await service.issue(run_id="run-1", actor="alice")
    actor = await service.validate_and_consume(issued.token, "run-1")
    assert actor == "alice"

    with pytest.raises(InvalidTokenError, match="already consumed"):
        await service.validate_and_consume(issued.token, "run-1")


@pytest.mark.asyncio
async def test_streaming_token_scoped_to_run() -> None:
    repo = _FakeRepo(records={})
    service = StreamingTokenService(repo, streaming_token_ttl_seconds=300)

    issued = await service.issue(run_id="run-1", actor="alice")
    with pytest.raises(InvalidTokenError, match="not valid for this run"):
        await service.validate_and_consume(issued.token, "run-2")


@pytest.mark.asyncio
async def test_streaming_token_expired() -> None:
    repo = _FakeRepo(records={})
    token = "expired-token"
    repo.records[token] = StreamingTokenRecord(
        token=token,
        run_id="run-1",
        actor="alice",
        token_type="streaming",
        workflow_id=None,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
        used_at=None,
    )
    service = StreamingTokenService(repo, streaming_token_ttl_seconds=300)

    with pytest.raises(InvalidTokenError, match="expired"):
        await service.validate_and_consume(token, "run-1")


@pytest.mark.asyncio
async def test_streaming_token_wrong_type_rejected() -> None:
    repo = _FakeRepo(records={})
    token = "builder-token"
    repo.records[token] = StreamingTokenRecord(
        token=token,
        run_id="run-1",
        actor="alice",
        token_type="builder",
        workflow_id="wf-1",
        expires_at=datetime.now(UTC) + timedelta(seconds=60),
        used_at=None,
    )
    service = StreamingTokenService(repo, streaming_token_ttl_seconds=300)

    with pytest.raises(InvalidTokenError, match="Wrong token type"):
        await service.validate_and_consume(token, "run-1")
