from __future__ import annotations

import enum
from datetime import UTC, datetime
from typing import Any, Self

from pydantic import BaseModel, Field
from ulid import ULID

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class WorkflowRunStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    WAITING_AGENT_RESPONSE = "WAITING_AGENT_RESPONSE"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class NodeExecutionStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class NodeType(str, enum.Enum):
    START = "START"
    END = "END"
    ACTION = "ACTION"
    DECISION = "DECISION"
    APPROVAL = "APPROVAL"
    AGENT = "AGENT"
    CHECKPOINT = "CHECKPOINT"


class ToolRiskLevel(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ToolExecutionStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"


class PolicyEffect(str, enum.Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"


class ApprovalStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class MemoryType(str, enum.Enum):
    EPISODIC = "EPISODIC"
    SEMANTIC = "SEMANTIC"
    STRUCTURED = "STRUCTURED"


class MemoryDeletionStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    MARKED_FOR_DELETION = "MARKED_FOR_DELETION"
    DELETED = "DELETED"


class AuditEventType(str, enum.Enum):
    # Workflow events
    WORKFLOW_CREATED = "WORKFLOW_CREATED"
    WORKFLOW_STARTED = "WORKFLOW_STARTED"
    WORKFLOW_COMPLETED = "WORKFLOW_COMPLETED"
    WORKFLOW_FAILED = "WORKFLOW_FAILED"
    WORKFLOW_PAUSED = "WORKFLOW_PAUSED"
    WORKFLOW_RESUMED = "WORKFLOW_RESUMED"
    WORKFLOW_CANCELLED = "WORKFLOW_CANCELLED"

    # Node events
    NODE_STARTED = "NODE_STARTED"
    NODE_COMPLETED = "NODE_COMPLETED"
    NODE_FAILED = "NODE_FAILED"
    NODE_SKIPPED = "NODE_SKIPPED"
    NODE_RETRIED = "NODE_RETRIED"

    # Tool events
    TOOL_REGISTERED = "TOOL_REGISTERED"
    TOOL_UPDATED = "TOOL_UPDATED"
    TOOL_DISABLED = "TOOL_DISABLED"
    TOOL_EXECUTION_STARTED = "TOOL_EXECUTION_STARTED"
    TOOL_EXECUTION_COMPLETED = "TOOL_EXECUTION_COMPLETED"
    TOOL_EXECUTION_FAILED = "TOOL_EXECUTION_FAILED"
    TOOL_EXECUTION_TIMED_OUT = "TOOL_EXECUTION_TIMED_OUT"

    # Memory events
    MEMORY_CREATED = "MEMORY_CREATED"
    MEMORY_UPDATED = "MEMORY_UPDATED"
    MEMORY_ACCESSED = "MEMORY_ACCESSED"
    MEMORY_DELETED = "MEMORY_DELETED"
    MEMORY_EXPIRED = "MEMORY_EXPIRED"

    # Policy events
    POLICY_CREATED = "POLICY_CREATED"
    POLICY_UPDATED = "POLICY_UPDATED"
    POLICY_DELETED = "POLICY_DELETED"
    POLICY_EVALUATED = "POLICY_EVALUATED"
    POLICY_DENIED = "POLICY_DENIED"

    # Approval events
    APPROVAL_REQUESTED = "APPROVAL_REQUESTED"
    APPROVAL_APPROVED = "APPROVAL_APPROVED"
    APPROVAL_REJECTED = "APPROVAL_REJECTED"
    APPROVAL_EXPIRED = "APPROVAL_EXPIRED"

    # HTTP request events
    HTTP_REQUEST = "HTTP_REQUEST"

    # Decision ledger events
    DECISION_RECORDED = "DECISION_RECORDED"

    # Memory trust events
    MEMORY_TRUST_DECAYED = "MEMORY_TRUST_DECAYED"
    MEMORY_CONFLICT_DETECTED = "MEMORY_CONFLICT_DETECTED"
    MEMORY_VALIDATED = "MEMORY_VALIDATED"

    # Replay events
    INPUT_SNAPSHOT_CAPTURED = "INPUT_SNAPSHOT_CAPTURED"
    REPLAY_STARTED = "REPLAY_STARTED"
    REPLAY_DIVERGENCE_DETECTED = "REPLAY_DIVERGENCE_DETECTED"

    # Inference / provider layer (Phase 1)
    INFERENCE_STARTED = "INFERENCE_STARTED"
    INFERENCE_COMPLETED = "INFERENCE_COMPLETED"
    INFERENCE_FAILED = "INFERENCE_FAILED"
    INFERENCE_STREAM_STARTED = "INFERENCE_STREAM_STARTED"
    INFERENCE_STREAM_COMPLETED = "INFERENCE_STREAM_COMPLETED"
    INFERENCE_STREAM_FAILED = "INFERENCE_STREAM_FAILED"

    # Catalog sync (models.dev enrichment)
    CATALOG_SYNC_STARTED = "CATALOG_SYNC_STARTED"
    CATALOG_SYNC_COMPLETED = "CATALOG_SYNC_COMPLETED"
    CATALOG_SYNC_FAILED = "CATALOG_SYNC_FAILED"
    CATALOG_SYNC_ANOMALY_ABORTED = "CATALOG_SYNC_ANOMALY_ABORTED"

    # Plugin lifecycle (v1.5.0) — values match audit string convention
    PLUGIN_HOOK_INVOKED = "plugin.hook_invoked"
    PLUGIN_HOOK_COMPLETED = "plugin.hook_completed"
    PLUGIN_HOOK_FAILED = "plugin.hook_failed"
    PLUGIN_HOOK_TIMEOUT = "plugin.hook_timeout"
    PLUGIN_SECURITY_VIOLATION = "plugin.security_violation"


class MemorySourceType(str, enum.Enum):
    HUMAN = "HUMAN"
    SYSTEM = "SYSTEM"
    DERIVED = "DERIVED"
    EXTERNAL = "EXTERNAL"
    LLM = "LLM"


class DecisionDomain(str, enum.Enum):
    POLICY = "POLICY"
    TOOL_EXECUTION = "TOOL_EXECUTION"
    MEMORY_WRITE = "MEMORY_WRITE"
    MEMORY_READ = "MEMORY_READ"
    APPROVAL = "APPROVAL"
    WORKFLOW_ROUTING = "WORKFLOW_ROUTING"


class ReplayMode(str, enum.Enum):
    LIVE = "LIVE"
    DETERMINISTIC = "DETERMINISTIC"


class ApprovalScopeType(str, enum.Enum):
    SINGLE_ACTION = "SINGLE_ACTION"
    TIME_WINDOW = "TIME_WINDOW"
    CONDITIONAL = "CONDITIONAL"
    BLANKET = "BLANKET"


class DeadLetterStatus(str, enum.Enum):
    PENDING = "PENDING"
    RETRIED = "RETRIED"
    FAILED_PERMANENT = "FAILED_PERMANENT"
    DISCARDED = "DISCARDED"
    RESOLVED = "RESOLVED"


# ---------------------------------------------------------------------------
# Base entity
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(UTC)


class BaseEntity(BaseModel):
    """Common base for all persisted domain objects."""

    id: str = Field(default_factory=lambda: str(ULID()), description="ULID primary key")
    created_at: datetime = Field(default_factory=_utcnow, description="Creation timestamp (UTC)")
    updated_at: datetime = Field(
        default_factory=_utcnow, description="Last-updated timestamp (UTC)"
    )

    model_config = {"from_attributes": True}

    @classmethod
    def new(cls, **kwargs: Any) -> Self:
        """Factory that generates a fresh ULID and sets timestamps."""
        now = _utcnow()
        return cls(id=str(ULID()), created_at=now, updated_at=now, **kwargs)


# ---------------------------------------------------------------------------
# Supporting models (must be defined before domain classes that reference them)
# ---------------------------------------------------------------------------


class MemoryTrustMetadata(BaseModel):
    """Trust scoring and decay metadata for memory records."""

    trust_score: float = Field(
        default=1.0, ge=0.0, le=1.0,
        description="Current trust score (decays over time, downgraded on conflict)",
    )
    source_type: MemorySourceType = Field(
        default=MemorySourceType.SYSTEM, description="Origin classification of this memory"
    )
    last_validated_at: datetime | None = Field(
        default=None, description="Last time this record was explicitly validated"
    )
    validation_count: int = Field(default=0, ge=0, description="Number of times validated")
    conflict_set_id: str | None = Field(
        default=None,
        description="Links conflicting records together for resolution",
    )
    decay_rate: float = Field(
        default=0.01, ge=0.0, le=1.0,
        description="Trust decay per day (score -= decay_rate * days_since_validation)",
    )
    frozen: bool = Field(
        default=False, description="If True, trust score does not decay (human-validated)"
    )


class VersionManifest(BaseModel):
    """Frozen version snapshot attached to every workflow run."""

    workflow_version: str = Field(..., description="Workflow definition version")
    tool_versions: dict[str, str] = Field(
        default_factory=dict, description="Map of tool_name -> version at execution time"
    )
    policy_version: str = Field(default="", description="Policy ruleset hash or version identifier")
    memory_schema_version: str = Field(default="", description="Memory schema version")
    platform_version: str = Field(default="0.1.0", description="SyndicateClaw platform version")
    captured_at: datetime = Field(
        default_factory=_utcnow,
        description="When the manifest was frozen",
    )


class ToolSandboxPolicy(BaseModel):
    """Network and resource constraints for tool execution."""

    allowed_domains: list[str] = Field(
        default_factory=list,
        description="Allowlisted outbound domains (empty = all public allowed with SSRF checks)",
    )
    allowed_protocols: list[str] = Field(
        default_factory=lambda: ["https"], description="Allowed URL schemes"
    )
    max_request_bytes: int = Field(
        default=1_048_576,
        ge=0,
        description="Max outbound payload size (1MB)",
    )
    max_response_bytes: int = Field(
        default=10_485_760,
        ge=0,
        description="Max inbound payload size (10MB)",
    )
    network_isolation: bool = Field(
        default=False, description="If True, tool runs with no network access"
    )
    filesystem_read: bool = Field(default=False, description="Whether tool may read filesystem")
    filesystem_write: bool = Field(default=False, description="Whether tool may write filesystem")
    subprocess_allowed: bool = Field(
        default=False,
        description="Whether tool may spawn subprocesses",
    )


# ---------------------------------------------------------------------------
# Workflow domain
# ---------------------------------------------------------------------------


class RetryPolicy(BaseModel):
    max_attempts: int = Field(default=3, ge=1, description="Maximum number of retry attempts")
    backoff_seconds: float = Field(default=1.0, ge=0, description="Initial backoff in seconds")
    backoff_multiplier: float = Field(
        default=2.0, ge=1.0, description="Multiplier applied to backoff after each attempt"
    )
    retryable_errors: list[str] = Field(
        default_factory=list, description="Error class names eligible for retry"
    )


class NodeDefinition(BaseModel):
    id: str = Field(..., description="Unique node identifier within the workflow")
    name: str = Field(..., description="Human-readable node name")
    node_type: NodeType = Field(..., description="Semantic type of this node")
    handler: str = Field(..., description="Dotted Python path to the handler callable")
    config: dict[str, Any] = Field(default_factory=dict, description="Arbitrary handler config")
    retry_policy: RetryPolicy | None = Field(
        default=None, description="Retry behaviour for this node"
    )
    timeout_seconds: int | None = Field(
        default=None, ge=1, description="Per-execution timeout in seconds"
    )


class EdgeDefinition(BaseModel):
    source_node_id: str = Field(..., description="ID of the source node")
    target_node_id: str = Field(..., description="ID of the target node")
    condition: str | None = Field(
        default=None, description="Optional expression evaluated to decide traversal"
    )
    priority: int = Field(default=0, description="Higher priority edges are evaluated first")


class WorkflowDefinition(BaseEntity):
    name: str = Field(..., description="Workflow name")
    version: str = Field(..., description="Semantic version string")
    description: str = Field(default="", description="Human-readable description")
    nodes: list[NodeDefinition] = Field(default_factory=list, description="Graph node definitions")
    edges: list[EdgeDefinition] = Field(default_factory=list, description="Graph edge definitions")
    owner: str = Field(..., description="Identity of the workflow owner")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Arbitrary metadata bag")


class WorkflowRun(BaseEntity):
    workflow_id: str = Field(..., description="Reference to the parent WorkflowDefinition")
    workflow_version: str = Field(..., description="Snapshot of workflow version at run time")
    status: WorkflowRunStatus = Field(
        default=WorkflowRunStatus.PENDING, description="Current run status"
    )
    state: dict[str, Any] = Field(default_factory=dict, description="Typed state bag for the run")
    parent_run_id: str | None = Field(
        default=None, description="Parent run ID when this is a sub-workflow"
    )
    initiated_by: str = Field(..., description="Actor that initiated the run")
    started_at: datetime | None = Field(default=None, description="Timestamp when run started")
    completed_at: datetime | None = Field(default=None, description="Timestamp when run completed")
    error: str | None = Field(default=None, description="Error message if run failed")
    checkpoint_data: bytes | None = Field(
        default=None, description="Serialised checkpoint for replay"
    )
    tags: dict[str, str] = Field(default_factory=dict, description="Arbitrary key-value tags")
    version_manifest: VersionManifest | None = Field(
        default=None, description="Frozen version snapshot at run start"
    )
    replay_mode: ReplayMode = Field(
        default=ReplayMode.LIVE, description="Whether this run uses live or frozen inputs"
    )


class NodeExecution(BaseEntity):
    run_id: str = Field(..., description="Parent WorkflowRun ID")
    node_id: str = Field(..., description="NodeDefinition ID within the workflow")
    node_name: str = Field(..., description="Snapshot of node name at execution time")
    status: NodeExecutionStatus = Field(
        default=NodeExecutionStatus.PENDING, description="Execution status"
    )
    attempt: int = Field(default=1, ge=1, description="Current attempt number")
    input_state: dict[str, Any] = Field(
        default_factory=dict, description="State snapshot fed into this node"
    )
    output_state: dict[str, Any] = Field(
        default_factory=dict, description="State snapshot produced by this node"
    )
    started_at: datetime | None = Field(default=None, description="Execution start time")
    completed_at: datetime | None = Field(default=None, description="Execution end time")
    error: str | None = Field(default=None, description="Error details if failed")
    duration_ms: int | None = Field(
        default=None, ge=0, description="Elapsed wall-clock milliseconds"
    )


# ---------------------------------------------------------------------------
# Tool domain
# ---------------------------------------------------------------------------


class ToolAuditConfig(BaseModel):
    log_input: bool = Field(default=True, description="Whether to log tool input in audit trail")
    log_output: bool = Field(default=True, description="Whether to log tool output in audit trail")
    redact_fields: list[str] = Field(
        default_factory=list, description="Field paths to redact before logging"
    )


class Tool(BaseEntity):
    name: str = Field(..., description="Unique tool name")
    description: str = Field(default="", description="Human-readable tool description")
    version: str = Field(..., description="Tool version string")
    input_schema: dict[str, Any] = Field(
        default_factory=dict, description="JSON Schema for tool input"
    )
    output_schema: dict[str, Any] = Field(
        default_factory=dict, description="JSON Schema for tool output"
    )
    risk_level: ToolRiskLevel = Field(default=ToolRiskLevel.LOW, description="Risk classification")
    required_permissions: list[str] = Field(
        default_factory=list, description="Permissions the caller must hold"
    )
    side_effects: list[str] = Field(
        default_factory=list, description="Declared side-effects (e.g. 'sends_email', 'writes_db')"
    )
    timeout_seconds: int = Field(default=30, ge=1, description="Execution timeout in seconds")
    max_retries: int = Field(default=0, ge=0, description="Maximum automatic retries on failure")
    idempotent: bool = Field(default=False, description="Whether re-execution is safe")
    enabled: bool = Field(default=True, description="Whether this tool is currently available")
    owner: str = Field(..., description="Identity of the tool owner")
    audit_config: ToolAuditConfig = Field(
        default_factory=ToolAuditConfig, description="Audit logging configuration"
    )
    sandbox_policy: ToolSandboxPolicy = Field(
        default_factory=ToolSandboxPolicy, description="Network and resource sandbox constraints"
    )


class ToolExecution(BaseEntity):
    run_id: str = Field(..., description="Parent WorkflowRun ID")
    node_execution_id: str = Field(..., description="Parent NodeExecution ID")
    tool_name: str = Field(..., description="Name of the tool invoked")
    status: ToolExecutionStatus = Field(
        default=ToolExecutionStatus.PENDING, description="Execution status"
    )
    input_data: dict[str, Any] = Field(default_factory=dict, description="Input payload")
    output_data: dict[str, Any] | None = Field(
        default=None, description="Output payload on success"
    )
    error: str | None = Field(default=None, description="Error details on failure")
    started_at: datetime | None = Field(default=None, description="Execution start time")
    completed_at: datetime | None = Field(default=None, description="Execution end time")
    duration_ms: int | None = Field(
        default=None, ge=0, description="Elapsed wall-clock milliseconds"
    )
    approved_by: str | None = Field(default=None, description="Actor who approved this execution")
    policy_decision_id: str | None = Field(default=None, description="Associated PolicyDecision ID")


# ---------------------------------------------------------------------------
# Memory domain
# ---------------------------------------------------------------------------


class MemoryLineage(BaseModel):
    parent_ids: list[str] = Field(default_factory=list, description="IDs of parent memory records")
    workflow_run_id: str | None = Field(
        default=None, description="WorkflowRun that produced this memory"
    )
    node_execution_id: str | None = Field(
        default=None, description="NodeExecution that produced this memory"
    )
    tool_name: str | None = Field(default=None, description="Tool that produced this memory")
    derivation_method: str | None = Field(
        default=None, description="How this memory was derived (e.g. 'llm_extraction', 'merge')"
    )


class MemoryRecord(BaseEntity):
    namespace: str = Field(..., description="Logical namespace for grouping")
    key: str = Field(..., description="Lookup key within the namespace")
    value: Any = Field(..., description="Stored value (arbitrary JSON-compatible)")
    memory_type: MemoryType = Field(..., description="Classification of memory kind")
    source: str = Field(..., description="What produced this memory record")
    actor: str = Field(..., description="Who or what triggered creation")
    confidence: float = Field(
        default=1.0, ge=0.0, le=1.0, description="Confidence score between 0 and 1"
    )
    access_policy: str = Field(default="default", description="Named access-control policy")
    lineage: MemoryLineage = Field(default_factory=MemoryLineage, description="Provenance tracking")
    trust: MemoryTrustMetadata = Field(
        default_factory=MemoryTrustMetadata, description="Trust scoring and decay metadata"
    )
    ttl_seconds: int | None = Field(default=None, ge=1, description="Time-to-live in seconds")
    expires_at: datetime | None = Field(default=None, description="Absolute expiration timestamp")
    deletion_status: MemoryDeletionStatus = Field(
        default=MemoryDeletionStatus.ACTIVE, description="Soft-delete lifecycle status"
    )
    deleted_at: datetime | None = Field(
        default=None, description="When the record was marked deleted"
    )
    tags: dict[str, str] = Field(default_factory=dict, description="Arbitrary key-value tags")


# ---------------------------------------------------------------------------
# Policy domain
# ---------------------------------------------------------------------------


class PolicyCondition(BaseModel):
    field: str = Field(..., description="Dot-path to the field being evaluated")
    operator: str = Field(
        ..., description="Comparison operator (eq, neq, in, not_in, gt, lt, matches)"
    )
    value: Any = Field(..., description="Value to compare against")


class ApprovalScope(BaseModel):
    """Defines the boundaries of what an approval covers."""

    scope_type: ApprovalScopeType = Field(
        default=ApprovalScopeType.SINGLE_ACTION, description="What kind of scope"
    )
    allowed_actions: list[str] = Field(
        default_factory=list,
        description=(
            "Specific action identifiers this approval covers "
            "(empty = the one requested action)"
        ),
    )
    time_window_seconds: int | None = Field(
        default=None, ge=1,
        description="If scope_type=TIME_WINDOW, approval valid for this many seconds",
    )
    conditions: list[PolicyCondition] = Field(
        default_factory=list,
        description="If scope_type=CONDITIONAL, these must remain true for approval to hold",
    )
    max_uses: int | None = Field(
        default=None, ge=1, description="Maximum number of times this approval can be used"
    )
    uses_remaining: int | None = Field(default=None, ge=0, description="Remaining uses")
    context_hash: str = Field(
        default="",
        description="Hash of the context at approval time; re-approval required if context changes",
    )
    redact_fields: list[str] = Field(
        default_factory=list, description="Fields that must be redacted before action execution"
    )


class PolicyRule(BaseEntity):
    name: str = Field(..., description="Unique policy rule name")
    description: str = Field(default="", description="Human-readable description")
    resource_type: str = Field(
        ..., description="Resource kind this rule applies to (tool, memory, workflow)"
    )
    resource_pattern: str = Field(
        ..., description="Glob or exact match pattern for the resource name"
    )
    effect: PolicyEffect = Field(..., description="Action to take when conditions match")
    conditions: list[PolicyCondition] = Field(
        default_factory=list, description="Conditions that must all be true"
    )
    priority: int = Field(default=0, description="Higher priority rules are evaluated first")
    enabled: bool = Field(default=True, description="Whether this rule is active")
    owner: str = Field(..., description="Identity of the rule owner")


class PolicyDecision(BaseEntity):
    rule_id: str = Field(..., description="PolicyRule that produced this decision")
    rule_name: str = Field(..., description="Snapshot of rule name at evaluation time")
    effect: PolicyEffect = Field(..., description="Resolved effect")
    resource_type: str = Field(..., description="Resource type evaluated")
    resource_id: str = Field(..., description="Resource ID evaluated")
    actor: str = Field(..., description="Actor who triggered evaluation")
    reason: str = Field(..., description="Human-readable explanation of the decision")
    conditions_evaluated: list[dict[str, Any]] = Field(
        default_factory=list, description="Snapshot of condition evaluation results"
    )
    all_rules_considered: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Every rule that was evaluated, including non-matching, "
            "with reasons for non-match"
        ),
    )
    input_attributes: dict[str, Any] = Field(
        default_factory=dict,
        description="Snapshot of all attributes used in evaluation for full reproducibility",
    )
    decision_record_id: str | None = Field(
        default=None, description="Link to the corresponding DecisionRecord"
    )
    timestamp: datetime = Field(default_factory=_utcnow, description="When the decision was made")


