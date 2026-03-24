from __future__ import annotations

from typing import Any

import pytest

from syndicateclaw.models import Tool, ToolRiskLevel
from syndicateclaw.tools.registry import ToolDefinition, ToolRegistry


async def _dummy_handler(input_data: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True}


def _make_tool(name: str, risk: ToolRiskLevel = ToolRiskLevel.LOW) -> Tool:
    return Tool.new(name=name, version="1.0", owner="test", risk_level=risk)


class TestToolRegistry:
    def test_tool_registry_register_and_get(self):
        registry = ToolRegistry()
        tool = _make_tool("alpha")
        registry.register(tool, _dummy_handler)

        result = registry.get("alpha")
        assert result is not None
        assert isinstance(result, ToolDefinition)
        assert result.tool.name == "alpha"
        assert result.handler is _dummy_handler

    def test_tool_registry_list_tools(self):
        registry = ToolRegistry()
        registry.register(_make_tool("one"), _dummy_handler)
        registry.register(_make_tool("two"), _dummy_handler)
        registry.register(_make_tool("three"), _dummy_handler)

        tools = registry.list_tools()
        assert len(tools) == 3
        names = {t.name for t in tools}
        assert names == {"one", "two", "three"}

    def test_tool_registry_unregister(self):
        registry = ToolRegistry()
        tool = _make_tool("removable")
        registry.register(tool, _dummy_handler)
        assert "removable" in registry

        registry.unregister("removable")
        assert "removable" not in registry
        assert registry.get("removable") is None

    def test_tool_registry_list_by_risk(self):
        registry = ToolRegistry()
        registry.register(_make_tool("low1", ToolRiskLevel.LOW), _dummy_handler)
        registry.register(_make_tool("low2", ToolRiskLevel.LOW), _dummy_handler)
        registry.register(_make_tool("high1", ToolRiskLevel.HIGH), _dummy_handler)
        registry.register(_make_tool("critical1", ToolRiskLevel.CRITICAL), _dummy_handler)

        low_tools = registry.list_tools(risk_level=ToolRiskLevel.LOW)
        assert len(low_tools) == 2
        assert all(t.risk_level == ToolRiskLevel.LOW for t in low_tools)

        high_tools = registry.list_tools(risk_level=ToolRiskLevel.HIGH)
        assert len(high_tools) == 1
        assert high_tools[0].name == "high1"

        medium_tools = registry.list_tools(risk_level=ToolRiskLevel.MEDIUM)
        assert len(medium_tools) == 0

    def test_tool_registry_len(self):
        registry = ToolRegistry()
        assert len(registry) == 0
        registry.register(_make_tool("x"), _dummy_handler)
        assert len(registry) == 1

    def test_tool_registry_overwrite(self):
        registry = ToolRegistry()
        tool1 = _make_tool("dup")
        tool2 = _make_tool("dup")
        registry.register(tool1, _dummy_handler)
        registry.register(tool2, _dummy_handler)

        assert len(registry) == 1
        assert registry.get("dup") is not None
