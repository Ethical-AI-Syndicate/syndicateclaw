from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


class WaitForApprovalError(Exception):
    """Raised when workflow execution must stop until an approval is granted."""

    def __init__(
        self,
        message: str | None = None,
        *,
        approval_id: str = "",
        tool_name: str = "",
        node_id: str = "",
        run_id: str = "",
        persisted_state: Mapping[str, Any] | None = None,
    ) -> None:
        self.approval_id = approval_id
        self.tool_name = tool_name
        self.node_id = node_id
        self.run_id = run_id
        self.persisted_state = _jsonable(dict(persisted_state or {}))
        super().__init__(message or f"Approval required: {approval_id}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "tool_name": self.tool_name,
            "node_id": self.node_id,
            "run_id": self.run_id,
            "persisted_state": self.persisted_state,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, default=str)

    def with_boundary_context(
        self,
        *,
        approval_id: str,
        tool_name: str,
        node_id: str,
        run_id: str,
        persisted_state: Mapping[str, Any],
    ) -> WaitForApprovalError:
        return WaitForApprovalError(
            str(self),
            approval_id=approval_id,
            tool_name=tool_name,
            node_id=node_id,
            run_id=run_id,
            persisted_state=persisted_state,
        )


class WorkflowCycleDetected(Exception):  # noqa: N818
    """Raised when workflow execution hits a graph cycle or step ceiling."""

    def __init__(
        self,
        message: str | None = None,
        *,
        run_id: str,
        cycle_path: list[str],
        step_count: int,
    ) -> None:
        self.run_id = run_id
        self.cycle_path = _jsonable(cycle_path)
        self.step_count = step_count
        super().__init__(message or f"Workflow execution bound exceeded for run {run_id}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "cycle_path": self.cycle_path,
            "step_count": self.step_count,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, default=str)
