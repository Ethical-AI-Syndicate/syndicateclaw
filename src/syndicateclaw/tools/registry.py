from __future__ import annotations

import dataclasses
from collections.abc import Awaitable, Callable
from typing import Any

import structlog

from syndicateclaw.models import Tool, ToolRiskLevel

logger = structlog.get_logger(__name__)


@dataclasses.dataclass(frozen=True)
class ToolDefinition:
    """Pairs a :class:`Tool` metadata model with its async handler callable."""

    tool: Tool
    handler: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class ToolRegistry:
    """Central registry of all available tools.

    Tools must be explicitly registered - no dynamic plugin auto-loading.
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(
        self,
        tool: Tool,
        handler: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
    ) -> None:
        if tool.name in self._tools:
            logger.warning("tool.overwritten", name=tool.name)
        self._tools[tool.name] = ToolDefinition(tool=tool, handler=handler)
        logger.info("tool.registered", name=tool.name, risk=tool.risk_level)

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def list_tools(self, risk_level: ToolRiskLevel | None = None) -> list[Tool]:
        if risk_level is None:
            return [td.tool for td in self._tools.values()]
        return [td.tool for td in self._tools.values() if td.tool.risk_level == risk_level]

    def unregister(self, name: str) -> None:
        removed = self._tools.pop(name, None)
        if removed:
            logger.info("tool.unregistered", name=name)
        else:
            logger.warning("tool.unregister_miss", name=name)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)
