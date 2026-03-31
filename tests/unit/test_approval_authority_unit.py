"""Unit tests for approval/authority.py — covers missing lines 64 and 70."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

from syndicateclaw.approval.authority import ApprovalAuthorityResolver
from syndicateclaw.models import ToolRiskLevel


async def test_authority_resolver_fallback_when_no_risk_level_match() -> None:
    # Line 70: non-empty overrides dict with no entry for LOW → hardcoded fallback
    # Note: {} is falsy so `{} or DEFAULT` would use DEFAULT; use a non-empty dict instead
    resolver = ApprovalAuthorityResolver(
        session_factory=None, authority_overrides={ToolRiskLevel.HIGH: ["admin:lead"]}
    )
    result = await resolver.resolve(
        tool_name="some-tool",
        risk_level=ToolRiskLevel.LOW,
        requester="user-a",
    )
    assert result == ["admin:ops", "admin:security"]


async def test_authority_resolver_uses_policy_approvers_when_resolved() -> None:
    # Line 64: when _resolve_from_policy returns a non-empty list, it is used
    resolver = ApprovalAuthorityResolver(session_factory=None)
    with patch.object(
        resolver,
        "_resolve_from_policy",
        new=AsyncMock(return_value=["policy:approver-1", "policy:approver-2"]),
    ):
        result = await resolver.resolve(
            tool_name="privileged-tool",
            risk_level=ToolRiskLevel.HIGH,
            requester="user-b",
        )
    assert "policy:approver-1" in result
    assert "user-b" not in result  # requester always excluded
