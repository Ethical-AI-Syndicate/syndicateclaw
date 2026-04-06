"""WorkflowBuilder graph validation."""

from __future__ import annotations

from typing import Any

from syndicateclaw_sdk.exceptions import BuildValidationError


class WorkflowBuilder:
    """Fluent builder for workflow definitions (client-side validation)."""

    def __init__(self) -> None:
        self._nodes: list[dict[str, Any]] = []
        self._edges: list[dict[str, Any]] = []

    def add_node(self, node: dict[str, Any]) -> WorkflowBuilder:
        self._nodes.append(dict(node))
        return self

    def add_edge(self, edge: dict[str, Any]) -> WorkflowBuilder:
        self._edges.append(dict(edge))
        return self

    def build(self) -> dict[str, Any]:
        """Validate and return a definition dict."""
        ids = [n.get("id") for n in self._nodes if n.get("id")]
        if len(ids) != len(set(ids)):
            raise BuildValidationError("Duplicate node ids")
        types_upper = {str(n.get("type", "")).upper() for n in self._nodes}
        if "START" not in types_upper:
            raise BuildValidationError("Graph has no START node")
        if "END" not in types_upper:
            raise BuildValidationError("Graph has no END node")
        for n in self._nodes:
            if str(n.get("type", "")).upper() == "DECISION":
                cfg = n.get("config") or {}
                if not cfg.get("true_branch") or not cfg.get("false_branch"):
                    raise BuildValidationError("DECISION node missing branch")
        return {"nodes": self._nodes, "edges": self._edges}
