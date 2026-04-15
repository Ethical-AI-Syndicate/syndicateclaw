from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from syndicateclaw.db.models import WorkflowRun
from syndicateclaw.services.message_service import MessageService

logger = structlog.get_logger(__name__)


def _parse_requested_at(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


async def resume_waiting_runs_once(
    session_factory: async_sessionmaker[AsyncSession],
    message_service: MessageService,
) -> int:
    responses = await message_service.delivered_responses(limit=200)
    resumed = 0
    async with session_factory() as session, session.begin():
        runs_result = await session.execute(
            select(WorkflowRun).where(WorkflowRun.status == "WAITING_AGENT_RESPONSE")
        )
        waiting_runs = list(runs_result.scalars().all())

        by_conversation: dict[str, Any] = {}
        for response in responses:
            by_conversation[str(response.conversation_id)] = response

        now = datetime.now(UTC)
        for run in waiting_runs:
            wait_ctx = run.state.get("_waiting_agent_response", {})
            if not isinstance(wait_ctx, dict):
                continue

            conversation_id = str(wait_ctx.get("conversation_id", ""))
            if not conversation_id:
                continue

            timeout_seconds = int(wait_ctx.get("timeout_seconds", 300))
            requested_at_raw = str(wait_ctx.get("requested_at", ""))
            requested_at = _parse_requested_at(requested_at_raw)

            matched = by_conversation.get(conversation_id)
            if matched is not None:
                response_key = str(wait_ctx.get("response_key", "agent_response"))
                run.state[response_key] = matched.content
                run.state.pop("_waiting_agent_response", None)
                run.status = "RUNNING"
                await message_service.mark_response_consumed(matched.id)
                resumed += 1
                continue

            if requested_at is None:
                continue
            if requested_at + timedelta(seconds=timeout_seconds) <= now:
                run.status = "FAILED"
                run.error = "WAITING_AGENT_RESPONSE_TIMEOUT"
                run.state.pop("_waiting_agent_response", None)

    return resumed
from syndicateclaw.runtime.execution.interceptor import ProtectedExecutionProvider, ExecutionAction
from syndicateclaw.auth.permit_service import PermitIssuer
from syndicateclaw.models import ExecutionPermit

logger = structlog.get_logger(__name__)


async def run_agent_response_resume_loop(
    session_factory: async_sessionmaker[AsyncSession],
    message_service: MessageService,
    *,
    poll_interval_seconds: int = 5,
    protected_execution_provider: ProtectedExecutionProvider = None,
    permit_issuer: PermitIssuer = None,
) -> None:
    if protected_execution_provider is None:
        raise RuntimeError("Structural Violation: run_agent_response_resume_loop lacks a protected_execution_provider")

    while True:
        try:
            # Phase 6: We must acquire a fresh permit for the background task
            # If no issuer is provided, we can simulate an internal "system" permit for now
            # but structurally it expects one.
            permit: ExecutionPermit | None = None
            if permit_issuer:
                permit = await permit_issuer.issue_permit(
                    target_type="workflow",
                    target_id="*",
                    action="task.resume",
                    payload_hash="*"
                )
            
            resumed = await protected_execution_provider.execute(
                ExecutionAction.TASK_RESUME,
                "system",
                {},
                resume_waiting_runs_once,
                session_factory,
                message_service,
                permit=permit,
                target_type="workflow",
                target_id="*"
            )
            if resumed:
                logger.info("agent_response_resume.resumed", resumed=resumed)
        except Exception:
            logger.warning("agent_response_resume.failed", exc_info=True)
        await asyncio.sleep(poll_interval_seconds)

