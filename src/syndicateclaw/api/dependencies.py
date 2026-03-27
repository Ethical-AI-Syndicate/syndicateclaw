from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any, cast

import structlog
from fastapi import HTTPException, Request, status
from opentelemetry import trace
from sqlalchemy.ext.asyncio import AsyncSession

from syndicateclaw.config import Settings
from syndicateclaw.security.api_keys import UnscopedApiKeyNotPermittedError
from syndicateclaw.security.auth import JWTError, decode_access_token, verify_api_key
from syndicateclaw.security.revocation import is_token_revoked

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)


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
    return cast(Settings, request.app.state.settings)


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


def get_provider_service(request: Request) -> Any:
    return _get_service(request, "provider_service")


def get_provider_loader(request: Request) -> Any:
    return _get_service(request, "provider_config_loader")


def get_streaming_token_service(request: Request) -> Any:
    return _get_service(request, "streaming_token_service")


def get_agent_service(request: Request) -> Any:
    return _get_service(request, "agent_service")


def get_message_service(request: Request) -> Any:
    return _get_service(request, "message_service")


def get_subscription_service(request: Request) -> Any:
    return _get_service(request, "subscription_service")


def get_versioning_service(request: Request) -> Any:
    return _get_service(request, "versioning_service")


def get_inference_catalog(request: Request) -> Any:
    """In-memory ModelCatalog shared with ProviderService (models.dev merge target)."""
    return _get_service(request, "inference_catalog")


async def get_current_actor(request: Request) -> str:
    """Extract actor identity from JWT bearer token or X-API-Key header.

    Falls back to ``"anonymous"`` during development when no credentials
    are provided.
    """
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.removeprefix("Bearer ").strip()
        try:
            with tracer.start_as_current_span(
                "auth.validate",
                attributes={"auth.method": "jwt"},
            ) as span:
                settings: Settings = request.app.state.settings
                keypair = getattr(request.app.state, "asymmetric_keypair", None)
                public_key = keypair._public_key if keypair else None
                claims = decode_access_token(
                    token,
                    secret_key=settings.secret_key,
                    secondary_secret_key=getattr(settings, "jwt_secondary_secret_key", None),
                    public_key=public_key,
                    audience=getattr(settings, "jwt_audience", None),
                )
                jti = claims.get("jti")
                if jti:
                    redis = getattr(request.app.state, "redis_client", None)
                    if await is_token_revoked(redis, str(jti)):
                        raise HTTPException(
                            status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Token has been revoked",
                        )
                actor = claims.get("sub")
                if not actor:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Token missing 'sub' claim",
                    )
                span.set_attribute("actor.id", str(actor))
                request.state.actor = actor
                return cast(str, actor)
        except JWTError as err:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            ) from err

    api_key = request.headers.get("X-API-Key")
    if api_key:
        with tracer.start_as_current_span(
            "auth.validate",
            attributes={"auth.method": "api_key"},
        ) as span:
            api_key_service = getattr(request.app.state, "api_key_service", None)
            if api_key_service is not None:
                api_key_settings: Settings = request.app.state.settings
                try:
                    verification = await api_key_service.verify_key_details(
                        api_key,
                        allow_unscoped_keys=getattr(api_key_settings, "allow_unscoped_keys", True),
                    )
                except UnscopedApiKeyNotPermittedError as err:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail={
                            "detail": "unscoped_key_not_permitted",
                            "upgrade_guide": "https://docs.syndicateclaw.dev/upgrade/api-key-scopes",
                        },
                    ) from err

                actor = verification.actor if verification is not None else None
                request.state.api_key_scopes = verification.scopes if verification else []
                request.state.unscoped_key = verification.unscoped if verification else False
            else:
                actor = verify_api_key(api_key)
            if actor is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid, revoked, or expired API key",
                )
            span.set_attribute("actor.id", str(actor))
        request.state.actor = actor
        return cast(str, actor)

    app_settings: Settings = request.app.state.settings
    environment = getattr(app_settings, "environment", None) or "production"
    if environment.lower() not in ("development", "dev", "test", "testing"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Provide a Bearer token or X-API-Key header.",
        )

    logger.warning("auth.anonymous_fallback", environment=environment)
    request.state.actor = "anonymous"
    return "anonymous"
