"""Invoke plugin hooks with audit trail and timeouts."""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from syndicateclaw.models import AuditEvent, AuditEventType
from syndicateclaw.plugins.base import Plugin, PluginContext

logger = structlog.get_logger(__name__)


class PluginExecutor:
    def __init__(
        self,
        plugins: list[Plugin],
        *,
        audit_service: Any,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._plugins = plugins
        self._audit = audit_service
        self._timeout = timeout_seconds

    async def invoke_on_node_execute(
        self,
        *,
        run_id: str,
        workflow_id: str,
        actor: str,
        namespace: str,
        state: dict[str, Any],
        node_id: str,
        output_state: dict[str, Any],
    ) -> None:
        ctx = PluginContext(run_id, workflow_id, actor, namespace, state)
        await self.invoke_hook("on_node_execute", ctx, node_id=node_id, result=output_state)

    async def invoke_hook(self, hook_name: str, ctx: PluginContext, **kwargs: Any) -> None:
        for plugin in self._plugins:
            await self._invoke_one(plugin, hook_name, ctx, **kwargs)

    async def _invoke_one(
        self,
        plugin: Plugin,
        hook_name: str,
        ctx: PluginContext,
        **kwargs: Any,
    ) -> None:
        fn = getattr(plugin, hook_name, None)
        if fn is None:
            return
        await self._audit_plugin_event(
            AuditEventType.PLUGIN_HOOK_INVOKED,
            plugin.name,
            hook_name,
            details={"run_id": ctx.run_id},
        )
        try:
            await asyncio.wait_for(fn(ctx, **kwargs), timeout=self._timeout)
        except TimeoutError:
            logger.warning("plugin.hook_timeout", plugin=plugin.name, hook=hook_name)
            await self._audit_plugin_event(
                AuditEventType.PLUGIN_HOOK_TIMEOUT,
                plugin.name,
                hook_name,
                details={"run_id": ctx.run_id},
            )
            return
        except Exception as exc:
            logger.error("plugin.hook_failed", plugin=plugin.name, error=str(exc))
            await self._audit_plugin_event(
                AuditEventType.PLUGIN_HOOK_FAILED,
                plugin.name,
                hook_name,
                details={"run_id": ctx.run_id, "error": str(exc)},
            )
            return
        await self._audit_plugin_event(
            AuditEventType.PLUGIN_HOOK_COMPLETED,
            plugin.name,
            hook_name,
            details={"run_id": ctx.run_id},
        )

    async def _audit_plugin_event(
        self,
        event_type: AuditEventType,
        plugin_name: str,
        hook: str,
        *,
        details: dict[str, Any],
    ) -> None:
        if self._audit is None or not hasattr(self._audit, "emit"):
            return
        event = AuditEvent.new(
            event_type=event_type,
            actor="system:plugins",
            resource_type="plugin",
            resource_id=plugin_name,
            action=hook,
            details=details,
        )
        await self._audit.emit(event)
