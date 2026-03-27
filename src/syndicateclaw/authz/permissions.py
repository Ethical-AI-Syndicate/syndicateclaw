from __future__ import annotations

PERMISSION_VOCABULARY: frozenset[str] = frozenset(
    {
        "workflow:read",
        "workflow:create",
        "workflow:manage",
        "run:read",
        "run:create",
        "run:control",
        "run:replay",
        "approval:read",
        "approval:decide",
        "approval:manage",
        "policy:read",
        "policy:evaluate",
        "policy:manage",
        "tool:read",
        "tool:execute",
        "tool:manage",
        "memory:read",
        "memory:write",
        "memory:update",
        "memory:delete",
        "memory:manage",
        "audit:read",
        "audit:export",
        "admin:*",
    }
)
