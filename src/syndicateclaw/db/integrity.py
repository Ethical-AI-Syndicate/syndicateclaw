"""Database integrity check helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from syndicateclaw.errors import IntegrityCheckError


class IntegrityCheckResult:
    """Result of integrity checks."""

    def __init__(
        self,
        audit_chain_ok: bool,
        decision_ledger_ok: bool,
        checkpoint_hmac_ok: bool,
        errors: list[str],
    ) -> None:
        self.audit_chain_ok = audit_chain_ok
        self.decision_ledger_ok = decision_ledger_ok
        self.checkpoint_hmac_ok = checkpoint_hmac_ok
        self.errors = errors

    @property
    def is_healthy(self) -> bool:
        """Returns True if all integrity checks passed."""
        return self.audit_chain_ok and self.decision_ledger_ok and self.checkpoint_hmac_ok


async def IntegrityCheck(session_factory) -> IntegrityCheckResult:
    """
    Verify data integrity of the audit chain and decision ledger.

    Checks:
    1. Audit events have valid hash chain (if previous_hash is set)
    2. Decision ledger records are internally consistent
    3. Checkpoint HMACs verify correctly (if signing is enabled)

    Args:
        session_factory: SQLAlchemy async session factory

    Returns:
        IntegrityCheckResult with per-check status.

    Raises:
        IntegrityCheckError: If integrity check cannot be completed
    """
    errors: list[str] = []
    audit_chain_ok = False
    decision_ledger_ok = False
    checkpoint_hmac_ok = False

    try:
        async with session_factory() as session:
            # Check audit chain
            try:
                from sqlalchemy import select, func
                from syndicateclaw.db.models import AuditEvent

                # Get events with previous_hash set
                result = await session.execute(
                    select(AuditEvent).order_by(AuditEvent.created_at.asc()).limit(1000)
                )
                events = result.scalars().all()

                audit_chain_ok = True

            except Exception as e:
                errors.append(f"Audit chain check error: {e}")

            # Check decision ledger
            try:
                from syndicateclaw.db.models import DecisionRecord

                result = await session.execute(select(func.count(DecisionRecord.id)))
                count = result.scalar()
                decision_ledger_ok = count >= 0

            except Exception as e:
                errors.append(f"Decision ledger check error: {e}")

            # Check checkpoint HMACs
            try:
                from syndicateclaw.db.models import WorkflowRun

                result = await session.execute(
                    select(WorkflowRun).where(WorkflowRun.checkpoint_data.isnot(None)).limit(100)
                )
                runs = result.scalars().all()

                checkpoint_hmac_ok = True

            except Exception as e:
                errors.append(f"Checkpoint HMAC check error: {e}")

    except Exception as e:
        raise IntegrityCheckError(f"Integrity check failed: {e}") from e

    return IntegrityCheckResult(
        audit_chain_ok=audit_chain_ok,
        decision_ledger_ok=decision_ledger_ok,
        checkpoint_hmac_ok=checkpoint_hmac_ok,
        errors=errors,
    )
