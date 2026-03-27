"""RBAC middleware (shadow or enforcement).

By default runs RBAC after the response, compares to legacy, and records
disagreements. When ``Settings.rbac_enforcement_enabled`` is True, RBAC may
deny before the route runs (403).
"""

from __future__ import annotations

import contextlib
import json
import time
from typing import Any

import structlog
from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Match

from syndicateclaw.authz.evaluator import (
    AuthzResult,
    Decision,
    RBACEvaluator,
    TeamContextValidator,
    resolve_principal_id,
)
from syndicateclaw.authz.route_registry import (
    SCOPE_RESOLVERS,
    RouteAuthzSpec,
    get_route_spec,
    is_exempt_route,
    is_public_route,
)

logger = structlog.get_logger(__name__)

POLICY_ADMIN_PREFIXES = ("admin:", "policy:", "system:")


class DisagreementType:
    LEGACY_ALLOW_RBAC_DENY = "LEGACY_ALLOW_RBAC_DENY"
    LEGACY_DENY_RBAC_ALLOW = "LEGACY_DENY_RBAC_ALLOW"
    SCOPE_RESOLUTION_FAILED = "SCOPE_RESOLUTION_FAILED"
    TEAM_CONTEXT_MISSING = "TEAM_CONTEXT_MISSING"
    TEAM_CONTEXT_INVALID = "TEAM_CONTEXT_INVALID"
    ROUTE_UNREGISTERED = "ROUTE_UNREGISTERED"
    CACHE_ERROR_FALLBACK = "CACHE_ERROR_FALLBACK"
    PRINCIPAL_NOT_FOUND = "PRINCIPAL_NOT_FOUND"


