from __future__ import annotations

import dataclasses
import json
import operator
import re
from datetime import UTC, datetime
from typing import Any, Protocol, cast, runtime_checkable

import structlog
from opentelemetry import trace
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from ulid import ULID

from syndicateclaw.db.models import ApprovalRequest as ApprovalRequestRow
from syndicateclaw.db.models import NodeExecution as NodeExecutionRow
from syndicateclaw.db.models import WorkflowRun as WorkflowRunRow
from syndicateclaw.models import (
    ApprovalRequest,
    ApprovalStatus,
    AuditEvent,
    AuditEventType,
    EdgeDefinition,
    NodeDefinition,
    NodeExecution,
    NodeExecutionStatus,
    NodeType,
    ToolRiskLevel,
    WorkflowDefinition,
    WorkflowRun,
    WorkflowRunStatus,
)
from syndicateclaw.orchestrator.exceptions import WaitForApprovalError, WorkflowCycleDetected

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)

MAX_WORKFLOW_STEPS = 1000
_STEP_LIMIT_PATH_LENGTH = 50

__all__ = [
    "ExecutionContext",
    "NodeHandler",
    "NodeResult",
    "PauseExecutionError",
    "WaitForAgentResponseError",
    "WaitForApprovalError",
    "WorkflowCycleDetected",
    "WorkflowEngine",
    "WorkflowRunResult",
    "safe_eval_condition",
]


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
    message_service: Any = None


@dataclasses.dataclass
class NodeResult:
    """Value returned by a node handler."""

    output_state: dict[str, Any]
    next_node_id: str | None = None
    should_checkpoint: bool = False