# ---------------------------------------------------------------------------
# Approval domain
# ---------------------------------------------------------------------------


class ApprovalRequest(BaseEntity):
    run_id: str = Field(..., description="Parent WorkflowRun ID")
    node_execution_id: str = Field(..., description="Parent NodeExecution ID")
    tool_name: str | None = Field(
        default=None, description="Tool requiring approval, if applicable"
    )
    action_description: str = Field(..., description="Human-readable description of the action")
    risk_level: ToolRiskLevel = Field(..., description="Risk classification of the action")
    status: ApprovalStatus = Field(
        default=ApprovalStatus.PENDING, description="Current approval status"
    )
    requested_by: str = Field(..., description="Actor who requested approval")
    assigned_to: list[str] = Field(
        default_factory=list, description="Actors eligible to approve/reject"
    )
    decided_by: str | None = Field(default=None, description="Actor who made the final decision")
    decided_at: datetime | None = Field(default=None, description="Timestamp of the decision")
    decision_reason: str | None = Field(default=None, description="Explanation for the decision")
    expires_at: datetime = Field(..., description="Deadline for the approval decision")
    context: dict[str, Any] = Field(
        default_factory=dict, description="Additional context for the approver"
    )
    scope: ApprovalScope = Field(
        default_factory=ApprovalScope, description="Boundaries and constraints of this approval"
    )