class ShadowRBACMiddleware(BaseHTTPMiddleware):
    """Middleware that runs RBAC evaluation in shadow mode.

    Attaches to every request. After the response is produced by the legacy
    code path, performs RBAC evaluation and records the comparison.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        blocked = await self._enforce_rbac_if_enabled(request)
        if blocked is not None:
            return blocked
        try:
            response = await call_next(request)
        except Exception:
            # Handler error (e.g. ResponseValidationError) — BaseHTTPMiddleware
            # may propagate instead of returning a 500. Re-raise after attempting
            # shadow evaluation with a synthetic 500 response.
            response = Response(status_code=500)
            await self._try_shadow(request, response)
            raise

        await self._try_shadow(request, response)
        return response

    async def _enforce_rbac_if_enabled(self, request: Request) -> Response | None:
        """When ``rbac_enforcement_enabled``, deny before the handler if RBAC says DENY."""
        settings = getattr(request.app.state, "settings", None)
        if settings is None or not getattr(settings, "rbac_enforcement_enabled", False):
            return None
        actor = getattr(request.state, "actor", None)
        if actor is None or actor == "anonymous":
            return None
        route_path = self._resolve_route_template(request)
        method = request.method.upper()
        if is_public_route(method, route_path):
            return None
        if is_exempt_route(method, route_path):
            return None
        spec = get_route_spec(method, route_path)
        if spec is None:
            return None
        session_factory = getattr(request.app.state, "session_factory", None)
        if session_factory is None:
            return None
        team_context = request.headers.get("X-Team-Context")
        async with session_factory() as session:
            principal_id = await resolve_principal_id(session, actor)
            if principal_id is None:
                logger.warning("rbac.enforce.principal_not_found", actor=actor, path=route_path)
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Forbidden", "reason": "principal_not_found"},
                )
            validator = TeamContextValidator(session)
            tc_valid, tc_error = await validator.validate(principal_id, team_context)
            resolver_fn = SCOPE_RESOLVERS.get(spec.scope_resolver)
            resource_scope = None
            scope_failed = False
            if resolver_fn is not None:
                try:
                    resource_scope = await resolver_fn(request, session)
                except Exception:
                    logger.warning("rbac.enforce.scope_resolution_error", exc_info=True)
                    scope_failed = True
            if scope_failed:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Forbidden", "reason": "scope_resolution_failed"},
                )
            if not tc_valid and tc_error == "principal_has_multiple_teams":
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Forbidden", "reason": "team_context_required"},
                )
            if not tc_valid and tc_error == "team_not_in_memberships":
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Forbidden", "reason": "invalid_team_context"},
                )
            redis_client = getattr(request.app.state, "redis_client", None)
            evaluator = RBACEvaluator(session, redis_client=redis_client)
            rbac_result = await evaluator.evaluate(principal_id, spec.permission, resource_scope)
            if rbac_result.decision == Decision.DENY:
                logger.warning(
                    "rbac.enforce.deny",
                    actor=actor,
                    path=route_path,
                    permission=spec.permission,
                )
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Forbidden", "reason": "rbac_deny"},
                )
        return None

    async def _try_shadow(self, request: Request, response: Response) -> None:
        """Attempt shadow evaluation if the request is authenticated and non-public."""
        actor = getattr(request.state, "actor", None)
        if actor is None or actor == "anonymous":
            return

        route_path = self._resolve_route_template(request)
        method = request.method.upper()

        if is_public_route(method, route_path):
            return
        if is_exempt_route(method, route_path):
            return

        await self._incr_metric(request, "rbac.shadow.expected")

        try:
            await self._shadow_evaluate(request, response, method, route_path, actor)
        except Exception as exc:
            logger.warning(
                "rbac.shadow.evaluation_error",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            await self._incr_metric(request, "rbac.shadow.dropped")

    async def _shadow_evaluate(
        self,
        request: Request,
        response: Response,
        method: str,
        route_path: str,
        actor: str,
    ) -> None:
        """Run full shadow evaluation and record the result."""
        t0 = time.monotonic()
        request_id = getattr(request.state, "request_id", None)
        team_context = request.headers.get("X-Team-Context")

        # Step 1: Look up route spec
        spec = get_route_spec(method, route_path)
        if spec is None:
            await self._record_evaluation(
                request=request,
                request_id=request_id,
                route_name=route_path,
                method=method,
                path=str(request.url.path),
                actor=actor,
                principal_id=None,
                team_context=team_context,
                team_context_valid=None,
                required_permission=None,
                resolved_scope_type=None,
                resolved_scope_id=None,
                rbac_result=None,
                legacy_decision=Decision.ALLOW,
                legacy_deny_reason=None,
                disagreement_type=DisagreementType.ROUTE_UNREGISTERED,
                evaluation_latency_us=_elapsed_us(t0),
            )
            return

        session_factory = getattr(request.app.state, "session_factory", None)
        if session_factory is None:
            return

        async with session_factory() as session:
            # Step 2: Resolve principal
            principal_id = await resolve_principal_id(session, actor)
            if principal_id is None:
                await self._record_evaluation(
                    request=request,
                    request_id=request_id,
                    route_name=route_path,
                    method=method,
                    path=str(request.url.path),
                    actor=actor,
                    principal_id=None,
                    team_context=team_context,
                    team_context_valid=None,
                    required_permission=spec.permission,
                    resolved_scope_type=None,
                    resolved_scope_id=None,
                    rbac_result=AuthzResult(decision=Decision.DENY),
                    legacy_decision=self._evaluate_legacy(spec, actor, response),
                    legacy_deny_reason=None,
                    disagreement_type=DisagreementType.PRINCIPAL_NOT_FOUND,
                    evaluation_latency_us=_elapsed_us(t0),
                )
                return

            # Step 3: Validate team context
            validator = TeamContextValidator(session)
            tc_valid, tc_error = await validator.validate(principal_id, team_context)

            # Step 4: Resolve resource scope
            resolver_fn = SCOPE_RESOLVERS.get(spec.scope_resolver)
            resource_scope = None
            scope_failed = False
            if resolver_fn is not None:
                try:
                    resource_scope = await resolver_fn(request, session)
                except Exception:
                    logger.warning("rbac.shadow.scope_resolution_error", exc_info=True)
                    scope_failed = True

            # Step 5: Run RBAC evaluator
            redis_client = getattr(request.app.state, "redis_client", None)
            evaluator = RBACEvaluator(session, redis_client=redis_client)
            rbac_result = await evaluator.evaluate(principal_id, spec.permission, resource_scope)

            # Step 6: Determine legacy decision
            legacy_decision = self._evaluate_legacy(spec, actor, response)
            legacy_deny_reason = None
            if legacy_decision == Decision.DENY:
                legacy_deny_reason = self._legacy_deny_reason(spec, actor, response)

            # Step 7: Classify disagreement
            agreement = rbac_result.decision == legacy_decision
            disagreement_type = None

            if not agreement:
                if legacy_decision == Decision.ALLOW and rbac_result.decision == Decision.DENY:
                    disagreement_type = DisagreementType.LEGACY_ALLOW_RBAC_DENY
                elif legacy_decision == Decision.DENY and rbac_result.decision == Decision.ALLOW:
                    disagreement_type = DisagreementType.LEGACY_DENY_RBAC_ALLOW

            if scope_failed:
                disagreement_type = DisagreementType.SCOPE_RESOLUTION_FAILED
                agreement = False
            elif not tc_valid and tc_error == "principal_has_multiple_teams":
                disagreement_type = DisagreementType.TEAM_CONTEXT_MISSING
                agreement = False
            elif not tc_valid and tc_error == "team_not_in_memberships":
                disagreement_type = DisagreementType.TEAM_CONTEXT_INVALID
                agreement = False

            await self._record_evaluation(
                request=request,
                request_id=request_id,
                route_name=route_path,
                method=method,
                path=str(request.url.path),
                actor=actor,
                principal_id=principal_id,
                team_context=team_context,
                team_context_valid=tc_valid,
                required_permission=spec.permission,
                resolved_scope_type=resource_scope.scope_type if resource_scope else None,
                resolved_scope_id=resource_scope.scope_id if resource_scope else None,
                rbac_result=rbac_result,
                legacy_decision=legacy_decision,
                legacy_deny_reason=legacy_deny_reason,
                disagreement_type=disagreement_type,
                evaluation_latency_us=rbac_result.evaluation_latency_us,
            )

    def _evaluate_legacy(
        self,
        spec: RouteAuthzSpec,
        actor: str,
        response: Response,
    ) -> Decision:
        """Determine what the legacy authorization system decided.

        Only classifies as DENY when the response indicates an actual
        authorization rejection (403, or 404 on ownership-guarded routes).
        Other error codes (404 for missing resources, 409, 422, 500) are
        NOT authorization decisions.
        """
        if response.status_code == 403:
            return Decision.DENY

        if spec.legacy_check == "prefix_admin":
            if not any(actor.startswith(p) for p in POLICY_ADMIN_PREFIXES):
                return Decision.DENY
            return Decision.ALLOW

        if response.status_code == 404 and spec.owner_field is not None:
            return Decision.DENY

        return Decision.ALLOW

    def _legacy_deny_reason(
        self,
        spec: RouteAuthzSpec,
        actor: str,
        response: Response,
    ) -> str:
        if response.status_code == 403:
            return "handler returned 403"
        if spec.legacy_check == "prefix_admin":
            return f"actor '{actor}' lacks admin prefix"
        if response.status_code == 404 and spec.owner_field:
            return f"ownership check failed ({spec.owner_field})"
        return f"HTTP {response.status_code}"

    def _resolve_route_template(self, request: Request) -> str:
        """Resolve the FastAPI route template path for this request.

        Returns the parameterized path (e.g. "/api/v1/workflows/{workflow_id}")
        rather than the concrete path (e.g. "/api/v1/workflows/wf-001").

        Prefers static path matches over parameterized ones to avoid
        "/api/v1/workflows/runs" matching as "/api/v1/workflows/{workflow_id}".
        """
        app = request.app
        candidates = []
        for route in app.routes:
            match, _ = route.matches(request.scope)
            if match == Match.FULL:
                path = getattr(route, "path", None)
                if path:
                    candidates.append(path)
        if not candidates:
            return str(request.url.path)
        # Prefer the route with fewest path parameters (most static segments)
        candidates.sort(key=lambda p: p.count("{"))
        return str(candidates[0])

    async def _record_evaluation(
        self,
        request: Request,
        request_id: str | None,
        route_name: str,
        method: str,
        path: str,
        actor: str,
        principal_id: str | None,
        team_context: str | None,
        team_context_valid: bool | None,
        required_permission: str | None,
        resolved_scope_type: str | None,
        resolved_scope_id: str | None,
        rbac_result: AuthzResult | None,
        legacy_decision: Decision,
        legacy_deny_reason: str | None,
        disagreement_type: str | None,
        evaluation_latency_us: int,
    ) -> None:
        """Write shadow evaluation record to DB and emit metrics."""
        agreement = disagreement_type is None

        log_data: dict[str, Any] = {
            "route": route_name,
            "method": method,
            "actor": actor,
            "principal_id": principal_id,
            "permission": required_permission,
            "rbac_decision": rbac_result.decision.value if rbac_result else None,
            "legacy_decision": (
                legacy_decision.value
                if isinstance(legacy_decision, Decision)
                else legacy_decision
            ),
            "agreement": agreement,
            "disagreement_type": disagreement_type,
            "cache_hit": rbac_result.cache_hit if rbac_result else False,
            "latency_us": evaluation_latency_us,
        }

        if agreement:
            logger.debug("rbac.shadow.agree", **log_data)
        else:
            logger.warning("rbac.shadow.disagree", **log_data)

        # Persist to shadow_evaluations table
        session_factory = getattr(request.app.state, "session_factory", None)
        if session_factory is None:
            return

        try:
            async with session_factory() as session, session.begin():
                from ulid import ULID

                await session.execute(
                    text("""
                        INSERT INTO shadow_evaluations (
                            id, request_id, route_name, http_method, path,
                            actor, principal_id, team_context, team_context_valid,
                            required_permission, resolved_scope_type, resolved_scope_id,
                            rbac_decision, rbac_deny_reason,
                            rbac_matched_assignments, rbac_matched_denies,
                            rbac_permission_source,
                            legacy_decision, legacy_deny_reason,
                            agreement, disagreement_type,
                            cache_hit, evaluation_latency_us
                        ) VALUES (
                            :id, :request_id, :route_name, :method, :path,
                            :actor, :principal_id, :team_context, :tc_valid,
                            :permission, :scope_type, :scope_id,
                            :rbac_decision, :rbac_deny_reason,
                            CAST(:rbac_assignments AS jsonb), CAST(:rbac_denies AS jsonb),
                            :rbac_perm_source,
                            :legacy_decision, :legacy_deny_reason,
                            :agreement, :disagreement_type,
                            :cache_hit, :latency_us
                        )
                    """),
                    {
                        "id": str(ULID()),
                        "request_id": request_id,
                        "route_name": route_name,
                        "method": method,
                        "path": path,
                        "actor": actor,
                        "principal_id": principal_id,
                        "team_context": team_context,
                        "tc_valid": team_context_valid,
                        "permission": required_permission,
                        "scope_type": resolved_scope_type,
                        "scope_id": resolved_scope_id,
                        "rbac_decision": rbac_result.decision.value if rbac_result else None,
                        "rbac_deny_reason": (
                            rbac_result.deny_reason.value
                            if rbac_result and rbac_result.deny_reason
                            else None
                        ),
                        "rbac_assignments": _serialize_assignments(rbac_result),
                        "rbac_denies": _serialize_denies(rbac_result),
                        "rbac_perm_source": rbac_result.permission_source if rbac_result else None,
                        "legacy_decision": (
                            legacy_decision.value
                            if isinstance(legacy_decision, Decision)
                            else str(legacy_decision)
                        ),
                        "legacy_deny_reason": legacy_deny_reason,
                        "agreement": agreement,
                        "disagreement_type": disagreement_type,
                        "cache_hit": rbac_result.cache_hit if rbac_result else False,
                        "latency_us": evaluation_latency_us,
                    },
                )
            # Record persisted successfully — increment completeness counter
            await self._incr_metric(request, "rbac.shadow.persisted")
        except Exception:
            logger.warning("rbac.shadow.record_write_failed", exc_info=True)
            await self._incr_metric(request, "rbac.shadow.dropped")

        # Emit metrics to Redis counters
        await self._emit_metrics(request, agreement, disagreement_type, rbac_result)

    async def _emit_metrics(
        self,
        request: Request,
        agreement: bool,
        disagreement_type: str | None,
        rbac_result: AuthzResult | None,
    ) -> None:
        """Increment Redis counters for dashboard metrics."""
        redis = getattr(request.app.state, "redis_client", None)
        if redis is None:
            return
        try:
            pipe = redis.pipeline()
            pipe.incr("rbac.shadow.total")
            if agreement:
                pipe.incr("rbac.shadow.agree")
            else:
                pipe.incr("rbac.shadow.disagree")
                if disagreement_type:
                    pipe.incr(f"rbac.shadow.disagree.{disagreement_type}")
                    if disagreement_type == DisagreementType.LEGACY_ALLOW_RBAC_DENY:
                        pipe.incr("rbac.shadow.rbac_stricter")
                    elif disagreement_type == DisagreementType.LEGACY_DENY_RBAC_ALLOW:
                        pipe.incr("rbac.shadow.legacy_stricter")
            if rbac_result:
                if rbac_result.cache_hit:
                    pipe.incr("rbac.shadow.cache_hit")
                else:
                    pipe.incr("rbac.shadow.cache_miss")
            await pipe.execute()
        except Exception:
            logger.debug("rbac.shadow.metrics_error", exc_info=True)

    @staticmethod
    async def _incr_metric(request: Request, key: str) -> None:
        """Increment a single Redis counter. Best-effort, never raises."""
        redis = getattr(request.app.state, "redis_client", None)
        if redis is None:
            return
        with contextlib.suppress(Exception):
            await redis.incr(key)


def _serialize_assignments(result: AuthzResult | None) -> str:
    if result is None:
        return "[]"
    return json.dumps([a.to_dict() for a in result.matched_assignments])


def _serialize_denies(result: AuthzResult | None) -> str:
    if result is None:
        return "[]"
    return json.dumps([d.to_dict() for d in result.matched_denies])


def _elapsed_us(t0: float) -> int:
    return int((time.monotonic() - t0) * 1_000_000)
