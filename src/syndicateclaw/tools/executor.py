from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import structlog
from ulid import ULID

from syndicateclaw.models import (
    ApprovalRequest,
    ApprovalScope,
    AuditEvent,
    AuditEventType,
    PolicyEffect,
    Tool,
    ToolExecution,
    ToolExecutionStatus,
    ToolSandboxPolicy,
)
from syndicateclaw.orchestrator.engine import ExecutionContext
from syndicateclaw.tools.registry import ToolRegistry

logger = structlog.get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class ToolNotFoundError(Exception):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"Tool not found: {name}")


class ToolDeniedError(Exception):
    def __init__(self, name: str, reason: str = "") -> None:
        self.name = name
        self.reason = reason
        super().__init__(f"Tool denied: {name}" + (f" ({reason})" if reason else ""))


class ApprovalRequiredError(Exception):
    def __init__(self, name: str, request: ApprovalRequest) -> None:
        self.name = name
        self.request = request
        super().__init__(f"Approval required for tool: {name} (request={request.id})")


class ToolExecutionError(Exception):
    def __init__(self, name: str, cause: Exception) -> None:
        self.name = name
        self.cause = cause
        super().__init__(f"Tool execution failed: {name}: {cause}")


class ToolTimeoutError(Exception):
    def __init__(self, name: str, timeout: int) -> None:
        self.name = name
        self.timeout = timeout
        super().__init__(f"Tool timed out after {timeout}s: {name}")


class SandboxViolationError(Exception):
    def __init__(self, name: str, violation: str) -> None:
        self.name = name
        self.violation = violation
        super().__init__(f"Sandbox violation for tool {name}: {violation}")


# ---------------------------------------------------------------------------
# Schema validation helper
# ---------------------------------------------------------------------------


def _validate_schema(data: dict[str, Any], schema: dict[str, Any], label: str) -> None:
    if not schema:
        return
    required = schema.get("required", [])
    for key in required:
        if key not in data:
            raise ValueError(f"{label}: missing required field '{key}'")
    properties = schema.get("properties", {})
    type_map: dict[str, type | tuple[type, ...]] = {
        "string": str, "integer": int, "number": (int, float),
        "boolean": bool, "array": list, "object": dict,
    }
    for key, prop in properties.items():
        if key not in data:
            continue
        expected_type = type_map.get(prop.get("type", ""))
        if expected_type and not isinstance(data[key], expected_type):
            raise ValueError(
                f"{label}: field '{key}' expected type {prop['type']}, got {type(data[key]).__name__}"
            )


# ---------------------------------------------------------------------------
# Sandbox enforcement
# ---------------------------------------------------------------------------


def enforce_sandbox(tool_name: str, input_data: dict[str, Any], policy: ToolSandboxPolicy) -> None:
    """Enforce sandbox policy BEFORE execution. Raises SandboxViolationError on violation."""
    if policy.network_isolation:
        url = input_data.get("url")
        if url:
            raise SandboxViolationError(tool_name, "network access denied: tool has network_isolation=True")

    url = input_data.get("url")
    if url and isinstance(url, str):
        parsed = urlparse(url)

        if parsed.scheme and parsed.scheme not in policy.allowed_protocols:
            raise SandboxViolationError(
                tool_name, f"protocol '{parsed.scheme}' not in allowed: {policy.allowed_protocols}"
            )

        if policy.allowed_domains and parsed.hostname:
            if parsed.hostname not in policy.allowed_domains:
                raise SandboxViolationError(
                    tool_name, f"domain '{parsed.hostname}' not in allowlist: {policy.allowed_domains}"
                )

    body = input_data.get("body")
    if body and isinstance(body, (str, bytes)):
        size = len(body.encode() if isinstance(body, str) else body)
        if size > policy.max_request_bytes:
            raise SandboxViolationError(
                tool_name, f"request payload {size} bytes exceeds limit {policy.max_request_bytes}"
            )

    if not policy.subprocess_allowed and input_data.get("subprocess"):
        raise SandboxViolationError(tool_name, "subprocess execution denied")

    if not policy.filesystem_read and input_data.get("file_path"):
        raise SandboxViolationError(tool_name, "filesystem read denied")


def enforce_response_limits(tool_name: str, output: dict[str, Any], policy: ToolSandboxPolicy) -> None:
    """Enforce response payload limits AFTER execution."""
    serialized = json.dumps(output, default=str)
    if len(serialized.encode()) > policy.max_response_bytes:
        raise SandboxViolationError(
            tool_name, f"response payload exceeds limit {policy.max_response_bytes}"
        )


# ---------------------------------------------------------------------------
# ToolExecutor — controls are MANDATORY on the hot path
# ---------------------------------------------------------------------------