# ---------------------------------------------------------------------------
# Audit domain
# ---------------------------------------------------------------------------


class AuditEvent(BaseEntity):
    event_type: AuditEventType = Field(..., description="Categorised event type")
    actor: str = Field(..., description="Identity of the actor that triggered the event")
    resource_type: str = Field(..., description="Type of the affected resource")
    resource_id: str = Field(..., description="ID of the affected resource")
    action: str = Field(..., description="Short verb describing the action")
    details: dict[str, Any] = Field(
        default_factory=dict, description="Arbitrary event-specific payload"
    )
    parent_event_id: str | None = Field(
        default=None, description="Parent event for causal chaining"
    )
    trace_id: str | None = Field(default=None, description="OpenTelemetry trace ID")
    span_id: str | None = Field(default=None, description="OpenTelemetry span ID")
    actor_principal_id: str | None = Field(
        default=None, description="FK to principals table (populated during RBAC rollout)"
    )
    real_actor: str | None = Field(
        default=None, description="Original actor during impersonation sessions"
    )
    impersonation_session_id: str | None = Field(
        default=None, description="Active impersonation session ID"
    )
    resource_scope_type: str | None = Field(
        default=None, description="Denormalized owning scope type of the target resource"
    )
    resource_scope_id: str | None = Field(
        default=None, description="Denormalized owning scope ID of the target resource"
    )