@runtime_checkable
class NodeHandler(Protocol):
    async def __call__(self, state: dict[str, Any], context: ExecutionContext) -> NodeResult: ...


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
                raise ValueError(f"Unexpected character at position {pos}: {expression[pos:]}")
            kind = m.lastgroup
            if kind is None:
                raise ValueError(f"Regex match missing group name at position {pos}")
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
        state_cache: Any = None,
        plugin_executor: Any = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        max_steps: int = MAX_WORKFLOW_STEPS,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        if max_steps > MAX_WORKFLOW_STEPS:
            raise ValueError(f"max_steps cannot exceed {MAX_WORKFLOW_STEPS}")
        self._handlers = handler_registry
        self._checkpoint_store = checkpoint_store
        self._audit_service = audit_service
        self._signing_key = signing_key
        self._state_cache = state_cache
        self._plugin_executor = plugin_executor
        self._session_factory = session_factory
        self._max_steps = max_steps
        self._runs: dict[str, WorkflowRunResult] = {}

    async def _maybe_cache_state(self, run: WorkflowRun) -> None:
        if self._state_cache is None:
            return
        st = run.status.value if isinstance(run.status, WorkflowRunStatus) else str(run.status)
        await self._state_cache.set(run.id, dict(run.state), st)

    # -- public API ---------------------------------------------------------

    async def execute(
        self, run: WorkflowRun, context: ExecutionContext, *, workflow: WorkflowDefinition
    ) -> WorkflowRunResult:
        """Execute a workflow run from its START node to completion."""
        run_result = self._runs.get(run.id) or WorkflowRunResult(run=run)
        self._runs[run.id] = run_result

        run.status = WorkflowRunStatus.RUNNING
        run.started_at = _utcnow()
        await self._maybe_cache_state(run)

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
        resume_from = run.state.get("_resume_from")
        current_node_id: str | None = (
            run_result.current_node_id
            or (str(resume_from) if isinstance(resume_from, str) else None)
            or start_node.id
        )

        step_count = 0
        visited_nodes: list[str] = []
        visited_node_set: set[str] = set()

        while current_node_id is not None:
            step_count += 1
            run_result.step_count = step_count
            run_result.visited_nodes = list(visited_nodes)

            if current_node_id in visited_node_set:
                first_seen = visited_nodes.index(current_node_id)
                await self._raise_execution_bound_failure(
                    run=run,
                    workflow=workflow,
                    reason="cycle_detected",
                    message=f"Cycle detected at node {current_node_id}",
                    cycle_path=visited_nodes[first_seen:],
                    step_count=step_count,
                )

            if step_count > self._max_steps:
                await self._raise_execution_bound_failure(
                    run=run,
                    workflow=workflow,
                    reason="step_limit_exceeded",
                    message=f"Workflow execution exceeded max_steps={self._max_steps}",
                    cycle_path=visited_nodes[-_STEP_LIMIT_PATH_LENGTH:],
                    step_count=step_count,
                )

            visited_nodes.append(current_node_id)
            visited_node_set.add(current_node_id)
            run_result.visited_nodes = list(visited_nodes)

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

            result = await self._execute_node(node, run, run_result, context, workflow)
            await self._maybe_cache_state(run)

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
                await self._maybe_cache_state(run)
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

    async def resume(self, run_id: str, from_node: str | None = None) -> WorkflowRunResult:
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

    async def resume_after_approval(
        self,
        *,
        run_id: str,
        approval_id: str,
        workflow: WorkflowDefinition,
        context: ExecutionContext,
    ) -> WorkflowRunResult:
        """Resume a waiting run after an approved approval has been consumed.

        The approval row is locked and marked consumed before execution continues.
        A second call for the same approval raises ``ValueError`` before a handler
        can run, which keeps side effects one-shot.
        """
        if self._session_factory is None:
            run_result = self._runs.get(run_id)
            if run_result is None:
                raise ValueError(f"Run not found: {run_id}")
            run = run_result.run
            resume = self._approval_resume_payload(run.state, approval_id)
            run.state["_approval_resume"] = resume
            run.state["_approved_approval_id"] = approval_id
            run.status = WorkflowRunStatus.RUNNING
            return await self.execute(run, context, workflow=workflow)

        async with self._session_factory() as session, session.begin():
            approval_stmt = (
                select(ApprovalRequestRow)
                .where(
                    ApprovalRequestRow.id == approval_id,
                    ApprovalRequestRow.run_id == run_id,
                )
                .with_for_update()
            )
            approval = (await session.execute(approval_stmt)).scalar_one_or_none()
            if approval is None:
                raise ValueError(f"Approval request {approval_id} not found for run {run_id}")
            if approval.status != ApprovalStatus.APPROVED.value:
                raise ValueError(f"Approval request {approval_id} is not APPROVED")
            approval_context = dict(approval.context or {})
            if approval_context.get("consumed_at"):
                raise ValueError(f"Approval request {approval_id} has already been consumed")

            run_row = await session.get(WorkflowRunRow, run_id, with_for_update=True)
            if run_row is None:
                raise ValueError(f"Run not found: {run_id}")
            if run_row.status != WorkflowRunStatus.WAITING_APPROVAL.value:
                raise ValueError(f"Run {run_id} is not waiting for approval")

            run_state = dict(run_row.state or {})
            resume_node = self._resume_node_from_state(run_state, approval_context)
            resume_payload = {
                "approval_id": approval_id,
                "node_id": resume_node,
                "tool_name": approval.tool_name,
                "resumed_at": _utcnow().isoformat(),
            }
            run_state["_approval_resume"] = resume_payload
            run_state["_approved_approval_id"] = approval_id
            run_state["_resume_from"] = resume_node

            approval_context["consumed_at"] = _utcnow().isoformat()
            approval_context["consumed_for_run_id"] = run_id
            approval_context["resume_node_id"] = resume_node
            approval.context = approval_context
            approval.updated_at = _utcnow()

            run_row.status = WorkflowRunStatus.RUNNING.value
            run_row.state = run_state
            run_row.updated_at = _utcnow()
            await session.flush()

            run = WorkflowRun.model_validate(run_row)

        run_result = self._runs.get(run.id) or WorkflowRunResult(run=run)
        run_result.run = run
        run_result.current_node_id = str(run.state.get("_resume_from", ""))
        self._runs[run.id] = run_result
        return await self.execute(run, context, workflow=workflow)

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

    async def _raise_execution_bound_failure(
        self,
        *,
        run: WorkflowRun,
        workflow: WorkflowDefinition,
        reason: str,
        message: str,
        cycle_path: list[str],
        step_count: int,
    ) -> None:
        run.status = WorkflowRunStatus.FAILED
        run.completed_at = _utcnow()
        run.error = reason
        run.state["_failure_reason"] = reason
        run.state["_execution_bound"] = {
            "reason": reason,
            "cycle_path": list(cycle_path),
            "step_count": step_count,
            "failed_at": run.completed_at.isoformat(),
        }
        await self._maybe_cache_state(run)
        await self._persist_run_failure(run)
        await self._emit_workflow_failed_audit(
            run=run,
            workflow=workflow,
            reason=reason,
            cycle_path=cycle_path,
            step_count=step_count,
        )
        raise WorkflowCycleDetected(
            message,
            run_id=run.id,
            cycle_path=cycle_path,
            step_count=step_count,
        )

    async def _persist_run_failure(self, run: WorkflowRun) -> None:
        if self._session_factory is None:
            return
        async with self._session_factory() as session, session.begin():
            await self._upsert_run(session, run)

    async def _emit_workflow_failed_audit(
        self,
        *,
        run: WorkflowRun,
        workflow: WorkflowDefinition,
        reason: str,
        cycle_path: list[str],
        step_count: int,
    ) -> None:
        try:
            await self._emit_audit(
                AuditEventType.WORKFLOW_FAILED,
                actor=run.initiated_by or "system:engine",
                resource_type="workflow",
                resource_id=workflow.id,
                action="failed",
                details={
                    "run_id": run.id,
                    "reason": reason,
                    "cycle_path": list(cycle_path),
                    "step_count": step_count,
                    "timestamp": _utcnow().isoformat(),
                },
            )
        except Exception:
            logger.exception(
                "workflow_failed_audit_failed",
                run_id=run.id,
                reason=reason,
                step_count=step_count,
            )

    async def pause(self, run_id: str) -> None:
        """Signal a running workflow to pause at its next opportunity."""
        run_result = self._runs.get(run_id)
        if run_result is None:
            raise ValueError(f"Run not found: {run_id}")
        run_result.run.status = WorkflowRunStatus.PAUSED
        await self._maybe_cache_state(run_result.run)
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
        await self._maybe_cache_state(run_result.run)
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
        workflow: WorkflowDefinition,
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
        approval_interrupt: WaitForApprovalError | None = None
        boundary_persisted = False

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
            except WaitForApprovalError as exc:
                run.status = WorkflowRunStatus.WAITING_APPROVAL
                execution.status = NodeExecutionStatus.WAITING_APPROVAL
                execution.completed_at = _utcnow()
                execution.output_state = dict(run.state)
                if execution.started_at:
                    execution.duration_ms = int(
                        (execution.completed_at - execution.started_at).total_seconds() * 1000
                    )
                approval_interrupt = await self._prepare_approval_interrupt(
                    exc=exc,
                    node=node,
                    run=run,
                    execution=execution,
                )
                boundary_persisted = True
                result = NodeResult(output_state=run.state)
                break
            except WaitForAgentResponseError:
                run.status = WorkflowRunStatus.WAITING_AGENT_RESPONSE
                execution.status = NodeExecutionStatus.WAITING_AGENT_RESPONSE
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
        if result is None:
            raise RuntimeError(f"Handler for node {node.id} returned None")

        if approval_interrupt is not None:
            raise approval_interrupt

        self._clear_consumed_resume_marker(run, node.id)

        if not boundary_persisted:
            await self._persist_run_and_node(run, execution)

        if self._plugin_executor is not None and execution.status == NodeExecutionStatus.COMPLETED:
            ns = run.state.get("_namespace", "default")
            await self._plugin_executor.invoke_on_node_execute(
                run_id=run.id,
                workflow_id=workflow.id,
                actor=run.initiated_by or "system",
                namespace=ns,
                state=dict(run.state),
                node_id=node.id,
                output_state=dict(result.output_state),
            )
        return result

    async def _prepare_approval_interrupt(
        self,
        *,
        exc: WaitForApprovalError,
        node: NodeDefinition,
        run: WorkflowRun,
        execution: NodeExecution,
    ) -> WaitForApprovalError:
        request = self._approval_request_for_interrupt(exc, node, run, execution)
        run.state["_waiting_approval"] = {
            "approval_id": request.id,
            "tool_name": request.tool_name or "",
            "node_id": node.id,
            "run_id": run.id,
            "requested_at": _utcnow().isoformat(),
        }
        run.state["_resume_from"] = node.id
        run.state["_pending_approval_id"] = request.id
        await self._persist_checkpoint(run)
        await self._maybe_cache_state(run)
        await self._persist_approval_boundary(run, execution, request)

        persisted_state = self._jsonable(run.state)
        enriched = exc.with_boundary_context(
            approval_id=request.id,
            tool_name=request.tool_name or "",
            node_id=node.id,
            run_id=run.id,
            persisted_state=persisted_state,
        )
        await self._emit_approval_required_audit(enriched, run)
        return enriched

    def _approval_request_for_interrupt(
        self,
        exc: WaitForApprovalError,
        node: NodeDefinition,
        run: WorkflowRun,
        execution: NodeExecution,
    ) -> ApprovalRequest:
        raw = self._approval_payload_from_state(run.state, exc.approval_id)
        if raw is not None:
            request = ApprovalRequest.model_validate(raw)
        else:
            request = ApprovalRequest(
                id=exc.approval_id or str(ULID()),
                run_id=run.id,
                node_execution_id=execution.id,
                tool_name=exc.tool_name or node.handler,
                action_description=f"Approval required for node {node.id}",
                risk_level=ToolRiskLevel.MEDIUM,
                requested_by=run.initiated_by or "system:engine",
                assigned_to=[],
                expires_at=_utcnow(),
                context={},
            )

        request.run_id = run.id
        request.node_execution_id = execution.id
        if not request.tool_name:
            request.tool_name = exc.tool_name or node.handler
        context = dict(request.context or {})
        context.update(
            {
                "run_id": run.id,
                "node_id": node.id,
                "resume_node_id": node.id,
                "state": self._jsonable(run.state),
            }
        )
        request.context = context
        return request

    @staticmethod
    def _approval_payload_from_state(
        state: dict[str, Any],
        approval_id: str,
    ) -> dict[str, Any] | None:
        pending = state.get("_pending_approval")
        if isinstance(pending, dict) and (
            not approval_id or str(pending.get("id", "")) == approval_id
        ):
            return pending

        pending_many = state.get("_pending_approvals")
        if isinstance(pending_many, list):
            for item in reversed(pending_many):
                if isinstance(item, dict) and (
                    not approval_id or str(item.get("id", "")) == approval_id
                ):
                    return item
        return None

    async def _persist_approval_boundary(
        self,
        run: WorkflowRun,
        execution: NodeExecution,
        request: ApprovalRequest,
    ) -> None:
        if self._session_factory is None:
            return

        async with self._session_factory() as session, session.begin():
            await self._upsert_run(session, run)
            await self._upsert_node_execution(session, execution)
            existing = await session.get(ApprovalRequestRow, request.id)
            if existing is None:
                session.add(
                    ApprovalRequestRow(
                        id=request.id,
                        run_id=request.run_id,
                        node_execution_id=request.node_execution_id,
                        tool_name=request.tool_name or "",
                        action_description=request.action_description,
                        risk_level=request.risk_level.value,
                        status=request.status.value,
                        requested_by=request.requested_by,
                        assigned_to=request.assigned_to,
                        expires_at=request.expires_at,
                        context=self._jsonable(request.context),
                        scope=request.scope.model_dump(mode="json"),
                    )
                )
            else:
                existing.node_execution_id = request.node_execution_id
                existing.tool_name = request.tool_name or ""
                existing.action_description = request.action_description
                existing.risk_level = request.risk_level.value
                existing.status = request.status.value
                existing.requested_by = request.requested_by
                cast(Any, existing).assigned_to = request.assigned_to
                existing.expires_at = request.expires_at
                existing.context = self._jsonable(request.context)
                existing.scope = request.scope.model_dump(mode="json")
                existing.updated_at = _utcnow()
            await session.flush()

    async def _persist_run_and_node(
        self,
        run: WorkflowRun,
        execution: NodeExecution,
    ) -> None:
        if self._session_factory is None:
            return
        async with self._session_factory() as session, session.begin():
            await self._upsert_run(session, run)
            await self._upsert_node_execution(session, execution)

    async def _upsert_run(self, session: AsyncSession, run: WorkflowRun) -> None:
        row = await session.get(WorkflowRunRow, run.id)
        version_manifest = (
            run.version_manifest.model_dump(mode="json") if run.version_manifest else None
        )
        if row is None:
            session.add(
                WorkflowRunRow(
                    id=run.id,
                    workflow_id=run.workflow_id,
                    workflow_version=run.workflow_version,
                    status=run.status.value,
                    state=self._jsonable(run.state),
                    parent_run_id=run.parent_run_id,
                    initiated_by=run.initiated_by,
                    started_at=run.started_at,
                    completed_at=run.completed_at,
                    error=run.error,
                    checkpoint_data=run.checkpoint_data,
                    tags=run.tags,
                    version_manifest=version_manifest,
                    replay_mode=run.replay_mode.value,
                )
            )
            await session.flush()
            return

        row.status = run.status.value
        row.state = self._jsonable(run.state)
        row.started_at = run.started_at
        row.completed_at = run.completed_at
        row.error = run.error
        row.checkpoint_data = run.checkpoint_data
        row.tags = run.tags
        row.version_manifest = version_manifest
        row.replay_mode = run.replay_mode.value
        row.updated_at = _utcnow()
        await session.flush()

    async def _upsert_node_execution(
        self,
        session: AsyncSession,
        execution: NodeExecution,
    ) -> None:
        row = await session.get(NodeExecutionRow, execution.id)
        if row is None:
            session.add(
                NodeExecutionRow(
                    id=execution.id,
                    run_id=execution.run_id,
                    node_id=execution.node_id,
                    node_name=execution.node_name,
                    status=execution.status.value,
                    attempt=execution.attempt,
                    input_state=self._jsonable(execution.input_state),
                    output_state=self._jsonable(execution.output_state),
                    started_at=execution.started_at,
                    completed_at=execution.completed_at,
                    error=execution.error,
                    duration_ms=execution.duration_ms,
                )
            )
            await session.flush()
            return

        row.status = execution.status.value
        row.attempt = execution.attempt
        row.input_state = self._jsonable(execution.input_state)
        row.output_state = self._jsonable(execution.output_state)
        row.started_at = execution.started_at
        row.completed_at = execution.completed_at
        row.error = execution.error
        row.duration_ms = execution.duration_ms
        row.updated_at = _utcnow()
        await session.flush()

    async def _emit_approval_required_audit(
        self,
        interrupt: WaitForApprovalError,
        run: WorkflowRun,
    ) -> None:
        try:
            policy_version = ""
            if run.version_manifest is not None:
                policy_version = run.version_manifest.policy_version
            await self._emit_audit(
                AuditEventType.APPROVAL_REQUIRED,
                actor=run.initiated_by or "system:engine",
                resource_type="workflow_run",
                resource_id=run.id,
                action="approval_required",
                details={
                    "run_id": interrupt.run_id,
                    "node_id": interrupt.node_id,
                    "tool_name": interrupt.tool_name,
                    "approval_id": interrupt.approval_id,
                    "policy_version": policy_version,
                    "timestamp": _utcnow().isoformat(),
                },
            )
        except Exception:
            logger.exception(
                "approval_required_audit_failed",
                run_id=interrupt.run_id,
                node_id=interrupt.node_id,
                approval_id=interrupt.approval_id,
            )

    @staticmethod
    def _jsonable(value: Any) -> Any:
        return json.loads(json.dumps(value, default=str))

    @staticmethod
    def _resume_node_from_state(
        state: dict[str, Any],
        approval_context: dict[str, Any],
    ) -> str:
        resume_node = approval_context.get("resume_node_id") or state.get("_resume_from")
        if not resume_node:
            waiting = state.get("_waiting_approval")
            if isinstance(waiting, dict):
                resume_node = waiting.get("node_id")
        if not resume_node:
            raise ValueError("Persisted approval checkpoint is missing resume node")
        return str(resume_node)

    @staticmethod
    def _approval_resume_payload(state: dict[str, Any], approval_id: str) -> dict[str, Any]:
        waiting = state.get("_waiting_approval")
        if not isinstance(waiting, dict) or str(waiting.get("approval_id", "")) != approval_id:
            raise ValueError(f"Approval {approval_id} is not the waiting approval for this run")
        return {
            "approval_id": approval_id,
            "node_id": str(waiting.get("node_id", "")),
            "tool_name": str(waiting.get("tool_name", "")),
            "resumed_at": _utcnow().isoformat(),
        }

    @staticmethod
    def _clear_consumed_resume_marker(run: WorkflowRun, node_id: str) -> None:
        resume = run.state.get("_approval_resume")
        if not isinstance(resume, dict) or resume.get("node_id") != node_id:
            return
        run.state.pop("_approval_resume", None)
        run.state.pop("_approved_approval_id", None)
        run.state.pop("_resume_from", None)
        run.state.pop("_waiting_approval", None)

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
            envelope = json.dumps(
                {
                    "data": json.loads(serialized),
                    "checkpoint_hmac": sig,
                },
                default=str,
            ).encode()
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
        elif self._audit_service is not None and hasattr(self._audit_service, "emit"):
            await self._audit_service.emit(event)
        logger.info("audit.event", event_type=event_type.value, resource_id=resource_id)


@dataclasses.dataclass
class WorkflowRunResult:
    """Wraps a :class:`WorkflowRun` with execution-time tracking data."""

    run: WorkflowRun
    node_executions: list[NodeExecution] = dataclasses.field(default_factory=list)
    current_node_id: str | None = None
    step_count: int = 0
    visited_nodes: list[str] = dataclasses.field(default_factory=list)


class PauseExecutionError(Exception):
    """Raised by handlers that need to pause workflow execution."""


class WaitForAgentResponseError(Exception):
    """Raised by handlers waiting for agent message responses."""
