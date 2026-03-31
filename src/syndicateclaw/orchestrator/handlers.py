from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from ulid import ULID

from syndicateclaw.inference.types import ChatInferenceRequest, ChatMessage
from syndicateclaw.llm.idempotency import IdempotencyStore as LLMIdempotencyStore
from syndicateclaw.llm.metrics import (
    llm_cache_hits_total,
    llm_cost_usd_total,
    llm_request_duration_seconds,
    llm_requests_total,
    llm_tokens_used_total,
)
from syndicateclaw.llm.templates import render_message_template
from syndicateclaw.llm.tracing import llm_span
from syndicateclaw.models import (
    ApprovalRequest,
    AuditEvent,
    AuditEventType,
    PolicyEffect,
    ToolRiskLevel,
)
from syndicateclaw.orchestrator.engine import (
    ExecutionContext,
    NodeResult,
    WaitForAgentResponseError,
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

    t0 = time.monotonic()
    try:
        response = await provider_service.infer_chat(request)
    except Exception:
        llm_requests_total.labels(provider="unknown", model="unknown", status="failed").inc()
        raise

    elapsed = max(time.monotonic() - t0, 0.0)

    provider_label = str(getattr(response, "provider_id", "unknown"))
    model_label = str(getattr(response, "model_id", "unknown"))
    llm_requests_total.labels(provider=provider_label, model=model_label, status="success").inc()
    llm_request_duration_seconds.labels(provider=provider_label, model=model_label).observe(elapsed)

    usage = getattr(response, "usage", None)
    with llm_span(
        provider=provider_label,
        model=model_label,
        cached=bool(context.config.get("cache_hit", False)),
    ) as span:
        if usage is not None:
            span.set_attribute("prompt_tokens", int(getattr(usage, "prompt_tokens", 0) or 0))
            span.set_attribute(
                "completion_tokens", int(getattr(usage, "completion_tokens", 0) or 0)
            )
        span.set_attribute("latency_ms", int(elapsed * 1000))

    if usage is not None:
        llm_tokens_used_total.labels(
            provider=provider_label,
            model=model_label,
            token_type="prompt",
        ).inc(float(getattr(usage, "prompt_tokens", 0) or 0))
        llm_tokens_used_total.labels(
            provider=provider_label,
            model=model_label,
            token_type="completion",
        ).inc(float(getattr(usage, "completion_tokens", 0) or 0))

    cost_usd = getattr(response, "cost_usd", None)
    if cost_usd is not None:
        llm_cost_usd_total.labels(provider=provider_label, model=model_label).inc(float(cost_usd))

    if bool(context.config.get("cache_hit", False)):
        llm_cache_hits_total.labels(provider=provider_label, model=model_label).inc()

    response_key = str(context.config.get("response_key", "llm_response"))
    state[response_key] = response.content
    state[f"_llm_output_{response_key}"] = True

    tool_calls = list(getattr(response, "tool_calls", []) or [])
    allow_tool_calls = bool(context.config.get("allow_tool_calls", False))
    if tool_calls and not allow_tool_calls:
        logger.warning(
            "llm.tool_calls_ignored",
            run_id=context.run_id,
            node_id=context.node_id,
            count=len(tool_calls),
        )
    elif tool_calls and allow_tool_calls:
        await _process_llm_tool_calls(state, context, tool_calls)

    logger.info("llm.completed", run_id=context.run_id, model=response.model_id)
    return NodeResult(output_state=state)


def _validate_tool_call_args(input_data: dict[str, Any], schema: dict[str, Any]) -> None:
    required = schema.get("required", [])
    for key in required:
        if key not in input_data:
            raise ValueError(f"missing required field '{key}'")


async def _emit_tool_call_audit(
    context: ExecutionContext,
    *,
    action: str,
    details: dict[str, Any],
) -> None:
    if context.audit_service is None or not hasattr(context.audit_service, "record"):
        return
    await context.audit_service.record(
        AuditEvent(
            event_type=AuditEventType.TOOL_EXECUTION_STARTED,
            actor="system:engine",
            resource_type="tool",
            resource_id=str(details.get("tool", "unknown")),
            action=action,
            details=details,
        )
    )


async def _process_llm_tool_calls(
    state: dict[str, Any],
    context: ExecutionContext,
    tool_calls: list[dict[str, Any]],
) -> None:
    tool_executor = context.tool_executor
    if tool_executor is None:
        return

    policy_engine = getattr(tool_executor, "_policy_engine", None)
    tool_registry = getattr(tool_executor, "_registry", None)
    if tool_registry is None:
        return

    for call in tool_calls:
        name = str(call.get("name", ""))
        args = call.get("arguments", {})
        if not isinstance(args, dict):
            args = {}

        tool_def = tool_registry.get(name)
        if tool_def is None:
            await _emit_tool_call_audit(
                context,
                action="llm.tool_call_invalid_args",
                details={"tool": name, "reason": "unknown_tool"},
            )
            continue

        try:
            _validate_tool_call_args(args, tool_def.tool.input_schema)
        except ValueError as exc:
            await _emit_tool_call_audit(
                context,
                action="llm.tool_call_invalid_args",
                details={"tool": name, "reason": str(exc)},
            )
            continue

        decision = PolicyEffect.ALLOW
        if policy_engine is not None and hasattr(policy_engine, "evaluate"):
            result = await policy_engine.evaluate(
                "tool",
                name,
                "execute",
                "system:engine",
                {
                    "tool": name,
                    "input": args,
                    "run_id": context.run_id,
                    "node_id": context.node_id,
                },
            )
            decision = result.effect if hasattr(result, "effect") else result

        if decision == PolicyEffect.DENY:
            await _emit_tool_call_audit(
                context,
                action="llm.tool_call_denied",
                details={"tool": name, "decision": "DENY"},
            )
            continue

        if decision == PolicyEffect.REQUIRE_APPROVAL:
            approval = ApprovalRequest(
                run_id=context.run_id,
                node_execution_id=context.config.get("node_execution_id", str(ULID())),
                tool_name=name,
                action_description=f"LLM tool call requires approval: {name}",
                risk_level=tool_def.tool.risk_level,
                requested_by="system:engine",
                expires_at=_utcnow() + timedelta(hours=24),
                context={"tool": name, "arguments": args},
            )
            state.setdefault("_pending_approvals", []).append(approval.model_dump(mode="json"))
            await _emit_tool_call_audit(
                context,
                action="llm.tool_call_requires_approval",
                details={"tool": name, "approval_id": approval.id},
            )
            raise WaitForApprovalError(f"Approval required: {approval.id}")

        await _emit_tool_call_audit(
            context,
            action="llm.tool_call",
            details={"tool": name},
        )
        tool_context = ExecutionContext(
            run_id=context.run_id,
            node_id=context.node_id,
            attempt=context.attempt,
            config={**context.config, "actor": "system:engine"},
            tool_executor=context.tool_executor,
            memory_service=context.memory_service,
            audit_service=context.audit_service,
            checkpoint_store=context.checkpoint_store,
            provider_service=context.provider_service,
            message_service=context.message_service,
        )
        result = await tool_executor.execute(name, args, tool_context)
        state.setdefault("_llm_tool_results", []).append({"tool": name, "result": result})


def _render_template_dict(value: Any, template_context: dict[str, Any]) -> Any:
    if isinstance(value, str):
        return render_message_template(value, template_context)
    if isinstance(value, list):
        return [_render_template_dict(item, template_context) for item in value]
    if isinstance(value, dict):
        return {k: _render_template_dict(v, template_context) for k, v in value.items()}
    return value


async def agent_send_handler(state: dict[str, Any], context: ExecutionContext) -> NodeResult:
    """Send a workflow message to an agent and optionally wait for response."""
    message_service = context.message_service or context.config.get("message_service")
    if message_service is None:
        raise RuntimeError("message_service is required for agent_send handler")

    recipient_id = context.config.get("recipient_id")
    recipient_name = context.config.get("recipient_name")
    recipient = str(recipient_id or recipient_name or "")
    fallback_strategy = str(context.config.get("fallback_strategy", "fail")).lower()

    message_type = str(context.config.get("message_type", "REQUEST"))
    response_key = str(context.config.get("response_key", "agent_response"))
    wait_for_response = bool(context.config.get("wait_for_response", False))
    timeout_seconds = int(context.config.get("response_timeout_seconds", 300))
    priority = str(context.config.get("priority", "NORMAL"))
    namespace = str(context.config.get("namespace", state.get("namespace", "default")))
    actor = str(context.config.get("actor", "system:engine"))

    topic: str | None = None
    if not recipient:
        if fallback_strategy == "broadcast":
            message_type = "BROADCAST"
            recipient = ""
        elif fallback_strategy == "queue":
            capability = str(context.config.get("capability", "default"))
            topic = f"capability:{capability}"
        else:
            raise ValueError("agent_send requires recipient_id or recipient_name")

    template_context = {"state": state, "context": context.config}
    content_cfg = context.config.get("content", {})
    if not isinstance(content_cfg, dict):
        raise ValueError("agent_send config.content must be an object")
    content = _render_template_dict(content_cfg, template_context)

    conversation_id = str(ULID())
    sent_rows = await message_service.send(
        actor=actor,
        namespace=namespace,
        message_type=message_type,
        content=content,
        recipient=recipient or None,
        topic=topic,
        conversation_id=conversation_id,
        priority=priority,
    )
    if not sent_rows:
        raise RuntimeError("agent_send did not persist any message")
    first = sent_rows[0]

    if not wait_for_response:
        state[response_key] = {
            "message_id": first.id,
            "conversation_id": conversation_id,
        }
        return NodeResult(output_state=state)

    state["_waiting_agent_response"] = {
        "conversation_id": conversation_id,
        "response_key": response_key,
        "requested_at": _utcnow().isoformat(),
        "timeout_seconds": timeout_seconds,
    }
    raise WaitForAgentResponseError(f"Waiting for agent response on conversation {conversation_id}")


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
    "agent_send": agent_send_handler,
    "decision": decision_handler,
}
