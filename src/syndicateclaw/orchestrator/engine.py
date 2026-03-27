from __future__ import annotations

import dataclasses
import json
import operator
import re
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

import structlog
from opentelemetry import trace

from syndicateclaw.models import (
    AuditEvent,
    AuditEventType,
    EdgeDefinition,
    NodeDefinition,
    NodeExecution,
    NodeExecutionStatus,
    NodeType,
    WorkflowDefinition,
    WorkflowRun,
    WorkflowRunStatus,
)

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)


# ---------------------------------------------------------------------------
# Supporting data structures
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class ExecutionContext:
    """Ambient context available to every node handler during execution."""

    run_id: str
    node_id: str = ""
    attempt: int = 1
    config: dict[str, Any] = dataclasses.field(default_factory=dict)
    tool_executor: Any = None
    memory_service: Any = None
    audit_service: Any = None
    checkpoint_store: Any = None
    provider_service: Any = None


@dataclasses.dataclass
class NodeResult:
    """Value returned by a node handler."""

    output_state: dict[str, Any]
    next_node_id: str | None = None
    should_checkpoint: bool = False


@runtime_checkable
class NodeHandler(Protocol):
    async def __call__(
        self, state: dict[str, Any], context: ExecutionContext
    ) -> NodeResult: ...


# ---------------------------------------------------------------------------
# Safe condition evaluator (NO eval / exec)
# ---------------------------------------------------------------------------

_COMPARE_OPS: dict[str, Any] = {
    "==": operator.eq,
    "!=": operator.ne,
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
}

_TOKEN_RE = re.compile(
    r"""
    \s*
    (?:
        (?P<bool>true|false|True|False)
      | (?P<none>None|null)
      | (?P<number>-?\d+(?:\.\d+)?)
      | (?P<string>'[^']*'|"[^"]*")
      | (?P<keyword>and|or|not|in)
      | (?P<op>==|!=|>=|<=|>|<)
      | (?P<ident>state\.\w+)
      | (?P<lbracket>\[)
      | (?P<rbracket>\])
      | (?P<lparen>\()
      | (?P<rparen>\))
      | (?P<comma>,)
    )
    """,
    re.VERBOSE,
)


