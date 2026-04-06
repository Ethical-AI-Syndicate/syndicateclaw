"""Optional extra logging hook points."""

from __future__ import annotations

from syndicateclaw.plugins.base import Plugin, PluginContext


class AuditTrailPlugin(Plugin):
    name = "audit_trail"
    version = "1.0.0"

    async def on_node_execute(self, ctx: PluginContext, node_id: str, result: object) -> None:
        return None
