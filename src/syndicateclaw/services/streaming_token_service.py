from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from syndicateclaw.db.models import StreamingToken as StreamingTokenRow


class InvalidTokenError(Exception):
    """Raised when a streaming token is missing, expired, reused, or mismatched."""


@dataclass(frozen=True)
class StreamingToken:
    token: str
    run_id: str
    expires_at: datetime


@dataclass(frozen=True)
class StreamingTokenRecord:
    token: str
    run_id: str | None
    actor: str
    token_type: str
    workflow_id: str | None
    expires_at: datetime
    used_at: datetime | None


class StreamingTokenRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def insert(
        self,
        token: str,
        run_id: str | None,
        actor: str,
        token_type: str,
        workflow_id: str | None,
        expires_at: datetime,
    ) -> None:
        async with self._session_factory() as session, session.begin():
            row = StreamingTokenRow(
                token=token,
                run_id=run_id,
                actor=actor,
                token_type=token_type,
                workflow_id=workflow_id,
                expires_at=expires_at,
            )
            session.add(row)

    async def get(self, token: str) -> StreamingTokenRecord | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(StreamingTokenRow).where(StreamingTokenRow.token == token)
            )
            row = result.scalar_one_or_none()
            if row is None:
                return None
            return StreamingTokenRecord(
                token=row.token,
                run_id=row.run_id,
                actor=row.actor,
                token_type=row.token_type,
                workflow_id=row.workflow_id,
                expires_at=row.expires_at,
                used_at=row.used_at,
            )

    async def mark_used(self, token: str) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(
                update(StreamingTokenRow)
                .where(StreamingTokenRow.token == token)
                .values(used_at=datetime.now(UTC))
            )


class StreamingTokenService:
    def __init__(
        self,
        repository: StreamingTokenRepository,
        *,
        streaming_token_ttl_seconds: int = 300,
    ) -> None:
        self._repo = repository
        self._ttl_seconds = streaming_token_ttl_seconds

    async def issue(self, run_id: str, actor: str) -> StreamingToken:
        """Issue a single-use streaming token scoped to run_id."""
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(UTC) + timedelta(seconds=self._ttl_seconds)
        await self._repo.insert(token, run_id, actor, "streaming", None, expires_at)
        return StreamingToken(token=token, run_id=run_id, expires_at=expires_at)

    async def validate_and_consume(self, token: str, run_id: str) -> str:
        """Returns actor. Raises InvalidTokenError on any failure."""
        record = await self._repo.get(token)
        if record is None:
            raise InvalidTokenError("Token not found")
        if record.token_type != "streaming":
            raise InvalidTokenError("Wrong token type")
        if record.used_at is not None:
            raise InvalidTokenError("Token already consumed")
        if record.expires_at < datetime.now(UTC):
            raise InvalidTokenError("Token expired")
        if record.run_id != run_id:
            raise InvalidTokenError("Token not valid for this run")
        await self._repo.mark_used(token)
        return record.actor
