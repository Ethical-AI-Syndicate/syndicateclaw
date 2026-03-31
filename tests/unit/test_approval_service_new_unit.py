"""Unit tests for approval/service.py and approval/authority.py — missing paths."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syndicateclaw.approval.authority import ApprovalAuthorityResolver
from syndicateclaw.approval.service import ApprovalService
from syndicateclaw.models import ApprovalRequest, ApprovalStatus, ToolRiskLevel

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session_factory(repo_get_return=None, scalars_all=None):
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = list(scalars_all or [])

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock(return_value=mock_result)

    mock_begin = AsyncMock()
    mock_begin.__aenter__ = AsyncMock(return_value=None)
    mock_begin.__aexit__ = AsyncMock(return_value=False)
    mock_session.begin = MagicMock(return_value=mock_begin)

    return MagicMock(return_value=mock_session)


def _make_approval_request(**overrides) -> ApprovalRequest:
    defaults: dict[str, Any] = {
        "run_id": "run-test",
        "node_execution_id": "ne-test",
        "requested_by": "user:requester",
        "expires_at": datetime.now(UTC) + timedelta(hours=1),
        "tool_name": "http_request",
        "action_description": "Make external call",
        "risk_level": ToolRiskLevel.LOW,
        "assigned_to": ["admin:ops"],
    }
    defaults.update(overrides)
    return ApprovalRequest.new(**defaults)


def _make_mock_row(
    *,
    status: str = "PENDING",
    requested_by: str = "user:requester",
    assigned_to: list[str] | None = None,
    expires_at: datetime | None = None,
) -> MagicMock:
    row = MagicMock()
    row.id = "req-1"
    row.status = status
    row.requested_by = requested_by
    row.assigned_to = assigned_to or ["admin:ops"]
    row.expires_at = expires_at
    row.run_id = None
    row.node_execution_id = None
    row.tool_name = "http_request"
    row.action_description = "test"
    row.risk_level = "LOW"
    row.context = {}
    return row


# ---------------------------------------------------------------------------
# ApprovalService.request_approval — notification callback
# ---------------------------------------------------------------------------


async def test_request_approval_calls_notification_callback() -> None:
    factory = _make_session_factory()
    notify = AsyncMock()

    with patch("syndicateclaw.approval.service.ApprovalRequestRepository") as MockRepo:
        mock_repo = AsyncMock()
        mock_repo.create = AsyncMock()
        MockRepo.return_value = mock_repo

        with patch("syndicateclaw.approval.service.AuditService") as MockAudit:
            MockAudit.return_value.emit = AsyncMock()

            svc = ApprovalService(factory, notification_callback=notify)
            req = _make_approval_request()
            await svc.request_approval(req, actor="user:requester")

    notify.assert_awaited_once()


async def test_request_approval_notification_failure_is_swallowed() -> None:
    factory = _make_session_factory()
    notify = AsyncMock(side_effect=RuntimeError("smtp down"))

    with patch("syndicateclaw.approval.service.ApprovalRequestRepository") as MockRepo:
        mock_repo = AsyncMock()
        mock_repo.create = AsyncMock()
        MockRepo.return_value = mock_repo

        with patch("syndicateclaw.approval.service.AuditService") as MockAudit:
            MockAudit.return_value.emit = AsyncMock()

            svc = ApprovalService(factory, notification_callback=notify)
            req = _make_approval_request()
            # Should not raise even though notify fails
            await svc.request_approval(req, actor="user:requester")


async def test_request_approval_missing_action_description_raises() -> None:
    factory = _make_session_factory()
    svc = ApprovalService(factory)
    req = _make_approval_request(action_description="")
    with pytest.raises(ValueError, match="action_description"):
        await svc.request_approval(req, actor="user:requester")


async def test_request_approval_no_assigned_to_without_resolver_raises() -> None:
    factory = _make_session_factory()
    svc = ApprovalService(factory)
    req = _make_approval_request(assigned_to=[])
    req.assigned_to = None  # clear it
    with pytest.raises(ValueError, match="assigned_to"):
        await svc.request_approval(req, actor="user:requester")


# ---------------------------------------------------------------------------
# ApprovalService._decide — approve/reject paths
# ---------------------------------------------------------------------------


async def test_approve_raises_if_request_not_found() -> None:
    factory = _make_session_factory()

    with patch("syndicateclaw.approval.service.ApprovalRequestRepository") as MockRepo:
        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=None)
        MockRepo.return_value = mock_repo

        svc = ApprovalService(factory)
        with pytest.raises(ValueError, match="not found"):
            await svc.approve("missing-id", "admin:ops", "ok")


async def test_approve_raises_if_not_pending() -> None:
    factory = _make_session_factory()
    row = _make_mock_row(status="APPROVED")

    with patch("syndicateclaw.approval.service.ApprovalRequestRepository") as MockRepo:
        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=row)
        MockRepo.return_value = mock_repo

        svc = ApprovalService(factory)
        with pytest.raises(ValueError, match="not PENDING"):
            await svc.approve("req-1", "admin:ops", "ok")


async def test_approve_raises_on_self_approval() -> None:
    factory = _make_session_factory()
    row = _make_mock_row(requested_by="admin:ops", assigned_to=["admin:ops"])

    with patch("syndicateclaw.approval.service.ApprovalRequestRepository") as MockRepo:
        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=row)
        MockRepo.return_value = mock_repo

        svc = ApprovalService(factory)
        with pytest.raises(PermissionError, match="Self-approval"):
            await svc.approve("req-1", "admin:ops", "ok")


async def test_approve_raises_if_approver_not_assigned() -> None:
    factory = _make_session_factory()
    row = _make_mock_row(assigned_to=["admin:lead"])

    with patch("syndicateclaw.approval.service.ApprovalRequestRepository") as MockRepo:
        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=row)
        MockRepo.return_value = mock_repo

        svc = ApprovalService(factory)
        with pytest.raises(PermissionError, match="not in the assigned"):
            await svc.approve("req-1", "admin:ops", "ok")


async def test_approve_raises_if_expired() -> None:
    factory = _make_session_factory()
    row = _make_mock_row(
        assigned_to=["admin:ops"],
        expires_at=datetime.now(UTC) - timedelta(hours=1),
    )

    with patch("syndicateclaw.approval.service.ApprovalRequestRepository") as MockRepo:
        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=row)
        mock_repo.update = AsyncMock(return_value=row)
        MockRepo.return_value = mock_repo

        svc = ApprovalService(factory)
        with pytest.raises(ValueError, match="expired"):
            await svc.approve("req-1", "admin:ops", "ok")


async def test_reject_delegates_to_decide() -> None:
    factory = _make_session_factory()
    row = _make_mock_row(assigned_to=["admin:ops"])

    mock_result = MagicMock()
    mock_result.id = "req-1"

    with patch("syndicateclaw.approval.service.ApprovalRequestRepository") as MockRepo:
        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=row)
        mock_repo.update = AsyncMock(return_value=row)
        MockRepo.return_value = mock_repo

        with patch("syndicateclaw.approval.service.AuditService") as MockAudit:
            MockAudit.return_value.emit = AsyncMock()

            with patch("syndicateclaw.approval.service.ApprovalRequest") as MockModel:
                MockModel.model_validate = MagicMock(return_value=mock_result)

                svc = ApprovalService(factory)
                result = await svc.reject("req-1", "admin:ops", "nope")

    assert result is mock_result


# ---------------------------------------------------------------------------
# ApprovalService.expire_stale
# ---------------------------------------------------------------------------


async def test_expire_stale_returns_zero_when_none_expired() -> None:
    factory = _make_session_factory()

    with patch("syndicateclaw.approval.service.ApprovalRequestRepository") as MockRepo:
        mock_repo = AsyncMock()
        mock_repo.get_expired_pending = AsyncMock(return_value=[])
        MockRepo.return_value = mock_repo

        with patch("syndicateclaw.approval.service.AuditService") as MockAudit:
            MockAudit.return_value.emit = AsyncMock()

            svc = ApprovalService(factory)
            count = await svc.expire_stale()

    assert count == 0


async def test_expire_stale_expires_pending_rows() -> None:
    factory = _make_session_factory()
    row = _make_mock_row()

    mock_ar = MagicMock()
    mock_ar.id = "req-1"

    with patch("syndicateclaw.approval.service.ApprovalRequestRepository") as MockRepo:
        mock_repo = AsyncMock()
        mock_repo.get_expired_pending = AsyncMock(return_value=[row])
        mock_repo.update = AsyncMock(return_value=row)
        MockRepo.return_value = mock_repo

        with patch("syndicateclaw.approval.service.AuditService") as MockAudit:
            MockAudit.return_value.emit = AsyncMock()

            with patch("syndicateclaw.approval.service.ApprovalRequest") as MockModel:
                MockModel.model_validate = MagicMock(return_value=mock_ar)

                svc = ApprovalService(factory)
                count = await svc.expire_stale()

    assert count == 1
    assert row.status == ApprovalStatus.EXPIRED.value


# ---------------------------------------------------------------------------
# ApprovalService.get_pending / get_by_run
# ---------------------------------------------------------------------------


async def test_get_pending_with_assignee() -> None:
    factory = _make_session_factory()
    row = _make_mock_row()

    with patch("syndicateclaw.approval.service.ApprovalRequestRepository") as MockRepo:
        mock_repo = AsyncMock()
        mock_repo.get_pending_by_assignee = AsyncMock(return_value=[row])
        MockRepo.return_value = mock_repo

        svc = ApprovalService(factory)
        with patch.object(ApprovalRequest, "model_validate", return_value=MagicMock()):
            results = await svc.get_pending(assignee="admin:ops")

    mock_repo.get_pending_by_assignee.assert_awaited_once_with("admin:ops")
    assert len(results) == 1


async def test_get_pending_without_assignee() -> None:
    factory = _make_session_factory()

    with patch("syndicateclaw.approval.service.ApprovalRequestRepository") as MockRepo:
        mock_repo = AsyncMock()
        mock_repo.get_pending = AsyncMock(return_value=[])
        MockRepo.return_value = mock_repo

        svc = ApprovalService(factory)
        results = await svc.get_pending()

    mock_repo.get_pending.assert_awaited_once()
    assert results == []


async def test_get_by_run() -> None:
    factory = _make_session_factory()

    with patch("syndicateclaw.approval.service.ApprovalRequestRepository") as MockRepo:
        mock_repo = AsyncMock()
        mock_repo.get_by_run = AsyncMock(return_value=[])
        MockRepo.return_value = mock_repo

        svc = ApprovalService(factory)
        results = await svc.get_by_run("run-42")

    mock_repo.get_by_run.assert_awaited_once_with("run-42")
    assert results == []


# ---------------------------------------------------------------------------
# ApprovalAuthorityResolver._resolve_from_policy
# ---------------------------------------------------------------------------


async def test_resolve_from_policy_with_session_matching_rule() -> None:
    # PolicyRuleRepository is imported locally inside _resolve_from_policy,
    # so we patch it at the db.repository level.
    rule = MagicMock()
    rule.resource_pattern = "privileged-*"
    rule.conditions = [{"field": "approval_authorities", "value": ["policy:approver"]}]

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    factory = MagicMock(return_value=mock_session)

    with patch("syndicateclaw.db.repository.PolicyRuleRepository") as MockRepo:
        mock_repo = AsyncMock()
        mock_repo.get_enabled_by_resource_type = AsyncMock(return_value=[rule])
        MockRepo.return_value = mock_repo

        resolver = ApprovalAuthorityResolver(session_factory=factory)
        approvers = await resolver._resolve_from_policy("privileged-tool", {})

    assert "policy:approver" in approvers


async def test_resolve_from_policy_no_match_returns_empty() -> None:
    rule = MagicMock()
    rule.resource_pattern = "other-*"
    rule.conditions = [{"field": "approval_authorities", "value": ["policy:approver"]}]

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    factory = MagicMock(return_value=mock_session)

    with patch("syndicateclaw.db.repository.PolicyRuleRepository") as MockRepo:
        mock_repo = AsyncMock()
        mock_repo.get_enabled_by_resource_type = AsyncMock(return_value=[rule])
        MockRepo.return_value = mock_repo

        resolver = ApprovalAuthorityResolver(session_factory=factory)
        result = await resolver._resolve_from_policy("my-tool", {})

    assert result == []


async def test_resolve_from_policy_exception_returns_empty() -> None:
    factory = MagicMock(side_effect=RuntimeError("db down"))
    resolver = ApprovalAuthorityResolver(session_factory=factory)
    result = await resolver._resolve_from_policy("any-tool", {})
    assert result == []


async def test_resolve_from_policy_no_session_factory_returns_empty() -> None:
    resolver = ApprovalAuthorityResolver(session_factory=None)
    result = await resolver._resolve_from_policy("any-tool", {})
    assert result == []


async def test_resolve_full_fallback_when_all_resolvers_match_requester() -> None:
    """requester == only approver → falls back to admin:security."""
    resolver = ApprovalAuthorityResolver(
        session_factory=None,
        authority_overrides={ToolRiskLevel.LOW: ["user:a"]},
    )
    approvers = await resolver.resolve(
        tool_name="tool", risk_level=ToolRiskLevel.LOW, requester="user:a"
    )
    assert approvers == ["admin:security"]
