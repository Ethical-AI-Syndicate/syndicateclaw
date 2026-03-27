from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from ulid import ULID

from syndicateclaw.inference.types import ChatInferenceRequest, ChatMessage
from syndicateclaw.llm.idempotency import IdempotencyStore as LLMIdempotencyStore
from syndicateclaw.llm.templates import render_message_template
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
    """Execute an LLM node through ProviderService."""
    provider_service = context.provider_service or context.config.get("provider_service")
    if provider_service is None:
        raise RuntimeError("provider_service is required for llm handler")

    actor = str(context.config.get("actor", "system:engine"))
    scope_type = str(context.config.get("scope_type", "PLATFORM"))
    scope_id = str(context.config.get("scope_id", "default"))

    idempotency = LLMIdempotencyStore()
    idem = idempotency.resolve(
        run_id=context.run_id,
        node_id=context.node_id,
        attempt_number=context.attempt,
        bypass_cache=bool(context.config.get("bypass_cache", False)),
    )

    template = str(context.config.get("prompt_template", context.config.get("prompt", "")))
    rendered_prompt = render_message_template(template, {"state": state, **context.config})

    messages_cfg = context.config.get("messages")
    if isinstance(messages_cfg, list) and messages_cfg:
        messages = [ChatMessage.model_validate(item) for item in messages_cfg]
    else:
        messages = [ChatMessage(role="user", content=rendered_prompt)]

    request = ChatInferenceRequest(
        messages=messages,
        model_id=context.config.get("model_id"),
        provider_id=context.config.get("provider_id"),
        temperature=context.config.get("temperature"),
        max_tokens=context.config.get("max_tokens"),
        actor=actor,
        scope_type=scope_type,
        scope_id=scope_id,
        trace_id=str(ULID()),
        idempotency_key=None if idem.bypass_cache else idem.key,
    )

    response = await provider_service.infer_chat(request)

    response_key = str(context.config.get("response_key", "llm_response"))
    state[response_key] = response.content
    state[f"_llm_output_{response_key}"] = True

    if not bool(context.config.get("allow_tool_calls", False)):
        logger.warning(
            "llm.tool_calls_ignored",
            run_id=context.run_id,
            node_id=context.node_id,
        )

    logger.info("llm.completed", run_id=context.run_id, model=response.model_id)
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
