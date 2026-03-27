from __future__ import annotations

import structlog
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from syndicateclaw.api.dependencies import get_current_actor
from syndicateclaw.authz.evaluator import Decision, RBACEvaluator, resolve_principal_id
from syndicateclaw.authz.route_registry import Scope, get_required_permission

logger = structlog.get_logger(__name__)


class RBACMiddleware(BaseHTTPMiddleware):
    """Route-level RBAC enforcement middleware."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        settings = getattr(request.app.state, "settings", None)
        if settings is None:
            return await call_next(request)

        if not getattr(settings, "rbac_enforcement_enabled", False):
            await self._log_disabled(request)
            return await call_next(request)

        try:
            actor = await get_current_actor(request)
        except HTTPException:
            # Keep auth semantics in route dependencies unchanged.
            return await call_next(request)

        required = get_required_permission(request.method, request.url.path)
        if required == "DENY":
            return JSONResponse({"detail": "Forbidden"}, status_code=403)
        if required is None:
            return await call_next(request)

        session_factory = getattr(request.app.state, "session_factory", None)
        if session_factory is None:
            logger.error("rbac.session_factory_missing", path=request.url.path)
            return JSONResponse({"detail": "Forbidden"}, status_code=403)

        async with session_factory() as session:
            decision = await self._evaluate_permission(session, actor, required)

        if decision == Decision.DENY:
            return JSONResponse({"detail": "Forbidden"}, status_code=403)

        return await call_next(request)

    async def _evaluate_permission(
        self,
        session: AsyncSession,
        actor: str,
        permission: str,
    ) -> Decision:
        principal_id = await resolve_principal_id(session, actor)
        evaluator = RBACEvaluator(session, redis_client=None)
        result = await evaluator.evaluate(
            principal_id=principal_id,
            permission=permission,
            resource_scope=Scope.platform(),
        )
        return result.decision

    async def _log_disabled(self, request: Request) -> None:
        actor = getattr(request.state, "actor", "unknown")
        path = request.url.path
        logger.warning("rbac.enforcement_disabled", actor=actor, path=path)

        settings = getattr(request.app.state, "settings", None)
        environment = "production"
        if settings is not None:
            environment = getattr(settings, "environment", "production")
        if environment.lower() not in {"development", "dev", "test", "testing"}:
            logger.error(
                "rbac.enforcement_disabled_invalid_environment",
                actor=actor,
                path=path,
                environment=environment,
            )
