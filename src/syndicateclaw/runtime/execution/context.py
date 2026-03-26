"""Execution context passed to skill handlers (tools, limits)."""

from __future__ import annotations

from typing import Any, Protocol

from syndicateclaw.runtime.contracts.common import ToolPolicy
from syndicateclaw.runtime.contracts.skill_manifest import SkillManifest
from syndicateclaw.runtime.contracts.tool import ToolRequest
from syndicateclaw.runtime.errors import ToolNotAuthorizedError


class ToolExecutor(Protocol):
    """Optional adapter — real tool dispatch lives outside the runtime core."""

    def __call__(self, request: ToolRequest) -> dict[str, Any]:
        ...


class ToolInvoker:
    """Deny-by-default tool access based on manifest allow/deny lists."""

    def __init__(
        self,
        manifest: SkillManifest,
        *,
        execution_id: str,
        tools_invoked: list[dict[str, Any]],
        executor: ToolExecutor | None = None,
    ) -> None:
        self._manifest = manifest
        self._execution_id = execution_id
        self._tools_invoked = tools_invoked
        self._executor = executor

    def invoke(
        self,
        *,
        tool_name: str,
        purpose: str,
        arguments: dict[str, Any],
        requested_scope: str | None = None,
        idempotency_key: str | None = None,
        side_effect_expected: bool = False,
    ) -> dict[str, Any]:
        if self._manifest.tool_policy == ToolPolicy.DENY_ALL:
            msg = (
                f"tool {tool_name!r} rejected (manifest tool_policy=deny_all — "
                "explicit no-tool policy)"
            )
            raise ToolNotAuthorizedError(msg)
        if tool_name in self._manifest.denied_tools:
            msg = f"tool {tool_name!r} is denied for skill {self._manifest.skill_id}"
            raise ToolNotAuthorizedError(msg)
        allowed = self._manifest.allowed_tools
        if not allowed:
            msg = (
                f"tool {tool_name!r} rejected (explicit_allowlist with empty list — "
                "deny-by-default; not the same as tool_policy=deny_all)"
            )
            raise ToolNotAuthorizedError(msg)
        if tool_name not in allowed:
            msg = f"tool {tool_name!r} not in allowlist for skill {self._manifest.skill_id}"
            raise ToolNotAuthorizedError(msg)

        req = ToolRequest(
            execution_id=self._execution_id,
            skill_id=self._manifest.skill_id,
            tool_name=tool_name,
            purpose=purpose,
            arguments=arguments,
            requested_scope=requested_scope,
            idempotency_key=idempotency_key,
            side_effect_expected=side_effect_expected,
        )
        self._tools_invoked.append(req.model_dump(mode="json"))
        if self._executor is None:
            return {}
        return self._executor(req)
