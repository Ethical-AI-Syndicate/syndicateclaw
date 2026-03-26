"""Single-skill execution engine — validate, run handler, audit (always)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Protocol

from syndicateclaw.runtime.audit.sink import AuditSink
from syndicateclaw.runtime.contracts.common import ResultStatus, ToolPolicy
from syndicateclaw.runtime.contracts.execution import ExecutionRecord, ExecutionRequest
from syndicateclaw.runtime.contracts.skill_manifest import SkillManifest
from syndicateclaw.runtime.errors import (
    AuditSinkError,
    ExecutionValidationError,
    SkillHandlerMissingError,
)
from syndicateclaw.runtime.execution.context import ToolExecutor, ToolInvoker
from syndicateclaw.runtime.execution.validation import validate_payload_against_schema


class SkillHandler(Protocol):
    def __call__(
        self,
        payload: dict[str, Any],
        *,
        manifest: SkillManifest,
        tool_invoker: ToolInvoker,
    ) -> dict[str, Any]:
        ...


class ExecutionEngine:
    """Runs one skill invocation with mandatory audit emission."""

    def __init__(
        self,
        *,
        audit_sink: AuditSink,
        tool_executor: ToolExecutor | None = None,
    ) -> None:
        if audit_sink is None:
            msg = "audit_sink is required (fail closed)"
            raise AuditSinkError(msg)
        self._audit_sink = audit_sink
        self._tool_executor = tool_executor

    def execute_skill(
        self,
        request: ExecutionRequest,
        manifest: SkillManifest,
        handler: SkillHandler | None,
        *,
        start_time: str,
        end_time: str,
        trigger_reason: str,
    ) -> ExecutionRecord:
        if request.skill.skill_id != manifest.skill_id or request.skill.version != manifest.version:
            msg = "execution request skill ref does not match manifest"
            record = self._failure_record(
                request=request,
                manifest=manifest,
                start_time=start_time,
                end_time=end_time,
                trigger_reason=trigger_reason,
                code="SKILL_REF_MISMATCH",
                message=msg,
            )
            self._emit(record)
            return record

        tools_invoked: list[dict[str, Any]] = []
        tool_invoker = ToolInvoker(
            manifest,
            execution_id=request.execution_id,
            tools_invoked=tools_invoked,
            executor=self._tool_executor,
        )

        try:
            validate_payload_against_schema(
                request.input_payload,
                manifest.input_schema,
                label="input_payload",
            )
        except ExecutionValidationError as e:
            record = self._failure_record(
                request=request,
                manifest=manifest,
                start_time=start_time,
                end_time=end_time,
                trigger_reason=trigger_reason,
                code=type(e).__name__,
                message=str(e),
                tools_invoked=tools_invoked,
            )
            self._emit(record)
            return record

        if handler is None:
            exc = SkillHandlerMissingError(
                f"no handler for {manifest.skill_id}@{manifest.version}",
            )
            record = self._failure_record(
                request=request,
                manifest=manifest,
                start_time=start_time,
                end_time=end_time,
                trigger_reason=trigger_reason,
                code=type(exc).__name__,
                message=str(exc),
                tools_invoked=tools_invoked,
            )
            self._emit(record)
            return record

        try:
            output = handler(
                request.input_payload,
                manifest=manifest,
                tool_invoker=tool_invoker,
            )
        except Exception as e:
            record = self._failure_record(
                request=request,
                manifest=manifest,
                start_time=start_time,
                end_time=end_time,
                trigger_reason=trigger_reason,
                code=type(e).__name__,
                message=str(e),
                tools_invoked=tools_invoked,
                failures=[str(e)],
            )
            self._emit(record)
            return record

        if not isinstance(output, dict):
            msg = "skill handler must return a dict"
            record = self._failure_record(
                request=request,
                manifest=manifest,
                start_time=start_time,
                end_time=end_time,
                trigger_reason=trigger_reason,
                code="INVALID_HANDLER_OUTPUT",
                message=msg,
                tools_invoked=tools_invoked,
            )
            self._emit(record)
            return record

        try:
            validate_payload_against_schema(
                output,
                manifest.output_schema,
                label="output",
            )
        except ExecutionValidationError as e:
            record = self._failure_record(
                request=request,
                manifest=manifest,
                start_time=start_time,
                end_time=end_time,
                trigger_reason=trigger_reason,
                code=type(e).__name__,
                message=str(e),
                tools_invoked=tools_invoked,
                output=output,
            )
            self._emit(record)
            return record

        if manifest.tool_policy == ToolPolicy.EXPLICIT_ALLOWLIST and not manifest.allowed_tools:
            policy_note = (
                f"manifest_tool_policy={manifest.tool_policy.value}; "
                "explicit_allowlist_empty_means_deny_all"
            )
        else:
            policy_note = f"manifest_tool_policy={manifest.tool_policy.value}"
        record = ExecutionRecord(
            execution_id=request.execution_id,
            task_id=request.task_id,
            skill_id=manifest.skill_id,
            version=manifest.version,
            manifest_tool_policy=manifest.tool_policy.value,
            trigger_reason=trigger_reason,
            inputs_used=[request.input_payload],
            tools_invoked=tools_invoked,
            decisions=["handler completed", policy_note],
            failures_detected=[],
            result_status=ResultStatus.SUCCESS,
            output=output,
            start_time=start_time,
            end_time=end_time,
        )
        self._emit(record)
        return record

    def _emit(self, record: ExecutionRecord) -> None:
        try:
            self._audit_sink.append(record)
        except Exception as e:
            msg = f"audit sink failed: {e}"
            raise AuditSinkError(msg) from e

    def _failure_record(
        self,
        *,
        request: ExecutionRequest,
        manifest: SkillManifest,
        start_time: str,
        end_time: str,
        trigger_reason: str,
        code: str,
        message: str,
        tools_invoked: list[dict[str, Any]] | None = None,
        failures: list[str] | None = None,
        output: dict[str, Any] | None = None,
    ) -> ExecutionRecord:
        return ExecutionRecord(
            execution_id=request.execution_id,
            task_id=request.task_id,
            skill_id=manifest.skill_id,
            version=manifest.version,
            manifest_tool_policy=manifest.tool_policy.value,
            trigger_reason=trigger_reason,
            inputs_used=[request.input_payload],
            tools_invoked=tools_invoked or [],
            decisions=[],
            failures_detected=failures or [message],
            result_status=ResultStatus.FAILED,
            output=output,
            error_code=code,
            error_message=message,
            start_time=start_time,
            end_time=end_time,
        )


def build_handler_map(
    mapping: Mapping[tuple[str, str], SkillHandler],
) -> Callable[[str, str], SkillHandler | None]:
    """Explicit handler registry — no mutable process-wide state."""

    frozen = dict(mapping)

    def resolve(skill_id: str, version: str) -> SkillHandler | None:
        return frozen.get((skill_id, version))

    return resolve