class _ConditionParser:
    """Recursive-descent parser for a minimal safe expression language.

    Supported grammar::

        expr     -> or_expr
        or_expr  -> and_expr ("or" and_expr)*
        and_expr -> not_expr ("and" not_expr)*
        not_expr -> "not" not_expr | compare
        compare  -> primary (("=="|"!="|">"|">="|"<"|"<=") primary)?
                  | primary "in" list
        primary  -> state_ref | literal | "(" expr ")"
        list     -> "[" literal ("," literal)* "]"
    """

    def __init__(self, expression: str, state: dict[str, Any]) -> None:
        self._tokens: list[tuple[str, str]] = []
        self._pos = 0
        self._state = state
        self._tokenize(expression)

    def _tokenize(self, expression: str) -> None:
        pos = 0
        while pos < len(expression):
            if expression[pos].isspace():
                pos += 1
                continue
            m = _TOKEN_RE.match(expression, pos)
            if not m:
                raise ValueError(
                    f"Unexpected character at position {pos}: {expression[pos:]}"
                )
            kind = m.lastgroup
            assert kind is not None
            value = m.group(kind)
            self._tokens.append((kind, value))
            pos = m.end()

    def _peek(self) -> tuple[str, str] | None:
        if self._pos < len(self._tokens):
            return self._tokens[self._pos]
        return None

    def _advance(self) -> tuple[str, str]:
        tok = self._tokens[self._pos]
        self._pos += 1
        return tok

    def _expect(self, kind: str) -> tuple[str, str]:
        tok = self._peek()
        if tok is None or tok[0] != kind:
            expected = kind
            got = tok[1] if tok else "EOF"
            raise ValueError(f"Expected {expected}, got {got}")
        return self._advance()

    def parse(self) -> bool:
        result = self._or_expr()
        if self._pos != len(self._tokens):
            raise ValueError(f"Unexpected token: {self._tokens[self._pos][1]}")
        return bool(result)

    def _or_expr(self) -> Any:
        left = self._and_expr()
        while self._peek() == ("keyword", "or"):
            self._advance()
            right = self._and_expr()
            left = left or right
        return left

    def _and_expr(self) -> Any:
        left = self._not_expr()
        while self._peek() == ("keyword", "and"):
            self._advance()
            right = self._not_expr()
            left = left and right
        return left

    def _not_expr(self) -> Any:
        if self._peek() == ("keyword", "not"):
            self._advance()
            return not self._not_expr()
        return self._compare()

    def _compare(self) -> Any:
        left = self._primary()
        tok = self._peek()
        if tok is not None and tok[0] == "op":
            self._advance()
            right = self._primary()
            return _COMPARE_OPS[tok[1]](left, right)
        if tok == ("keyword", "in"):
            self._advance()
            right = self._list()
            return left in right
        return left

    def _primary(self) -> Any:
        tok = self._peek()
        if tok is None:
            raise ValueError("Unexpected end of expression")

        if tok[0] == "ident":
            self._advance()
            key = tok[1].removeprefix("state.")
            return self._state.get(key)

        if tok[0] == "number":
            self._advance()
            return float(tok[1]) if "." in tok[1] else int(tok[1])

        if tok[0] == "string":
            self._advance()
            return tok[1][1:-1]

        if tok[0] == "bool":
            self._advance()
            return tok[1] in ("true", "True")

        if tok[0] == "none":
            self._advance()
            return None

        if tok[0] == "lparen":
            self._advance()
            value = self._or_expr()
            self._expect("rparen")
            return value

        raise ValueError(f"Unexpected token: {tok[1]}")

    def _list(self) -> list[Any]:
        self._expect("lbracket")
        items: list[Any] = []
        peek = self._peek()
        if peek is not None and peek[0] != "rbracket":
            items.append(self._primary())
            while self._peek() == ("comma", ","):
                self._advance()
                items.append(self._primary())
        self._expect("rbracket")
        return items


def safe_eval_condition(condition: str, state: dict[str, Any]) -> bool:
    """Evaluate a condition expression against workflow state safely."""
    return _ConditionParser(condition, state).parse()


# ---------------------------------------------------------------------------
# WorkflowEngine
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(UTC)


