from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class PolicyContext:
    actor: str
    resource_type: str
    resource_id: str
    action: str
    risk_level: str = "low"
    tools: list[str] = field(default_factory=list)
    tenant_id: str | None = None
    session_id: str | None = None
    request_id: str | None = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    extra: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        if hasattr(self, key):
            value = getattr(self, key)
            if value is not None:
                return value
        return self.extra.get(key, default)
