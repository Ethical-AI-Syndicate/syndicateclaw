from __future__ import annotations

import hashlib
import json
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from syndicateclaw.db.models import DecisionRecord as DecisionRecordRow
from syndicateclaw.db.repository import DecisionRecordRepository
from syndicateclaw.models import DecisionDomain, DecisionRecord

logger = structlog.get_logger(__name__)


def _hash_inputs(inputs: dict[str, Any]) -> str:
    """SHA-256 of canonical JSON for integrity verification."""
    canonical = json.dumps(inputs, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


class DecisionLedger:
    """Append-only structured decision ledger.

    Every policy evaluation, tool invocation, memory write, and approval
    produces a DecisionRecord that captures:
    - What inputs were considered
    - Which rules were evaluated (ALL of them, not just the match)
    - Why the outcome was reached
    - What side effects resulted
    - A content hash for tamper detection
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        signing_key: bytes | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._signing_key = signing_key

    async def record(
        self,
        *,
        domain: DecisionDomain,
        decision_type: str,
        actor: str,
        inputs: dict[str, Any],
        rules_evaluated: list[dict[str, Any]],
        matched_rule: str | None,
        effect: str,
        justification: str,
        run_id: str | None = None,
        node_execution_id: str | None = None,
        confidence: float = 1.0,
        side_effects: list[str] | None = None,
        trace_id: str | None = None,
    ) -> DecisionRecord:
        """Record a structured decision. This is append-only — no updates."""

        context_hash = _hash_inputs(inputs)

        decision = DecisionRecord.new(
            domain=domain,
            decision_type=decision_type,
            actor=actor,
            run_id=run_id,
            node_execution_id=node_execution_id,
            inputs=inputs,
            rules_evaluated=rules_evaluated,
            matched_rule=matched_rule,
            effect=effect,
            justification=justification,
            confidence=confidence,
            side_effects=side_effects or [],
            context_hash=context_hash,
            trace_id=trace_id,
        )

        if self._signing_key:
            from syndicateclaw.security.signing import sign_payload
            signature = sign_payload(decision.inputs, self._signing_key)
            decision.side_effects = [*decision.side_effects, f"hmac:{signature}"]

        async with self._session_factory() as session, session.begin():
            repo = DecisionRecordRepository(session)
            row = DecisionRecordRow(
                id=decision.id,
                domain=decision.domain.value,
                decision_type=decision.decision_type,
                actor=decision.actor,
                run_id=decision.run_id,
                node_execution_id=decision.node_execution_id,
                inputs=decision.inputs,
                rules_evaluated=decision.rules_evaluated,
                matched_rule=decision.matched_rule,
                effect=decision.effect,
                justification=decision.justification,
                confidence=decision.confidence,
                side_effects=decision.side_effects,
                context_hash=decision.context_hash,
                trace_id=decision.trace_id,
            )
            await repo.append(row)

        logger.info(
            "decision.recorded",
            decision_id=decision.id,
            domain=domain.value,
            decision_type=decision_type,
            effect=effect,
            actor=actor,
            run_id=run_id,
        )
        return decision

    async def record_policy_decision(
        self,
        *,
        actor: str,
        resource_type: str,
        resource_id: str,
        action: str,
        all_rules: list[dict[str, Any]],
        matched_rule: str | None,
        effect: str,
        justification: str,
        input_attributes: dict[str, Any],
        run_id: str | None = None,
        trace_id: str | None = None,
    ) -> DecisionRecord:
        """Convenience method for policy decisions with full evaluation trace."""
        return await self.record(
            domain=DecisionDomain.POLICY,
            decision_type=f"policy_{action}",
            actor=actor,
            inputs={
                "resource_type": resource_type,
                "resource_id": resource_id,
                "action": action,
                "attributes": input_attributes,
            },
            rules_evaluated=all_rules,
            matched_rule=matched_rule,
            effect=effect,
            justification=justification,
            run_id=run_id,
            trace_id=trace_id,
        )

    async def record_tool_decision(
        self,
        *,
        actor: str,
        tool_name: str,
        input_data: dict[str, Any],
        policy_effect: str,
        justification: str,
        side_effects: list[str],
        run_id: str | None = None,
        node_execution_id: str | None = None,
        trace_id: str | None = None,
    ) -> DecisionRecord:
        """Convenience method for tool execution decisions."""
        return await self.record(
            domain=DecisionDomain.TOOL_EXECUTION,
            decision_type="tool_invocation",
            actor=actor,
            inputs={"tool_name": tool_name, "input_data": input_data},
            rules_evaluated=[],
            matched_rule=None,
            effect=policy_effect,
            justification=justification,
            side_effects=side_effects,
            run_id=run_id,
            node_execution_id=node_execution_id,
            trace_id=trace_id,
        )

    async def record_memory_decision(
        self,
        *,
        actor: str,
        namespace: str,
        key: str,
        action: str,
        trust_score: float,
        justification: str,
        run_id: str | None = None,
        trace_id: str | None = None,
    ) -> DecisionRecord:
        """Convenience method for memory write/read decisions."""
        domain = (
            DecisionDomain.MEMORY_WRITE if action == "write"
            else DecisionDomain.MEMORY_READ
        )
        return await self.record(
            domain=domain,
            decision_type=f"memory_{action}",
            actor=actor,
            inputs={"namespace": namespace, "key": key, "action": action},
            rules_evaluated=[],
            matched_rule=None,
            effect="allowed",
            justification=justification,
            confidence=trust_score,
            run_id=run_id,
            trace_id=trace_id,
        )

    async def get_run_decisions(self, run_id: str) -> list[DecisionRecord]:
        """Retrieve all decisions for a workflow run — the full audit trail."""
        async with self._session_factory() as session:
            repo = DecisionRecordRepository(session)
            rows = await repo.get_by_run(run_id)
            return [DecisionRecord.model_validate(r) for r in rows]

    async def get_trace_decisions(self, trace_id: str) -> list[DecisionRecord]:
        """Retrieve all decisions sharing a trace ID."""
        async with self._session_factory() as session:
            repo = DecisionRecordRepository(session)
            rows = await repo.get_by_trace(trace_id)
            return [DecisionRecord.model_validate(r) for r in rows]

    async def verify_integrity(self, decision_id: str) -> bool:
        """Re-hash inputs and compare to stored hash for tamper detection."""
        async with self._session_factory() as session:
            row = await session.get(DecisionRecordRow, decision_id)
            if row is None:
                return False
            expected = _hash_inputs(row.inputs or {})
            return expected == row.context_hash