# ---------------------------------------------------------------------------
# Decision ledger
# ---------------------------------------------------------------------------


class DecisionRecord(BaseEntity):
    """Structured, immutable record of every consequential decision."""

    domain: DecisionDomain = Field(..., description="Which subsystem produced this decision")
    decision_type: str = Field(
        ...,
        description=(
            "Specific decision kind (e.g. 'tool_allowed', 'memory_write_permitted')"
        ),
    )
    actor: str = Field(..., description="Identity of the actor")
    run_id: str | None = Field(default=None, description="Associated workflow run")
    node_execution_id: str | None = Field(default=None, description="Associated node execution")

    inputs: dict[str, Any] = Field(
        default_factory=dict,
        description="Frozen snapshot of decision inputs",
    )
    rules_evaluated: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "All rules evaluated, not just the match — includes why others didn't match"
        ),
    )
    matched_rule: str | None = Field(
        default=None,
        description="ID of the rule that produced the outcome",
    )
    effect: str = Field(..., description="Outcome (allow, deny, require_approval, etc.)")
    justification: str = Field(
        ...,
        description="Human-readable explanation of why this decision was reached",
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Decision confidence score",
    )
    side_effects: list[str] = Field(
        default_factory=list,
        description="Declared side effects that will/did result from this decision",
    )
    context_hash: str = Field(
        default="",
        description="SHA-256 of serialized inputs for integrity verification",
    )
    trace_id: str | None = Field(default=None, description="OpenTelemetry trace ID for correlation")


