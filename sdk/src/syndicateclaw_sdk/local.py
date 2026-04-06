"""Local in-memory runtime — not for production."""

from __future__ import annotations

import os
import warnings
from typing import Any


class LocalRuntime:
    """Explicitly unsafe local execution."""

    _PROD_ENVS = frozenset({"production", "prod", "staging"})

    def __init__(self) -> None:
        env = os.environ.get("SYNDICATECLAW_ENVIRONMENT", "production").lower()
        if env in self._PROD_ENVS:
            raise RuntimeError("LocalRuntime cannot be constructed in production environments")
        warnings.warn(
            "LocalRuntime bypasses policy, audit, RBAC, approvals, tool sandbox, and DB persistence.",
            UserWarning,
            stacklevel=2,
        )

    async def run(self, definition: dict[str, Any]) -> dict[str, Any]:
        return {"status": "completed", "definition": definition}
