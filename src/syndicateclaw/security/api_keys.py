"""Database-backed API key management with lifecycle tracking.

Replaces the static dict-based API key store with a proper lifecycle:
- key creation with hashing (only the hash is stored)
- last-used tracking on every verification
- revocation with actor attribution
- expiration support
"""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from fnmatch import fnmatch
from typing import Any

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from syndicateclaw.authz.evaluator import resolve_principal_id
from syndicateclaw.authz.permissions import PERMISSION_VOCABULARY
from syndicateclaw.db.models import ApiKey as ApiKeyRow

logger = structlog.get_logger(__name__)

_KEY_PREFIX = "sc-"
_KEY_LENGTH = 32
_SCOPE_GLOB_RE = re.compile(r"[\*\?\[\]]")

_ACTOR_PERMISSIONS_SQL = text(
    """
    WITH direct_permissions AS (
        SELECT jsonb_array_elements_text(r.permissions) AS permission
        FROM role_assignments ra
        JOIN roles r ON r.id = ra.role_id
        WHERE ra.principal_id = :principal_id AND ra.revoked = false
    ),
    team_permissions AS (
        SELECT jsonb_array_elements_text(r.permissions) AS permission
        FROM team_memberships tm
        JOIN role_assignments ra ON ra.principal_id = tm.team_id
        JOIN roles r ON r.id = ra.role_id
        WHERE tm.principal_id = :principal_id AND ra.revoked = false
    )
    SELECT DISTINCT permission FROM direct_permissions
    UNION
    SELECT DISTINCT permission FROM team_permissions
    """
)


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


class UnscopedApiKeyNotPermittedError(Exception):
    """Raised when unscoped API keys are disallowed by configuration."""


@dataclass(frozen=True)
class ApiKeyVerificationResult:
    actor: str
    key_id: str
    scopes: list[str]
    unscoped: bool


class ApiKeyService:
    """Manages API key lifecycle: create, verify, revoke, expire."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_api_key(
        self,
        actor: str,
        scopes: list[str] | None = None,
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
            normalized_scopes = await self._validate_scopes(session, actor, scopes)
            row = ApiKeyRow(
                key_hash=key_hash,
                key_prefix=key_prefix,
                actor=actor,
                description=description,
                expires_at=expires_at,
                scopes=normalized_scopes,
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
            scopes_count=len(normalized_scopes),
        )
        return key_id, raw_key

    async def create_key(
        self,
        actor: str,
        description: str = "",
        expires_at: datetime | None = None,
        created_by: str = "system",
    ) -> tuple[str, str]:
        """Backward-compatible wrapper for legacy call sites."""
        return await self.create_api_key(
            actor=actor,
            scopes=None,
            description=description,
            expires_at=expires_at,
            created_by=created_by,
        )

    async def _validate_scopes(
        self,
        session: AsyncSession,
        actor: str,
        scopes: list[str] | None,
    ) -> list[str]:
        if scopes is None:
            return []

        normalized = [scope.strip() for scope in scopes if scope.strip()]
        if len(normalized) > 50:
            raise ValueError("api_key scopes cannot exceed 50 entries")

        if any(_SCOPE_GLOB_RE.search(scope) for scope in normalized):
            raise ValueError("api_key scopes must not include wildcard patterns")

        unknown = [scope for scope in normalized if scope not in PERMISSION_VOCABULARY]
        if unknown:
            raise ValueError(f"api_key scopes not in vocabulary: {unknown}")

        actor_permissions = await self._resolve_actor_permissions(session, actor)
        if "admin:*" in actor_permissions:
            return normalized

        missing = [
            scope
            for scope in normalized
            if not any(fnmatch(scope, actor_perm) for actor_perm in actor_permissions)
        ]
        if missing:
            raise ValueError(f"actor cannot grant scopes above privilege ceiling: {missing}")

        return normalized

    async def _resolve_actor_permissions(self, session: AsyncSession, actor: str) -> set[str]:
        principal_id = await resolve_principal_id(session, actor)
        if principal_id is None:
            return set()

        result = await session.execute(_ACTOR_PERMISSIONS_SQL, {"principal_id": principal_id})
        permissions = {str(row[0]) for row in result.fetchall() if row[0] is not None}
        return permissions

    async def verify_key_details(
        self,
        raw_key: str,
        *,
        allow_unscoped_keys: bool = True,
    ) -> ApiKeyVerificationResult | None:
        """Verify API key and return actor/scopes metadata when valid."""
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

            scopes = list(row.scopes or [])
            unscoped = len(scopes) == 0
            if unscoped:
                logger.warning(
                    "api_key.unscoped",
                    key_id=row.id,
                    actor=row.actor,
                )
                if not allow_unscoped_keys:
                    raise UnscopedApiKeyNotPermittedError

            row.last_used_at = now
            row.updated_at = now

            return ApiKeyVerificationResult(
                actor=row.actor,
                key_id=row.id,
                scopes=scopes,
                unscoped=unscoped,
            )

    async def verify_key(self, raw_key: str) -> str | None:
        """Verify an API key. Returns the actor if valid, None if invalid/revoked/expired.

        Updates last_used_at on successful verification.
        """
        result = await self.verify_key_details(raw_key, allow_unscoped_keys=True)
        if result is None:
            return None
        return result.actor

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
                    "scopes": list(r.scopes or []),
                }
                for r in rows
            ]
