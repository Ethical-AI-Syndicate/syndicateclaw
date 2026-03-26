"""Approval authority resolution.

Determines who is eligible to approve a request based on the tool's risk level
and policy rules, rather than allowing the requester to choose their own
approvers. This prevents the "colluding approver" governance loophole.
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from syndicateclaw.models import ToolRiskLevel

logger = structlog.get_logger(__name__)

DEFAULT_APPROVAL_AUTHORITIES: dict[ToolRiskLevel, list[str]] = {
    ToolRiskLevel.LOW: ["admin:ops"],
    ToolRiskLevel.MEDIUM: ["admin:ops", "admin:security"],
    ToolRiskLevel.HIGH: ["admin:security", "admin:lead"],
    ToolRiskLevel.CRITICAL: ["admin:security", "admin:ciso"],
}


class ApprovalAuthorityResolver:
    """Resolves eligible approvers for an approval request.

    Resolution order:
    1. Policy-defined approvers: if a policy rule for the tool specifies
       `approval_authorities` in its conditions/metadata, those are used.
    2. Risk-level defaults: fall back to configured defaults by tool risk level.
    3. System administrators: if no other resolution, requires admin-prefixed actors.

    The requester is always excluded from the resolved set.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        authority_overrides: dict[ToolRiskLevel, list[str]] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._authorities = authority_overrides or DEFAULT_APPROVAL_AUTHORITIES

    async def resolve(
        self,
        *,
        tool_name: str,
        risk_level: ToolRiskLevel,
        requester: str,
        context: dict[str, Any] | None = None,
    ) -> list[str]:
        """Resolve the list of eligible approvers for a request.

        Returns a non-empty list of actor identifiers. The requester is
        always excluded to prevent self-approval chains.
        """
        approvers: list[str] = []

        policy_approvers = await self._resolve_from_policy(tool_name, context or {})
        if policy_approvers:
            approvers = policy_approvers

        if not approvers:
            approvers = list(self._authorities.get(risk_level, []))

        if not approvers:
            approvers = ["admin:ops", "admin:security"]

        approvers = [a for a in approvers if a != requester]

        if not approvers:
            approvers = ["admin:security"]
            logger.warning(
                "approval.authority.fallback",
                tool_name=tool_name,
                risk_level=risk_level.value,
                requester=requester,
                reason="All resolved approvers matched requester; falling back to admin:security",
            )

        logger.info(
            "approval.authority.resolved",
            tool_name=tool_name,
            risk_level=risk_level.value,
            requester=requester,
            approvers=approvers,
        )
        return approvers

    async def _resolve_from_policy(
        self, tool_name: str, context: dict[str, Any]
    ) -> list[str]:
        """Look up policy-defined approvers for this tool.

        Checks for policy rules with resource_type='tool' that contain
        'approval_authorities' in their conditions metadata.
        """
        if self._session_factory is None:
            return []

        try:
            from syndicateclaw.db.repository import PolicyRuleRepository

            async with self._session_factory() as session:
                repo = PolicyRuleRepository(session)
                rules = await repo.get_enabled_by_resource_type("tool")

                for rule in rules:
                    from fnmatch import fnmatch
                    if not fnmatch(tool_name, rule.resource_pattern):
                        continue
                    raw_co: Any = rule.conditions
                    if isinstance(raw_co, list):
                        conditions: list[Any] = raw_co
                    elif isinstance(raw_co, dict):
                        conditions = [raw_co]
                    else:
                        conditions = []
                    for cond in conditions:
                        if isinstance(cond, dict) and cond.get("field") == "approval_authorities":
                            authorities = cond.get("value", [])
                            if isinstance(authorities, list) and authorities:
                                return authorities
        except Exception:
            logger.warning(
                "approval.authority.policy_lookup_failed",
                tool_name=tool_name,
                exc_info=True,
            )

        return []
