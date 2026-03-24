"""Database-backed API key management with lifecycle tracking.

Replaces the static dict-based API key store with a proper lifecycle:
- key creation with hashing (only the hash is stored)
- last-used tracking on every verification
- revocation with actor attribution
- expiration support
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from syndicateclaw.db.models import ApiKey as ApiKeyRow

logger = structlog.get_logger(__name__)

_KEY_PREFIX = "sc-"
_KEY_LENGTH = 32


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


class ApiKeyService:
    """Manages API key lifecycle: create, verify, revoke, expire."""

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._session_factory = session_factory

    async def create_key(
        self,
        actor: str,
        description: str = "",
        expires_at: datetime | None = None,
        created_by: str = "system",
    ) -> tuple[str, str]:
        """Create a new API key. Returns (key_id, raw_key).

        The raw key is returned exactly once — it is not stored.
        Only the SHA-256 hash is persisted.
        """
        raw_key = _KEY_PREFIX + secrets.token_urlsafe(_KEY_LENGTH)
        key_hash = _hash_key(raw_key)
        key_prefix = raw_key[:12]

        async with self._session_factory() as session, session.begin():
            row = ApiKeyRow(
                key_hash=key_hash,
                key_prefix=key_prefix,
                actor=actor,
                description=description,
                expires_at=expires_at,
            )
            session.add(row)
            await session.flush()
            key_id = row.id

        logger.info(
            "api_key.created",
            key_id=key_id,
            actor=actor,
            prefix=key_prefix,
            created_by=created_by,
        )
        return key_id, raw_key

    async def verify_key(self, raw_key: str) -> str | None:
        """Verify an API key. Returns the actor if valid, None if invalid/revoked/expired.

        Updates last_used_at on successful verification.
        """
        key_hash = _hash_key(raw_key)
        now = datetime.now(UTC)

        async with self._session_factory() as session, session.begin():
            stmt = select(ApiKeyRow).where(ApiKeyRow.key_hash == key_hash)
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()

            if row is None:
                return None

            if row.revoked:
                logger.warning("api_key.revoked_key_used", key_prefix=row.key_prefix)
                return None

            if row.expires_at and row.expires_at <= now:
                logger.warning("api_key.expired_key_used", key_prefix=row.key_prefix)
                return None

            row.last_used_at = now
            row.updated_at = now

        return row.actor

    async def revoke_key(self, key_id: str, revoked_by: str) -> bool:
        """Revoke an API key by ID. Returns True if revoked, False if not found."""
        now = datetime.now(UTC)

        async with self._session_factory() as session, session.begin():
            row = await session.get(ApiKeyRow, key_id)
            if row is None:
                return False
            if row.revoked:
                return True

            row.revoked = True
            row.revoked_at = now
            row.revoked_by = revoked_by
            row.updated_at = now

        logger.info("api_key.revoked", key_id=key_id, revoked_by=revoked_by)
        return True

    async def list_keys(self, actor: str | None = None) -> list[dict[str, Any]]:
        """List API keys (without hashes). Optionally filter by actor."""
        async with self._session_factory() as session:
            stmt = select(ApiKeyRow)
            if actor:
                stmt = stmt.where(ApiKeyRow.actor == actor)
            stmt = stmt.order_by(ApiKeyRow.created_at.desc())
            result = await session.execute(stmt)
            rows = result.scalars().all()

            return [
                {
                    "id": r.id,
                    "key_prefix": r.key_prefix,
                    "actor": r.actor,
                    "description": r.description,
                    "revoked": r.revoked,
                    "revoked_at": r.revoked_at.isoformat() if r.revoked_at else None,
                    "last_used_at": r.last_used_at.isoformat() if r.last_used_at else None,
                    "expires_at": r.expires_at.isoformat() if r.expires_at else None,
                    "created_at": r.created_at.isoformat(),
                }
                for r in rows
            ]
