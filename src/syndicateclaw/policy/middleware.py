from __future__ import annotations

from typing import Any

try:
    from fastapi import Request
    from starlette.middleware.base import BaseHTTPMiddleware

    _HAS_FASTAPI = True
except ImportError:
    _HAS_FASTAPI = False

from syndicateclaw.models import PolicyDecision
from syndicateclaw.policy.models import PolicyContext


class PolicyEvaluationMiddleware:
    _skip_paths = {"/healthz", "/readyz", "/api/v1/info"}

    def __init__(
        self,
        app: Any,
        policy_scope: dict[str, str] | None = None,
    ) -> None:
        self._app = app
        self._scope = policy_scope or {}

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in self._skip_paths:
            await self._app(scope, receive, send)
            return

        resource_type = self._get_resource_type(path)
        if resource_type is None:
            await self._app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        method = scope.get("method", "GET")

        actor = self._get_actor_from_scope(scope)
        tenant_id = self._get_tenant_from_scope(scope)

        context = PolicyContext(
            actor=actor,
            resource_type=resource_type,
            resource_id=self._extract_resource_id(path),
            action=self._method_to_action(method),
            tenant_id=tenant_id,
        )

        try:
            decision = await self._evaluate(context)
            if decision.is_denied:
                await self._send_denial_response(scope, receive, send, decision)
                return
            if decision.requires_approval:
                await self._send_approval_response(scope, receive, send, decision)
                return
        except Exception:
            await self._send_error_response(scope, receive, send)
            return

        await self._app(scope, receive, send)

    async def _evaluate(self, context: PolicyContext) -> PolicyDecision:
        return PolicyDecision.new(
            rule_id="__middleware_skip__",
            rule_name="middleware_skip",
            effect=PolicyDecision.effect.field.default,
            resource_type=context.resource_type,
            resource_id=context.resource_id,
            actor=context.actor,
            reason="Middleware passthrough — actual evaluation done by PolicyEngine",
            conditions_evaluated=[],
            policy_version="policy-v1",
        )

    def _get_resource_type(self, path: str) -> str | None:
        for prefix, resource_type in self._scope.items():
            if path.startswith(prefix):
                return resource_type
        return None

    def _get_actor_from_scope(self, scope: dict[str, Any]) -> str:
        auth_headers = [v for k, v in scope.get("headers", []) if k == b"authorization"]
        if auth_headers:
            return "authenticated"
        return "anonymous"

    def _get_tenant_from_scope(self, scope: dict[str, Any]) -> str | None:
        return None

    def _extract_resource_id(self, path: str) -> str:
        parts = path.strip("/").split("/")
        if len(parts) >= 4 and parts[0] == "api":
            return parts[-1] if parts[-1] else parts[-2]
        return "*"

    def _method_to_action(self, method: str) -> str:
        mapping = {
            "GET": "read",
            "POST": "create",
            "PUT": "update",
            "PATCH": "update",
            "DELETE": "delete",
        }
        return mapping.get(method, "execute")

    async def _send_denial_response(
        self,
        scope: dict[str, Any],
        receive: Any,
        send: Any,
        decision: PolicyDecision,
    ) -> None:
        body = (
            b'{"error":{"code":"POLICY_DENIED","message":"'
            + decision.reason.encode()
            + b'","rule":"'
            + decision.rule_name.encode()
            + b'"}}'
        )
        await send(
            {
                "type": "http.response.start",
                "status": 403,
                "headers": [[b"content-type", b"application/json"]],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def _send_approval_response(
        self,
        scope: dict[str, Any],
        receive: Any,
        send: Any,
        decision: PolicyDecision,
    ) -> None:
        body = (
            b'{"error":{"code":"APPROVAL_REQUIRED","message":"'
            + decision.reason.encode()
            + b'","rule":"'
            + decision.rule_name.encode()
            + b'","approval_required":true}}'
        )
        await send(
            {
                "type": "http.response.start",
                "status": 403,
                "headers": [[b"content-type", b"application/json"]],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def _send_error_response(
        self,
        scope: dict[str, Any],
        receive: Any,
        send: Any,
    ) -> None:
        body = b'{"error":{"code":"POLICY_ERROR","message":"Policy evaluation failed"}}'
        await send(
            {
                "type": "http.response.start",
                "status": 500,
                "headers": [[b"content-type", b"application/json"]],
            }
        )
        await send({"type": "http.response.body", "body": body})