# ---------------------------------------------------------------------------
# Input snapshot for deterministic replay
# ---------------------------------------------------------------------------


class InputSnapshot(BaseEntity):
    """Captures all external inputs at a point in execution for deterministic replay."""

    run_id: str = Field(..., description="Associated workflow run")
    node_execution_id: str = Field(..., description="Node that produced/consumed these inputs")
    snapshot_type: str = Field(
        ...,
        description=(
            "What was captured: 'tool_response', 'memory_read', "
            "'external_api', 'llm_response'"
        ),
    )
    source_identifier: str = Field(
        ..., description="Tool name, memory key, API URL, etc."
    )
    request_data: dict[str, Any] = Field(default_factory=dict, description="What was requested")
    response_data: dict[str, Any] = Field(default_factory=dict, description="What was received")
    content_hash: str = Field(
        default="",
        description="SHA-256 of response_data for integrity check",
    )
    captured_at: datetime = Field(
        default_factory=_utcnow,
        description="When the snapshot was taken",
    )


# ---------------------------------------------------------------------------
# Dead letter record (persistent)
# ---------------------------------------------------------------------------


class DeadLetterRecord(BaseEntity):
    """Persistent record of a failed event for classification and recovery."""

    event_type: str = Field(..., description="Original event type")
    event_payload: dict[str, Any] = Field(default_factory=dict, description="Serialized event")
    error_message: str = Field(..., description="Why processing failed")
    error_category: str = Field(
        default="transient",
        description="Classification: 'transient', 'permanent', 'unknown'",
    )
    status: DeadLetterStatus = Field(default=DeadLetterStatus.PENDING)
    retry_count: int = Field(default=0, ge=0, description="Number of retry attempts")
    max_retries: int = Field(
        default=3,
        ge=0,
        description="Maximum retry attempts before permanent failure",
    )
    last_retry_at: datetime | None = Field(default=None)
    resolved_at: datetime | None = Field(default=None)
    resolved_by: str | None = Field(default=None, description="Actor who resolved this")
