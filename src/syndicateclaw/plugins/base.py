"""Plugin base types and immutable execution context."""

from __future__ import annotations

import copy
import types
from typing import Any


class PluginContext:
    """Sandboxed read-only view of workflow state for plugins."""

    def __init__(
        self,
        run_id: str,
        workflow_id: str,
        actor: str,
        namespace: str,
        state: dict[str, Any],
    ) -> None:
        self._run_id = run_id
        self._workflow_id = workflow_id
        self._actor = actor
        self._namespace = namespace
        self._state_snapshot = copy.deepcopy(state)

    @property
    def state(self) -> types.MappingProxyType[str, Any]:
        return types.MappingProxyType(self._state_snapshot)

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def workflow_id(self) -> str:
        return self._workflow_id

    @property
    def actor(self) -> str:
        return self._actor

    @property
    def namespace(self) -> str:
        return self._namespace


class Plugin:
    """User-defined plugin; subclass and register via entry points."""

    name: str = "unnamed"
    version: str = "0.0.0"

    async def on_workflow_start(self, ctx: PluginContext) -> None:
        return None

    async def on_node_execute(
        self, ctx: PluginContext, node_id: str, result: Any
    ) -> None:
        return None

    async def on_workflow_end(self, ctx: PluginContext, status: str) -> None:
        return None

    async def on_error(self, ctx: PluginContext, error: Exception) -> None:
        return None