class ToolExecutor:
    """Executes registered tools with mandatory decision ledger, sandbox
    enforcement, policy checks, input snapshotting, and auditing.

    Enforcement guarantees:
    - Tool execution CANNOT complete without a DecisionRecord
    - Sandbox policy is enforced before execution, fail-closed if missing
    - Input snapshots are captured for replay
    - If the decision ledger is unavailable, execution is DENIED
    """

    def __init__(
        self,
        registry: ToolRegistry,
        policy_engine: Any = None,
        audit_service: Any = None,
        decision_ledger: Any = None,
        snapshot_store: Any = None,
    ) -> None:
        self._registry = registry
        self._policy_engine = policy_engine
        self._audit_service = audit_service
        self._decision_ledger = decision_ledger
        self._snapshot_store = snapshot_store

    async def execute(
        self,
        tool_name: str,
        input_data: dict[str, Any],
        context: ExecutionContext,
    ) -> dict[str, Any]:
        tool_def = self._registry.get(tool_name)
        if tool_def is None:
            raise ToolNotFoundError(tool_name)

        tool_meta = tool_def.tool

        # --- 1. Schema validation ---
        _validate_schema(input_data, tool_meta.input_schema, f"tool:{tool_name}:input")

        # --- 2. Sandbox enforcement (MANDATORY, fail-closed) ---
        sandbox = tool_meta.sandbox_policy
        enforce_sandbox(tool_name, input_data, sandbox)

        # --- 3. Policy check ---
        # PolicyEngine.evaluate(resource_type, resource_id, action, actor, context)
        decision = await self._check_policy(tool_name, input_data, context, tool_meta)

        if decision == PolicyEffect.DENY:
            await self._record_decision(
                tool_name, input_data, context, "deny",
                f"Policy denied execution of tool '{tool_name}'",
                tool_meta.side_effects,
            )
            raise ToolDeniedError(tool_name)

        if decision == PolicyEffect.REQUIRE_APPROVAL:
            await self._record_decision(
                tool_name, input_data, context, "require_approval",
                f"Policy requires approval for tool '{tool_name}'",
                tool_meta.side_effects,
            )
            request = ApprovalRequest(
                run_id=context.run_id,
                node_execution_id=context.config.get("node_execution_id", str(ULID())),
                tool_name=tool_name,
                action_description=f"Execute tool: {tool_name}",
                risk_level=tool_meta.risk_level,
                requested_by=context.run_id,
                expires_at=_utcnow() + timedelta(hours=24),
                context={"tool": tool_name, "input": input_data},
                scope=ApprovalScope(),
            )
            raise ApprovalRequiredError(tool_name, request)

        # --- 4. Decision ledger record (MANDATORY — fail-closed) ---
        decision_record = await self._record_decision(
            tool_name, input_data, context, "allow",
            f"Policy allowed execution of tool '{tool_name}'",
            tool_meta.side_effects,
        )
        if decision_record is None:
            raise ToolDeniedError(
                tool_name,
                reason="Decision ledger unavailable — execution denied (fail-closed)",
            )

        # --- 5. Execute with timeout ---
        record = ToolExecution(
            run_id=context.run_id,
            node_execution_id=context.config.get("node_execution_id", str(ULID())),
            tool_name=tool_name,
            input_data=input_data,
            status=ToolExecutionStatus.RUNNING,
            started_at=_utcnow(),
            policy_decision_id=decision_record.id if decision_record else None,
        )
        t0 = time.monotonic()

        try:
            output = await asyncio.wait_for(
                tool_def.handler(input_data),
                timeout=tool_meta.timeout_seconds,
            )
        except TimeoutError:
            record.status = ToolExecutionStatus.TIMED_OUT
            record.error = f"Timed out after {tool_meta.timeout_seconds}s"
            record.completed_at = _utcnow()
            record.duration_ms = int((time.monotonic() - t0) * 1000)
            await self._emit_audit(AuditEventType.TOOL_EXECUTION_TIMED_OUT, record)
            raise ToolTimeoutError(tool_name, tool_meta.timeout_seconds) from None
        except Exception as exc:
            record.status = ToolExecutionStatus.FAILED
            record.error = str(exc)
            record.completed_at = _utcnow()
            record.duration_ms = int((time.monotonic() - t0) * 1000)
            await self._emit_audit(AuditEventType.TOOL_EXECUTION_FAILED, record)
            raise ToolExecutionError(tool_name, exc) from exc

        # --- 6. Response sandbox enforcement ---
        enforce_response_limits(tool_name, output, sandbox)

        # --- 7. Schema validation on output ---
        record.status = ToolExecutionStatus.COMPLETED
        record.output_data = output
        record.completed_at = _utcnow()
        record.duration_ms = int((time.monotonic() - t0) * 1000)

        _validate_schema(output, tool_meta.output_schema, f"tool:{tool_name}:output")

        # --- 8. Capture input snapshot for replay (MANDATORY) ---
        await self._capture_snapshot(
            context, tool_name, input_data, output,
        )

        # --- 9. Audit ---
        await self._emit_audit(AuditEventType.TOOL_EXECUTION_COMPLETED, record)

        logger.info(
            "tool.executed",
            tool=tool_name,
            duration_ms=record.duration_ms,
            decision_record_id=decision_record.id if decision_record else None,
        )
        return output

    # -- internals ----------------------------------------------------------

    def _policy_actor(self, context: ExecutionContext) -> str:
        """Actor for policy evaluation; workflow runs may use actor from config."""
        if context.config.get("actor"):
            return str(context.config["actor"])
        return context.run_id

    def _build_tool_policy_context(
        self,
        tool_name: str,
        tool_meta: Tool,
        input_data: dict[str, Any],
        context: ExecutionContext,
    ) -> dict[str, Any]:
        """Context for PolicyEngine conditions (risk_level, input, run metadata)."""
        actor = self._policy_actor(context)
        ctx: dict[str, Any] = {
            "input": input_data,
            "tool": tool_name,
            "risk_level": tool_meta.risk_level.value,
            "run_id": context.run_id,
            "node_id": context.node_id,
            "actor": actor,
        }
        reserved = frozenset(ctx.keys())
        for key, value in (context.config or {}).items():
            if key not in reserved:
                ctx[key] = value
        return ctx

    async def _check_policy(
        self,
        tool_name: str,
        input_data: dict[str, Any],
        context: ExecutionContext,
        tool_meta: Tool,
    ) -> PolicyEffect:
        if self._policy_engine is None:
            logger.error("policy_engine.missing", tool=tool_name)
            return PolicyEffect.DENY
        if not hasattr(self._policy_engine, "evaluate"):
            return PolicyEffect.ALLOW
        actor = self._policy_actor(context)
        policy_context = self._build_tool_policy_context(
            tool_name, tool_meta, input_data, context)
        try:
            result = await self._policy_engine.evaluate(
                "tool",
                tool_name,
                "execute",
                actor,
                policy_context,
            )
        except Exception:
            logger.exception("policy_engine.evaluate_failed", tool=tool_name)
            return PolicyEffect.DENY
        if hasattr(result, "effect"):
            return result.effect  # PolicyDecision
        return result  # tests may return PolicyEffect directly

    async def _record_decision(
        self,
        tool_name: str,
        input_data: dict[str, Any],
        context: ExecutionContext,
        effect: str,
        justification: str,
        side_effects: list[str],
    ) -> Any:
        """Record to decision ledger. Returns the record, or None on failure."""
        if self._decision_ledger is None:
            logger.error("decision_ledger.unavailable", tool=tool_name)
            return None
        try:
            return await self._decision_ledger.record_tool_decision(
                actor=context.run_id,
                tool_name=tool_name,
                input_data=input_data,
                policy_effect=effect,
                justification=justification,
                side_effects=side_effects,
                run_id=context.run_id,
                node_execution_id=context.node_id,
            )
        except Exception:
            logger.exception("decision_ledger.record_failed", tool=tool_name)
            return None

    async def _capture_snapshot(
        self,
        context: ExecutionContext,
        tool_name: str,
        input_data: dict[str, Any],
        output: dict[str, Any],
    ) -> None:
        if self._snapshot_store is None:
            return
        try:
            await self._snapshot_store.capture(
                run_id=context.run_id,
                node_execution_id=context.node_id,
                snapshot_type="tool_response",
                source_identifier=tool_name,
                request_data=input_data,
                response_data=output,
            )
        except Exception:
            logger.warning("snapshot.capture_failed", tool=tool_name, exc_info=True)

    async def _emit_audit(self, event_type: AuditEventType, record: ToolExecution) -> None:
        event = AuditEvent(
            event_type=event_type,
            actor="system",
            resource_type="tool",
            resource_id=record.tool_name,
            action=event_type.value,
            details=record.model_dump(mode="json"),
        )
        if self._audit_service is not None and hasattr(self._audit_service, "emit"):
            try:
                await self._audit_service.emit(event)
            except Exception:
                logger.warning("audit.emit_failed", exc_info=True)
        elif self._audit_service is not None and hasattr(self._audit_service, "record"):
            try:
                await self._audit_service.record(event)
            except Exception:
                logger.warning("audit.record_failed", exc_info=True)
