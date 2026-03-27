"""Builder CSRF: require X-Builder-Token on workflow PUT for interactive saves."""

from __future__ import annotations

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from syndicateclaw.services.streaming_token_service import InvalidTokenError

logger = structlog.get_logger(__name__)

_BUILDER_PUT_PREFIX = "/api/v1/workflows/"


class BuilderCSRFMiddleware(BaseHTTPMiddleware):
    """For PUT /api/v1/workflows/{id}, validate X-Builder-Token when enabled."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        settings = getattr(request.app.state, "settings", None)
        if settings is None or not getattr(settings, "builder_enabled", True):
            return await call_next(request)

        if request.method.upper() != "PUT":
            return await call_next(request)

        path = request.url.path
        if not path.startswith(_BUILDER_PUT_PREFIX):
            return await call_next(request)

        # Skip static subpaths like /runs (PUT is only on /{workflow_id})
        rest = path[len(_BUILDER_PUT_PREFIX) :]
        if "/" in rest:
            return await call_next(request)

        workflow_id = rest
        if not workflow_id:
            return await call_next(request)

        header = request.headers.get("X-Builder-Token")
        if not header:
            return JSONResponse(
                status_code=403,
                content={"detail": "Missing X-Builder-Token"},
            )

        svc = getattr(request.app.state, "builder_token_service", None)
        if svc is None:
            logger.error("builder_token.service_missing")
            return JSONResponse(
                status_code=500,
                content={"detail": "Builder token service unavailable"},
            )

        try:
            await svc.validate(header, workflow_id)
        except InvalidTokenError as exc:
            return JSONResponse(status_code=403, content={"detail": str(exc)})

        return await call_next(request)
