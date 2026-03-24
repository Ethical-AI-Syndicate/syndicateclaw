from __future__ import annotations

from syndicateclaw.api.routes.approvals import router as approvals_router
from syndicateclaw.api.routes.audit import router as audit_router
from syndicateclaw.api.routes.memory import router as memory_router
from syndicateclaw.api.routes.policy import router as policy_router
from syndicateclaw.api.routes.tools import router as tools_router
from syndicateclaw.api.routes.workflows import router as workflows_router

ALL_ROUTERS = [
    approvals_router,
    audit_router,
    memory_router,
    policy_router,
    tools_router,
    workflows_router,
]
