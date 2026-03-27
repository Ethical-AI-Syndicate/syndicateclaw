"""Multi-use builder tokens scoped to a workflow (v1.5.0 visual builder)."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from syndicateclaw.services.streaming_token_service import (
    InvalidTokenError,
    StreamingTokenRepository,
)


@dataclass(frozen=True)
class BuilderToken:
    token: str
    workflow_id: str
    expires_at: datetime


class BuilderTokenService:
    """Issues and validates builder tokens (not single-use — no used_at)."""

    def __init__(
        self,
        repository: StreamingTokenRepository,
        *,
        ttl_seconds: int = 3600,
    ) -> None:
        self._repo = repository
        self._ttl_seconds = ttl_seconds

    async def issue(self, workflow_id: str, actor: str) -> BuilderToken:
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(UTC) + timedelta(seconds=self._ttl_seconds)
        await self._repo.insert(token, None, actor, "builder", workflow_id, expires_at)
        return BuilderToken(token=token, workflow_id=workflow_id, expires_at=expires_at)

    async def validate(self, token: str, workflow_id: str) -> str:
        """Return actor if valid; raises InvalidTokenError otherwise."""
        record = await self._repo.get(token)
        if record is None:
            raise InvalidTokenError("Token not found")
        if record.token_type != "builder":
            raise InvalidTokenError("Wrong token type")
        if record.expires_at < datetime.now(UTC):
            raise InvalidTokenError("Token expired")
        if record.workflow_id != workflow_id:
            raise InvalidTokenError("Token not valid for this workflow")
        return record.actor
