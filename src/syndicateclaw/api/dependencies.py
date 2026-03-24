from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import structlog
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from syndicateclaw.config import Settings
from syndicateclaw.security.auth import JWTError, decode_access_token, verify_api_key

logger = structlog.get_logger(__name__)


async def get_db_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Yield an async DB session scoped to the request lifecycle."""
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def get_settings(request: Request) -> Settings:
    """Return the Settings singleton stored on app state."""
    return request.app.state.settings


def _get_service(request: Request, attr: str) -> Any:
    svc = getattr(request.app.state, attr, None)
    if svc is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Service {attr!r} is not initialised",
        )
    return svc


def get_audit_service(request: Request) -> Any:
    return _get_service(request, "audit_service")


def get_memory_service(request: Request) -> Any:
    return _get_service(request, "memory_service")


def get_policy_engine(request: Request) -> Any:
    return _get_service(request, "policy_engine")


def get_approval_service(request: Request) -> Any:
    return _get_service(request, "approval_service")


def get_workflow_engine(request: Request) -> Any:
    return _get_service(request, "workflow_engine")


def get_tool_executor(request: Request) -> Any:
    return _get_service(request, "tool_executor")


async def get_current_actor(request: Request) -> str:
    """Extract actor identity from JWT bearer token or X-API-Key header.

    Falls back to ``"anonymous"`` during development when no credentials
    are provided.
    """
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.removeprefix("Bearer ").strip()
        try:
            settings: Settings = request.app.state.settings
            keypair = getattr(request.app.state, "asymmetric_keypair", None)
            public_key = keypair._public_key if keypair else None
            claims = decode_access_token(
                token,
                secret_key=settings.secret_key,
                public_key=public_key,
            )
            actor = claims.get("sub")
            if not actor:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token missing 'sub' claim",
                )
            request.state.actor = actor
            return actor
        except JWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            )

    api_key = request.headers.get("X-API-Key")
    if api_key:
        api_key_service = getattr(request.app.state, "api_key_service", None)
        if api_key_service is not None:
            actor = await api_key_service.verify_key(api_key)
        else:
            actor = verify_api_key(api_key)
        if actor is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid, revoked, or expired API key",
            )
        request.state.actor = actor
        return actor

    settings: Settings = request.app.state.settings
    environment = getattr(settings, "environment", None) or "production"
    if environment.lower() not in ("development", "dev", "test", "testing"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Provide a Bearer token or X-API-Key header.",
        )

    logger.warning("auth.anonymous_fallback", environment=environment)
    request.state.actor = "anonymous"
    return "anonymous"
