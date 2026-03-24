from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from ulid import ULID

from syndicateclaw.models import (
    ApprovalRequest,
    AuditEvent,
    AuditEventType,
    ToolRiskLevel,
)
from syndicateclaw.orchestrator.engine import (
    ExecutionContext,
    NodeResult,
    WaitForApprovalError,
    safe_eval_condition,
)

logger = structlog.get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def start_handler(state: dict[str, Any], context: ExecutionContext) -> NodeResult:
    """Initializes a workflow run."""
    state["_started_at"] = _utcnow().isoformat()
    state["_run_id"] = context.run_id

    if context.audit_service and hasattr(context.audit_service, "record"):
        await context.audit_service.record(
            AuditEvent(
                event_type=AuditEventType.NODE_STARTED,
                actor="system",
                resource_type="node",
                resource_id=context.node_id,
                action="start_handler",
                details={"run_id": context.run_id, "node_id": context.node_id},
            )
        )

    logger.info("workflow.started", run_id=context.run_id)
    return NodeResult(output_state=state)


async def end_handler(state: dict[str, Any], context: ExecutionContext) -> NodeResult:
    """Finalizes a workflow run."""
    state["_completed_at"] = _utcnow().isoformat()

    if context.audit_service and hasattr(context.audit_service, "record"):
        await context.audit_service.record(
            AuditEvent(
                event_type=AuditEventType.NODE_COMPLETED,
                actor="system",
                resource_type="node",
                resource_id=context.node_id,
                action="end_handler",
                details={"run_id": context.run_id, "node_id": context.node_id},
            )
        )

    logger.info("workflow.ended", run_id=context.run_id)
    return NodeResult(output_state=state)


async def checkpoint_handler(
    state: dict[str, Any], context: ExecutionContext
) -> NodeResult:
    """Persists current state as a checkpoint."""
    if context.checkpoint_store and hasattr(context.checkpoint_store, "save"):
        await context.checkpoint_store.save(context.run_id, dict(state))

    logger.info("checkpoint.created", run_id=context.run_id, node_id=context.node_id)
    return NodeResult(output_state=state, should_checkpoint=True)


async def approval_handler(
    state: dict[str, Any], context: ExecutionContext
) -> NodeResult:
    """Creates an approval request and pauses execution until approved."""
    request = ApprovalRequest(
        run_id=context.run_id,
        node_execution_id=context.config.get("node_execution_id", str(ULID())),
        action_description=context.config.get("description", "Approval required"),
        risk_level=ToolRiskLevel(context.config.get("risk_level", "MEDIUM")),
        requested_by=context.config.get("requested_by", "system"),
        assigned_to=context.config.get("assigned_to", []),
        expires_at=_utcnow() + timedelta(hours=context.config.get("expires_hours", 24)),
        context={"run_id": context.run_id, "node_id": context.node_id, "state": dict(state)},
    )

    state["_pending_approval"] = request.model_dump(mode="json")
    logger.info("approval.requested", run_id=context.run_id, approval_id=request.id)

    raise WaitForApprovalError(f"Approval required: {request.id}")


async def llm_handler(state: dict[str, Any], context: ExecutionContext) -> NodeResult:
    """Placeholder for LLM integration.

    In a full implementation this would call an LLM provider through the
    configured model router. For now it annotates the state.
    """
    prompt = context.config.get("prompt", "")
    model = context.config.get("model", "default")

    state["_llm_response"] = {
        "note": "LLM handler placeholder - no actual call made",
        "prompt": prompt,
        "model": model,
    }

    logger.info("llm.placeholder", run_id=context.run_id, model=model)
    return NodeResult(output_state=state)


async def decision_handler(
    state: dict[str, Any], context: ExecutionContext
) -> NodeResult:
    """Evaluates a condition and picks the next node."""
    condition = context.config.get("condition", "")
    true_node = context.config.get("true_node")
    false_node = context.config.get("false_node")

    result = safe_eval_condition(condition, state) if condition else False
    next_node = true_node if result else false_node

    state["_decision"] = {
        "condition": condition,
        "result": result,
        "next_node": next_node,
    }

    logger.info(
        "decision.evaluated",
        run_id=context.run_id,
        condition=condition,
        result=result,
        next_node=next_node,
    )
    return NodeResult(output_state=state, next_node_id=next_node)


BUILTIN_HANDLERS: dict[str, Any] = {
    "start": start_handler,
    "end": end_handler,
    "checkpoint": checkpoint_handler,
    "approval": approval_handler,
    "llm": llm_handler,
    "decision": decision_handler,
}
