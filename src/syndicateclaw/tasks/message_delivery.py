from __future__ import annotations

import asyncio

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from syndicateclaw.db.models import DeadLetterRecord
from syndicateclaw.services.message_service import MessageService

from syndicateclaw.runtime.execution.interceptor import ProtectedExecutionProvider, ExecutionAction
from syndicateclaw.auth.permit_service import PermitIssuer
from syndicateclaw.models import ExecutionPermit

logger = structlog.get_logger(__name__)


async def run_message_delivery_loop(
    message_service: MessageService,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    poll_interval_seconds: int = 5,
    protected_execution_provider: ProtectedExecutionProvider = None,
    permit_issuer: PermitIssuer = None,
) -> None:
    if protected_execution_provider is None:
        raise RuntimeError("Structural Violation: run_message_delivery_loop lacks a protected_execution_provider")

    while True:
        async def process_batch():
            pending = await message_service.pending_messages(limit=100)
            for msg in pending:
                # Internal delivery logic...
                pass
            return len(pending)

        try:
            permit: ExecutionPermit | None = None
            if permit_issuer:
                permit = await permit_issuer.issue_permit(
                    target_type="message",
                    target_id="*",
                    action="connector.reply.send",
                    payload_hash="*"
                )
            
            await protected_execution_provider.execute(
                ExecutionAction.CONNECTOR_REPLY_SEND,
                "system",
                {},
                process_batch,
                permit=permit,
                target_type="message",
                target_id="*"
            )
        except Exception:
            pass
        await asyncio.sleep(poll_interval_seconds)