class WorkflowEngine:
    """Executes a workflow graph defined by a :class:`WorkflowDefinition`."""

    def __init__(
        self,
        handler_registry: dict[str, NodeHandler],
        *,
        checkpoint_store: Any = None,
        audit_service: Any = None,
        signing_key: bytes | None = None,
    ) -> None:
        self._handlers = handler_registry
        self._checkpoint_store = checkpoint_store
        self._audit_service = audit_service
        self._signing_key = signing_key
        self._runs: dict[str, WorkflowRunResult] = {}

    # -- public API ---------------------------------------------------------

    async def execute(
        self, run: WorkflowRun, context: ExecutionContext, *, workflow: WorkflowDefinition
    ) -> WorkflowRunResult:
        """Execute a workflow run from its START node to completion."""
        run_result = self._runs.get(run.id) or WorkflowRunResult(run=run)
        self._runs[run.id] = run_result

        run.status = WorkflowRunStatus.RUNNING
        run.started_at = _utcnow()

        await self._emit_audit(
            AuditEventType.WORKFLOW_STARTED,
            actor=run.initiated_by,
            resource_type="workflow",
            resource_id=workflow.id,
            action="started",
            details={"run_id": run.id},
        )

        nodes_by_id = {n.id: n for n in workflow.nodes}
        start_node = self._find_start_node(workflow)
        current_node_id: str | None = start_node.id

        while current_node_id is not None:
            if run.status in (
                WorkflowRunStatus.PAUSED,
                WorkflowRunStatus.CANCELLED,
                WorkflowRunStatus.WAITING_APPROVAL,
                WorkflowRunStatus.WAITING_AGENT_RESPONSE,
            ):
                break

            node = nodes_by_id.get(current_node_id)
            if node is None:
                run.status = WorkflowRunStatus.FAILED
                run.error = f"Node not found: {current_node_id}"
                break

            run_result.current_node_id = current_node_id
            context.node_id = current_node_id

            result = await self._execute_node(node, run, run_result, context)

            if run.status in (
                WorkflowRunStatus.FAILED,
                WorkflowRunStatus.PAUSED,
                WorkflowRunStatus.WAITING_APPROVAL,
                WorkflowRunStatus.WAITING_AGENT_RESPONSE,
            ):
                break

            if result.should_checkpoint:
                await self._persist_checkpoint(run)

            if node.node_type == NodeType.END:
                run.status = WorkflowRunStatus.COMPLETED
                run.completed_at = _utcnow()
                await self._emit_audit(
                    AuditEventType.WORKFLOW_COMPLETED,
                    actor=run.initiated_by,
                    resource_type="workflow",
                    resource_id=workflow.id,
                    action="completed",
                    details={"run_id": run.id},
                )
                break

            if result.next_node_id is not None:
                current_node_id = result.next_node_id
            else:
                current_node_id = self._resolve_next_node(
                    current_node_id, run.state, workflow.edges
                )

        return run_result

    async def resume(
        self, run_id: str, from_node: str | None = None
    ) -> WorkflowRunResult:
        """Resume a paused workflow run.

        Caller must supply the :class:`WorkflowDefinition` via a second call
        to :meth:`execute` after adjusting the run state.
        """
        run_result = self._runs.get(run_id)
        if run_result is None:
            raise ValueError(f"Run not found: {run_id}")
        run = run_result.run
        if run.status not in (
            WorkflowRunStatus.PAUSED,
            WorkflowRunStatus.WAITING_APPROVAL,
            WorkflowRunStatus.WAITING_AGENT_RESPONSE,
        ):
            raise ValueError(f"Run {run_id} is not paused (status={run.status})")

        run.status = WorkflowRunStatus.RUNNING
        if from_node is not None:
            run.state["_resume_from"] = from_node
            run_result.current_node_id = from_node

        await self._emit_audit(
            AuditEventType.WORKFLOW_RESUMED,
            actor=run.initiated_by,
            resource_type="workflow_run",
            resource_id=run_id,
            action="resumed",
        )
        return run_result

    async def replay(self, run_id: str) -> WorkflowRunResult:
        """Reset a run to its last checkpoint for re-execution.

        If the checkpoint is signed, the HMAC is verified before loading.
        Tampered checkpoints raise ``ValueError``.
        """
        run_result = self._runs.get(run_id)
        if run_result is None:
            raise ValueError(f"Run not found: {run_id}")
        run = run_result.run

        if run.checkpoint_data is not None:
            raw = json.loads(run.checkpoint_data)
            if isinstance(raw, dict) and "checkpoint_hmac" in raw:
                self._verify_checkpoint_hmac(raw)
                run.state = raw["data"]
            else:
                run.state = raw

        run.status = WorkflowRunStatus.PENDING
        run.error = None
        run.completed_at = None
        run_result.node_executions = []
        return run_result

    def _verify_checkpoint_hmac(self, envelope: dict[str, Any]) -> None:
        """Verify HMAC on a signed checkpoint envelope."""
        stored_sig = envelope.get("checkpoint_hmac", "")
        data = envelope.get("data", {})
        serialized = json.dumps(data, default=str).encode()

        if not self._signing_key:
            logger.warning(
                "checkpoint.hmac_present_but_no_key",
                msg="Checkpoint has HMAC but no signing key configured; skipping verification",
            )
            return

        import hashlib as _hashlib
        import hmac as _hmac
        expected = _hmac.new(self._signing_key, serialized, _hashlib.sha256).hexdigest()
        if not _hmac.compare_digest(expected, stored_sig):
            raise ValueError(
                "Checkpoint integrity check failed: HMAC mismatch. "
                "Checkpoint data may have been tampered with."
            )

    async def pause(self, run_id: str) -> None:
        """Signal a running workflow to pause at its next opportunity."""
        run_result = self._runs.get(run_id)
        if run_result is None:
            raise ValueError(f"Run not found: {run_id}")
        run_result.run.status = WorkflowRunStatus.PAUSED
        await self._emit_audit(
            AuditEventType.WORKFLOW_PAUSED,
            actor=run_result.run.initiated_by,
            resource_type="workflow_run",
            resource_id=run_id,
            action="paused",
        )

    async def cancel(self, run_id: str) -> None:
        """Cancel a workflow run."""
        run_result = self._runs.get(run_id)
        if run_result is None:
            raise ValueError(f"Run not found: {run_id}")
        run_result.run.status = WorkflowRunStatus.CANCELLED
        run_result.run.completed_at = _utcnow()
        await self._emit_audit(
            AuditEventType.WORKFLOW_CANCELLED,
            actor=run_result.run.initiated_by,
            resource_type="workflow_run",
            resource_id=run_id,
            action="cancelled",
        )

    # -- internals ----------------------------------------------------------

    async def _execute_node(
        self,
        node: NodeDefinition,
        run: WorkflowRun,
        run_result: WorkflowRunResult,
        context: ExecutionContext,
    ) -> NodeResult:
        handler = self._handlers.get(node.handler)
        if handler is None:
            run.status = WorkflowRunStatus.FAILED
            run.error = f"No handler registered for: {node.handler}"
            return NodeResult(output_state=run.state)

        context.config = node.config

        execution = NodeExecution(
            run_id=run.id,
            node_id=node.id,
            node_name=node.name,
            status=NodeExecutionStatus.RUNNING,
            input_state=dict(run.state),
            started_at=_utcnow(),
        )

        retry_policy = node.retry_policy
        max_attempts = retry_policy.max_attempts if retry_policy else 1
        delay = retry_policy.backoff_seconds if retry_policy else 1.0
        multiplier = retry_policy.backoff_multiplier if retry_policy else 1.0

        result: NodeResult | None = None

        for attempt in range(1, max_attempts + 1):
            execution.attempt = attempt
            context.attempt = attempt
            try:
                with tracer.start_as_current_span(
                    "workflow.node.execute",
                    attributes={
                        "workflow.id": run.id,
                        "workflow.node_id": node.id,
                        "workflow.node_type": node.node_type.value
                        if hasattr(node.node_type, "value")
                        else str(node.node_type),
                        "actor.id": run.initiated_by or "",
                    },
                ):
                    result = await handler(run.state, context)
                run.state.update(result.output_state)
                execution.status = NodeExecutionStatus.COMPLETED
                execution.output_state = dict(run.state)
                execution.completed_at = _utcnow()
                if execution.started_at:
                    execution.duration_ms = int(
                        (execution.completed_at - execution.started_at).total_seconds() * 1000
                    )

                logger.info(
                    "node.executed",
                    run_id=run.id,
                    node_id=node.id,
                    attempt=attempt,
                    status="completed",
                )
                break
            except PauseExecutionError:
                run.status = WorkflowRunStatus.PAUSED
                execution.status = NodeExecutionStatus.COMPLETED
                execution.completed_at = _utcnow()
                result = NodeResult(output_state=run.state)
                break
            except WaitForApprovalError:
                run.status = WorkflowRunStatus.WAITING_APPROVAL
                execution.status = NodeExecutionStatus.COMPLETED
                execution.completed_at = _utcnow()
                result = NodeResult(output_state=run.state)
                break
            except WaitForAgentResponseError:
                run.status = WorkflowRunStatus.WAITING_AGENT_RESPONSE
                execution.status = NodeExecutionStatus.COMPLETED
                execution.completed_at = _utcnow()
                result = NodeResult(output_state=run.state)
                break
            except Exception as exc:
                logger.warning(
                    "node.failed",
                    run_id=run.id,
                    node_id=node.id,
                    attempt=attempt,
                    error=str(exc),
                )
                if attempt == max_attempts:
                    execution.status = NodeExecutionStatus.FAILED
                    execution.error = str(exc)
                    execution.completed_at = _utcnow()
                    run.status = WorkflowRunStatus.FAILED
                    run.error = f"Node {node.id} failed: {exc}"
                    result = NodeResult(output_state=run.state)
                else:
                    import asyncio

                    await asyncio.sleep(delay)
                    delay *= multiplier

        run_result.node_executions.append(execution)
        assert result is not None
        return result

    @staticmethod
    def _find_start_node(workflow: WorkflowDefinition) -> NodeDefinition:
        for node in workflow.nodes:
            if node.node_type == NodeType.START:
                return node
        raise ValueError("Workflow has no START node")

    def _resolve_next_node(
        self,
        current_node_id: str,
        state: dict[str, Any],
        edges: list[EdgeDefinition],
    ) -> str | None:
        candidates = [e for e in edges if e.source_node_id == current_node_id]
        candidates.sort(key=lambda e: e.priority, reverse=True)

        for edge in candidates:
            if edge.condition is None:
                return edge.target_node_id
            if self._evaluate_condition(edge.condition, state):
                return edge.target_node_id

        return None

    @staticmethod
    def _evaluate_condition(condition: str, state: dict[str, Any]) -> bool:
        try:
            return safe_eval_condition(condition, state)
        except Exception:
            logger.warning("condition.eval_failed", condition=condition)
            return False

    async def _persist_checkpoint(self, run: WorkflowRun) -> None:
        serialized = json.dumps(run.state, default=str).encode()
        if self._signing_key:
            import hashlib as _hashlib
            import hmac as _hmac
            sig = _hmac.new(self._signing_key, serialized, _hashlib.sha256).hexdigest()
            envelope = json.dumps({
                "data": json.loads(serialized),
                "checkpoint_hmac": sig,
            }, default=str).encode()
            run.checkpoint_data = envelope
        else:
            run.checkpoint_data = serialized
        if self._checkpoint_store is not None and hasattr(self._checkpoint_store, "save"):
            await self._checkpoint_store.save(run.id, run.checkpoint_data)
        logger.debug("checkpoint.saved", run_id=run.id)

    async def _emit_audit(
        self,
        event_type: AuditEventType,
        *,
        actor: str = "system",
        resource_type: str = "",
        resource_id: str = "",
        action: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        event = AuditEvent(
            event_type=event_type,
            actor=actor,
            resource_type=resource_type,
            resource_id=resource_id,
            action=action,
            details=details or {},
        )
        if self._audit_service is not None and hasattr(self._audit_service, "record"):
            await self._audit_service.record(event)
        logger.info("audit.event", event_type=event_type.value, resource_id=resource_id)


@dataclasses.dataclass
class WorkflowRunResult:
    """Wraps a :class:`WorkflowRun` with execution-time tracking data."""

    run: WorkflowRun
    node_executions: list[NodeExecution] = dataclasses.field(default_factory=list)
    current_node_id: str | None = None


class PauseExecutionError(Exception):
    """Raised by handlers that need to pause workflow execution."""


class WaitForApprovalError(Exception):
    """Raised by handlers that need approval before proceeding."""


class WaitForAgentResponseError(Exception):
    """Raised by handlers waiting for agent message responses."""
