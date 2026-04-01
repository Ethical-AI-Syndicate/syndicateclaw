from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Table,
    Text,
    UniqueConstraint,
    desc,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class WorkflowDefinition(Base):
    __tablename__ = "workflow_definitions"
    __table_args__ = (
        UniqueConstraint(
            "name",
            "version",
            "namespace",
            name="uq_workflow_definitions_name_version_namespace",
        ),
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(Text, nullable=False)
    namespace: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="default",
        server_default="default",
    )
    description: Mapped[str | None] = mapped_column(Text)
    nodes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    edges: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    owner: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    current_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    updated_by: Mapped[str | None] = mapped_column(Text)
    owner_principal_id: Mapped[str | None] = mapped_column(
        ForeignKey("principals.id", ondelete="SET NULL")
    )
    owning_scope_type: Mapped[str | None] = mapped_column(Text)
    owning_scope_id: Mapped[str | None] = mapped_column(Text)

    runs: Mapped[list[WorkflowRun]] = relationship(back_populates="workflow", lazy="raise")


class WorkflowVersion(Base):
    __tablename__ = "workflow_versions"
    __table_args__ = (
        UniqueConstraint("workflow_id", "version", name="uq_workflow_version"),
        Index("idx_workflow_versions_wf", "workflow_id", "version"),
    )

    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_definitions.id", ondelete="CASCADE"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    definition: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    changed_by: Mapped[str] = mapped_column(Text, nullable=False)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    comment: Mapped[str | None] = mapped_column(Text)


class WorkflowVersionArchive(Base):
    __tablename__ = "workflow_versions_archive"
    __table_args__ = (Index("idx_workflow_versions_archive_wf", "workflow_id", "version"),)

    workflow_id: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    definition: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    changed_by: Mapped[str] = mapped_column(Text, nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (
        Index("ix_workflow_runs_status", "status"),
        Index("ix_workflow_runs_initiated_by", "initiated_by"),
        Index("idx_workflow_runs_namespace_status", "namespace", "status"),
    )

    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_definitions.id", ondelete="CASCADE"), nullable=False
    )
    workflow_version: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="PENDING")
    state: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    parent_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="SET NULL")
    )
    initiated_by: Mapped[str | None] = mapped_column(Text)
    initiated_by_principal_id: Mapped[str | None] = mapped_column(
        ForeignKey("principals.id", ondelete="SET NULL")
    )
    owning_scope_type: Mapped[str | None] = mapped_column(Text)
    owning_scope_id: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]
    error: Mapped[str | None] = mapped_column(Text)
    checkpoint_data: Mapped[bytes | None] = mapped_column(LargeBinary)
    tags: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    version_manifest: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    replay_mode: Mapped[str] = mapped_column(Text, nullable=False, default="LIVE")

    workflow: Mapped[WorkflowDefinition] = relationship(back_populates="runs", lazy="selectin")
    parent_run: Mapped[WorkflowRun | None] = relationship(
        remote_side="WorkflowRun.id", lazy="selectin"
    )
    node_executions: Mapped[list[NodeExecution]] = relationship(back_populates="run", lazy="raise")
    parent_schedule_id: Mapped[str | None]
    triggered_by: Mapped[str | None]
    namespace: Mapped[str] = mapped_column(Text, nullable=False, default="default")


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = (
        UniqueConstraint("name", "namespace", name="uq_agents_name_namespace"),
        Index("idx_agents_namespace_status", "namespace", "status"),
        Index("idx_agents_capabilities", "capabilities", postgresql_using="gin"),
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    namespace: Mapped[str] = mapped_column(Text, nullable=False)
    capabilities: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        default=list,
        server_default="{}",
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="OFFLINE",
        server_default="OFFLINE",
    )
    registered_by: Mapped[str] = mapped_column(Text, nullable=False)
    heartbeat_at: Mapped[datetime | None]
    deregistered_at: Mapped[datetime | None]


class AgentMessage(Base):
    __tablename__ = "agent_messages"
    __table_args__ = (
        Index("idx_messages_recipient_status", "recipient", "status"),
        Index("idx_messages_topic_status", "topic", "status"),
        Index("idx_messages_conversation", "conversation_id"),
        Index("idx_messages_sender", "sender"),
    )

    conversation_id: Mapped[str] = mapped_column(Text, nullable=False)
    sender: Mapped[str] = mapped_column(Text, nullable=False)
    recipient: Mapped[str | None] = mapped_column(Text)
    topic: Mapped[str | None] = mapped_column(Text)
    message_type: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
    )
    priority: Mapped[str] = mapped_column(Text, nullable=False, default="NORMAL")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="PENDING")
    ttl_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=3600)
    hop_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parent_message_id: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None]
    delivered_at: Mapped[datetime | None]
    acked_at: Mapped[datetime | None]
    namespace: Mapped[str] = mapped_column(Text, nullable=False, default="default")


class TopicSubscription(Base):
    __tablename__ = "topic_subscriptions"
    __table_args__ = (
        UniqueConstraint("agent_id", "topic", name="uq_topic_subscriptions"),
        Index("idx_topic_subs_topic", "topic", "namespace"),
    )

    agent_id: Mapped[str] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    namespace: Mapped[str] = mapped_column(Text, nullable=False)


class NodeExecution(Base):
    __tablename__ = "node_executions"
    __table_args__ = (
        Index("ix_node_executions_run_id", "run_id"),
        Index("ix_node_executions_status", "status"),
    )

    run_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False
    )
    node_id: Mapped[str] = mapped_column(Text, nullable=False)
    node_name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    input_state: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    output_state: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    started_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]
    error: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)

    run: Mapped[WorkflowRun] = relationship(back_populates="node_executions", lazy="selectin")


class Tool(Base):
    __tablename__ = "tools"
    __table_args__ = (UniqueConstraint("name"),)

    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    version: Mapped[str] = mapped_column(Text, nullable=False, default="1.0.0")
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    output_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    risk_level: Mapped[str] = mapped_column(Text, nullable=False, default="low")
    required_permissions: Mapped[dict[str, Any]] = mapped_column(JSONB, default=list)
    side_effects: Mapped[dict[str, Any]] = mapped_column(JSONB, default=list)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=30)
    max_retries: Mapped[int] = mapped_column(Integer, default=0)
    idempotent: Mapped[bool] = mapped_column(default=False)
    enabled: Mapped[bool] = mapped_column(default=True)
    owner: Mapped[str | None] = mapped_column(Text)
    audit_config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    sandbox_policy: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class ToolExecution(Base):
    __tablename__ = "tool_executions"
    __table_args__ = (
        Index("ix_tool_executions_run_id", "run_id"),
        Index("ix_tool_executions_tool_name", "tool_name"),
    )

    run_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False
    )
    node_execution_id: Mapped[str] = mapped_column(
        ForeignKey("node_executions.id", ondelete="CASCADE"), nullable=False
    )
    tool_name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    input_data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    output_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    approved_by: Mapped[str | None] = mapped_column(Text)
    policy_decision_id: Mapped[str | None] = mapped_column(Text)

    run: Mapped[WorkflowRun] = relationship(lazy="selectin")
    node_execution: Mapped[NodeExecution] = relationship(lazy="selectin")


class MemoryRecord(Base):
    __tablename__ = "memory_records"
    __table_args__ = (
        UniqueConstraint("namespace", "key"),
        Index("ix_memory_records_namespace_key", "namespace", "key"),
        Index("ix_memory_records_memory_type", "memory_type"),
        Index("ix_memory_records_deletion_status", "deletion_status"),
    )

    namespace: Mapped[str] = mapped_column(Text, nullable=False)
    key: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    memory_type: Mapped[str] = mapped_column(Text, nullable=False, default="ephemeral")
    source: Mapped[str | None] = mapped_column(Text)
    actor: Mapped[str | None] = mapped_column(Text)
    actor_principal_id: Mapped[str | None] = mapped_column(
        ForeignKey("principals.id", ondelete="SET NULL")
    )
    owning_scope_type: Mapped[str | None] = mapped_column(Text)
    owning_scope_id: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    access_policy: Mapped[str] = mapped_column(Text, nullable=False, default="private")
    lineage: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    ttl_seconds: Mapped[int | None] = mapped_column(Integer)
    expires_at: Mapped[datetime | None]
    deletion_status: Mapped[str] = mapped_column(Text, nullable=False, default="ACTIVE")
    deleted_at: Mapped[datetime | None]
    tags: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    trust_score: Mapped[float | None] = mapped_column(Float, default=1.0)
    source_type: Mapped[str] = mapped_column(Text, nullable=False, default="SYSTEM")
    last_validated_at: Mapped[datetime | None]
    validation_count: Mapped[int] = mapped_column(Integer, default=0)
    conflict_set_id: Mapped[str | None] = mapped_column(Text)
    decay_rate: Mapped[float | None] = mapped_column(Float, default=0.01)
    trust_frozen: Mapped[bool] = mapped_column(default=False)


class PolicyRule(Base):
    __tablename__ = "policy_rules"
    __table_args__ = (
        UniqueConstraint("name", "namespace", name="uq_policy_rules_name_namespace"),
        Index("ix_policy_rules_resource_type", "resource_type"),
        Index("ix_policy_rules_enabled", "enabled"),
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    namespace: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="default",
        server_default="default",
    )
    description: Mapped[str | None] = mapped_column(Text)
    resource_type: Mapped[str] = mapped_column(Text, nullable=False)
    resource_pattern: Mapped[str] = mapped_column(Text, nullable=False)
    effect: Mapped[str] = mapped_column(Text, nullable=False, default="deny")
    conditions: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    enabled: Mapped[bool] = mapped_column(default=True)
    owner: Mapped[str | None] = mapped_column(Text)
    owning_scope_type: Mapped[str | None] = mapped_column(Text)
    owning_scope_id: Mapped[str | None] = mapped_column(Text)


class PolicyDecision(Base):
    __tablename__ = "policy_decisions"
    __table_args__ = (
        Index("ix_policy_decisions_rule_id", "rule_id"),
        Index("ix_policy_decisions_resource", "resource_type", "resource_id"),
        Index("ix_policy_decisions_actor", "actor"),
    )

    rule_id: Mapped[str] = mapped_column(Text, nullable=False)
    rule_name: Mapped[str] = mapped_column(Text, nullable=False)
    effect: Mapped[str] = mapped_column(Text, nullable=False)
    resource_type: Mapped[str] = mapped_column(Text, nullable=False)
    resource_id: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    conditions_evaluated: Mapped[dict[str, Any]] = mapped_column(JSONB, default=list)
    all_rules_considered: Mapped[dict[str, Any]] = mapped_column(JSONB, default=list)
    input_attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    decision_record_id: Mapped[str | None] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC),
    )


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"
    __table_args__ = (
        Index("ix_approval_requests_status", "status"),
        Index("ix_approval_requests_run_id", "run_id"),
    )

    run_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False
    )
    node_execution_id: Mapped[str] = mapped_column(
        ForeignKey("node_executions.id", ondelete="CASCADE"), nullable=False
    )
    tool_name: Mapped[str] = mapped_column(Text, nullable=False)
    action_description: Mapped[str | None] = mapped_column(Text)
    risk_level: Mapped[str] = mapped_column(Text, nullable=False, default="low")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    requested_by: Mapped[str | None] = mapped_column(Text)
    assigned_to: Mapped[dict[str, Any]] = mapped_column(JSONB, default=list)
    decided_by: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None]
    decision_reason: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None]
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    scope: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    owning_scope_type: Mapped[str | None] = mapped_column(Text)
    owning_scope_id: Mapped[str | None] = mapped_column(Text)

    run: Mapped[WorkflowRun] = relationship(lazy="selectin")
    node_execution: Mapped[NodeExecution] = relationship(lazy="selectin")


# Append-only audit log. Consider range-partitioning on created_at for
# high-volume deployments (e.g. PARTITION BY RANGE (created_at)).
class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_event_type", "event_type"),
        Index("ix_audit_events_actor", "actor"),
        Index("ix_audit_events_resource", "resource_type", "resource_id"),
        Index("ix_audit_events_trace_id", "trace_id"),
        Index("ix_audit_events_resource_scope", "resource_scope_type", "resource_scope_id"),
        Index("ix_audit_events_actor_principal", "actor_principal_id"),
        Index("idx_audit_events_actor_created", "actor", desc("created_at")),
    )

    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str] = mapped_column(Text, nullable=False)
    actor_principal_id: Mapped[str | None] = mapped_column(
        ForeignKey("principals.id", ondelete="SET NULL")
    )
    resource_type: Mapped[str] = mapped_column(Text, nullable=False)
    resource_id: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    parent_event_id: Mapped[str | None] = mapped_column(Text)
    trace_id: Mapped[str | None] = mapped_column(Text)
    span_id: Mapped[str | None] = mapped_column(Text)
    real_actor: Mapped[str | None] = mapped_column(Text)
    impersonation_session_id: Mapped[str | None] = mapped_column(Text)
    resource_scope_type: Mapped[str | None] = mapped_column(Text)
    resource_scope_id: Mapped[str | None] = mapped_column(Text)


class DecisionRecord(Base):
    """Append-only structured decision ledger."""

    __tablename__ = "decision_records"
    __table_args__ = (
        Index("ix_decision_records_domain", "domain"),
        Index("ix_decision_records_run_id", "run_id"),
        Index("ix_decision_records_actor", "actor"),
        Index("ix_decision_records_trace_id", "trace_id"),
    )

    domain: Mapped[str] = mapped_column(Text, nullable=False)
    decision_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str] = mapped_column(Text, nullable=False)
    run_id: Mapped[str | None] = mapped_column(Text)
    node_execution_id: Mapped[str | None] = mapped_column(Text)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    rules_evaluated: Mapped[dict[str, Any]] = mapped_column(JSONB, default=list)
    matched_rule: Mapped[str | None] = mapped_column(Text)
    effect: Mapped[str] = mapped_column(Text, nullable=False)
    justification: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    side_effects: Mapped[dict[str, Any]] = mapped_column(JSONB, default=list)
    context_hash: Mapped[str] = mapped_column(Text, nullable=False, default="")
    trace_id: Mapped[str | None] = mapped_column(Text)


class InputSnapshot(Base):
    """Captures external inputs for deterministic replay."""

    __tablename__ = "input_snapshots"
    __table_args__ = (
        Index("ix_input_snapshots_run_id", "run_id"),
        Index("ix_input_snapshots_node_execution_id", "node_execution_id"),
        Index("ix_input_snapshots_snapshot_type", "snapshot_type"),
    )

    run_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False
    )
    node_execution_id: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot_type: Mapped[str] = mapped_column(Text, nullable=False)
    source_identifier: Mapped[str] = mapped_column(Text, nullable=False)
    request_data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    response_data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False, default="")
    captured_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC),
    )


class DeadLetterRecord(Base):
    """Persistent dead letter queue with classification."""

    __tablename__ = "dead_letter_records"
    __table_args__ = (
        Index("ix_dead_letter_records_status", "status"),
        Index("ix_dead_letter_records_error_category", "error_category"),
    )

    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    event_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    error_category: Mapped[str] = mapped_column(Text, nullable=False, default="transient")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="PENDING")
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    last_retry_at: Mapped[datetime | None]
    resolved_at: Mapped[datetime | None]
    resolved_by: Mapped[str | None] = mapped_column(Text)


class ApiKey(Base):
    """Database-backed API key with lifecycle tracking."""

    __tablename__ = "api_keys"
    __table_args__ = (
        Index("ix_api_keys_key_hash", "key_hash", unique=True),
        Index("ix_api_keys_actor", "actor"),
    )

    key_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    key_prefix: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    revoked: Mapped[bool] = mapped_column(default=False)
    revoked_at: Mapped[datetime | None]
    revoked_by: Mapped[str | None] = mapped_column(Text)
    last_used_at: Mapped[datetime | None]
    expires_at: Mapped[datetime | None]
    actor_principal_id: Mapped[str | None] = mapped_column(
        ForeignKey("principals.id", ondelete="SET NULL")
    )
    scopes: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        default=list,
        server_default="{}",
        comment=(
            "Empty array intentionally grants full access for v1.0 backward "
            "compatibility. See v1.1.0 spec section 4.3.2."
        ),
    )


# ---------------------------------------------------------------------------
# RBAC tables (Phase 0 — Gate 2)
# ---------------------------------------------------------------------------


class Principal(Base):
    """Identity record for users, service accounts, and teams."""

    __tablename__ = "principals"
    __table_args__ = (UniqueConstraint("principal_type", "name"),)

    principal_type: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    tenant_id: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(default=True)

    team_memberships: Mapped[list[TeamMembership]] = relationship(
        back_populates="principal",
        foreign_keys="TeamMembership.principal_id",
        lazy="selectin",
    )
    role_assignments: Mapped[list[RoleAssignment]] = relationship(
        back_populates="principal",
        lazy="selectin",
    )


class TeamMembership(Base):
    __tablename__ = "team_memberships"
    __table_args__ = (
        UniqueConstraint("principal_id", "team_id"),
        Index("ix_team_memberships_team_id", "team_id"),
    )

    principal_id: Mapped[str] = mapped_column(
        ForeignKey("principals.id", ondelete="CASCADE"),
        nullable=False,
    )
    team_id: Mapped[str] = mapped_column(
        ForeignKey("principals.id", ondelete="CASCADE"),
        nullable=False,
    )
    granted_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC),
    )
    granted_by: Mapped[str] = mapped_column(Text, nullable=False)

    principal: Mapped[Principal] = relationship(
        foreign_keys=[principal_id],
        lazy="selectin",
    )
    team: Mapped[Principal] = relationship(
        foreign_keys=[team_id],
        lazy="selectin",
    )


class Role(Base):
    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("name", "scope_type"),)

    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    built_in: Mapped[bool] = mapped_column(default=False)
    permissions: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=list)
    inherits_from: Mapped[str | None] = mapped_column(Text)
    display_base: Mapped[str | None] = mapped_column(Text)
    scope_type: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str] = mapped_column(Text, nullable=False)


class RoleAssignment(Base):
    __tablename__ = "role_assignments"
    __table_args__ = (
        Index("ix_role_assignments_principal_scope", "principal_id", "scope_type", "scope_id"),
        Index("ix_role_assignments_role_id", "role_id"),
    )

    principal_id: Mapped[str] = mapped_column(
        ForeignKey("principals.id", ondelete="CASCADE"),
        nullable=False,
    )
    role_id: Mapped[str] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"),
        nullable=False,
    )
    scope_type: Mapped[str] = mapped_column(Text, nullable=False)
    scope_id: Mapped[str] = mapped_column(Text, nullable=False)
    granted_by: Mapped[str] = mapped_column(Text, nullable=False)
    granted_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC),
    )
    expires_at: Mapped[datetime | None]
    revoked: Mapped[bool] = mapped_column(default=False)
    revoked_at: Mapped[datetime | None]
    revoked_by: Mapped[str | None] = mapped_column(Text)
    transitional: Mapped[bool] = mapped_column(default=False)

    principal: Mapped[Principal] = relationship(back_populates="role_assignments", lazy="selectin")
    role: Mapped[Role] = relationship(lazy="selectin")


class DenyAssignment(Base):
    __tablename__ = "deny_assignments"
    __table_args__ = (
        Index("ix_deny_assignments_principal_permission", "principal_id", "permission"),
    )

    principal_id: Mapped[str] = mapped_column(
        ForeignKey("principals.id", ondelete="CASCADE"),
        nullable=False,
    )
    permission: Mapped[str] = mapped_column(Text, nullable=False)
    scope_type: Mapped[str] = mapped_column(Text, nullable=False)
    scope_id: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    granted_by: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime | None]


class NamespaceBinding(Base):
    __tablename__ = "namespace_bindings"
    __table_args__ = (
        Index("ix_namespace_bindings_team_id", "team_id"),
        Index("ix_namespace_bindings_pattern", "namespace_pattern"),
    )

    namespace_pattern: Mapped[str] = mapped_column(Text, nullable=False)
    team_id: Mapped[str] = mapped_column(
        ForeignKey("principals.id", ondelete="CASCADE"),
        nullable=False,
    )
    access_level: Mapped[str] = mapped_column(Text, nullable=False)
    granted_by: Mapped[str] = mapped_column(Text, nullable=False)


class ImpersonationSession(Base):
    __tablename__ = "impersonation_sessions"
    __table_args__ = (
        Index("ix_impersonation_sessions_real", "real_principal_id"),
        Index("ix_impersonation_sessions_effective", "effective_principal_id"),
    )

    real_principal_id: Mapped[str] = mapped_column(
        ForeignKey("principals.id", ondelete="CASCADE"),
        nullable=False,
    )
    effective_principal_id: Mapped[str] = mapped_column(
        ForeignKey("principals.id", ondelete="CASCADE"),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    approval_reference: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(nullable=False)
    ended_at: Mapped[datetime | None]
    max_duration_seconds: Mapped[int] = mapped_column(Integer, default=3600)
    permissions_restricted: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class ShadowEvaluation(Base):
    """Phase 1 shadow RBAC evaluation record."""

    __tablename__ = "shadow_evaluations"
    __table_args__ = (
        Index("ix_shadow_evaluations_disagreement", "agreement", "disagreement_type"),
        Index("ix_shadow_evaluations_timestamp", "created_at"),
        Index("ix_shadow_evaluations_route", "route_name"),
        Index("ix_shadow_evaluations_actor", "actor"),
    )

    request_id: Mapped[str | None] = mapped_column(Text)
    trace_id: Mapped[str | None] = mapped_column(Text)
    route_name: Mapped[str] = mapped_column(Text, nullable=False)
    http_method: Mapped[str] = mapped_column(Text, nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str] = mapped_column(Text, nullable=False)
    principal_id: Mapped[str | None] = mapped_column(Text)
    team_context: Mapped[str | None] = mapped_column(Text)
    team_context_valid: Mapped[bool | None]
    required_permission: Mapped[str | None] = mapped_column(Text)
    resolved_scope_type: Mapped[str | None] = mapped_column(Text)
    resolved_scope_id: Mapped[str | None] = mapped_column(Text)
    rbac_decision: Mapped[str | None] = mapped_column(Text)
    rbac_deny_reason: Mapped[str | None] = mapped_column(Text)
    rbac_matched_assignments: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=list)
    rbac_matched_denies: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=list)
    rbac_permission_source: Mapped[str | None] = mapped_column(Text)
    legacy_decision: Mapped[str | None] = mapped_column(Text)
    legacy_deny_reason: Mapped[str | None] = mapped_column(Text)
    agreement: Mapped[bool] = mapped_column(nullable=False, default=True)
    disagreement_type: Mapped[str | None] = mapped_column(Text)
    cache_hit: Mapped[bool] = mapped_column(default=False)
    evaluation_latency_us: Mapped[int] = mapped_column(Integer, default=0)


# ---------------------------------------------------------------------------
# Inference / provider layer (Phase 1) — YAML is authoritative for topology;
# these tables store idempotency, catalog materialization, and audit evidence.
# ---------------------------------------------------------------------------


class InferenceEnvelope(Base):
    """Idempotency envelope: one row per idempotency_key (unique).

    request_hash must be SHA-256 hex from syndicateclaw.inference.hashing.canonical_json_hash.
    """

    __tablename__ = "inference_request_envelopes"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_inference_request_envelopes_idempotency_key"),
        Index(
            "ix_inference_request_envelopes_stale_sweep",
            "status",
            "updated_at",
        ),
        Index("ix_inference_request_envelopes_inference_id", "inference_id"),
        Index("ix_inference_request_envelopes_trace_id", "trace_id"),
    )

    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    request_hash: Mapped[str] = mapped_column(Text, nullable=False)
    inference_id: Mapped[str] = mapped_column(Text, nullable=False)
    system_config_version: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    trace_id: Mapped[str | None] = mapped_column(Text)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    first_seen_at: Mapped[datetime | None]
    last_seen_at: Mapped[datetime | None]
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


class InferenceDecisionEvidence(Base):
    """Persisted inference decision record (table: inference_decision_records)."""

    __tablename__ = "inference_decision_records"
    __table_args__ = (
        Index("ix_inference_decision_records_inference_id", "inference_id"),
        Index("ix_inference_decision_records_trace_id", "trace_id"),
        Index("ix_inference_decision_records_created_at", "created_at"),
        Index("ix_inference_decision_records_policy_chain_id", "policy_chain_id"),
        Index("ix_inference_decision_records_capability_status", "capability", "status"),
    )

    inference_id: Mapped[str] = mapped_column(Text, nullable=False)
    trace_id: Mapped[str | None] = mapped_column(Text)
    policy_chain_id: Mapped[str | None] = mapped_column(Text)
    capability: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str] = mapped_column(Text, nullable=False)
    scope_type: Mapped[str] = mapped_column(Text, nullable=False)
    scope_id: Mapped[str] = mapped_column(Text, nullable=False)
    resolved_provider_id: Mapped[str | None] = mapped_column(Text)
    resolved_model_id: Mapped[str | None] = mapped_column(Text)
    resolved_provider_type: Mapped[str | None] = mapped_column(Text)
    adapter_protocol: Mapped[str | None] = mapped_column(Text)
    request_payload_hash: Mapped[str | None] = mapped_column(Text)
    response_payload_hash: Mapped[str | None] = mapped_column(Text)
    parent_decision_id: Mapped[str | None] = mapped_column(Text)
    attempt_number: Mapped[int] = mapped_column(Integer, default=1)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class InferenceCatalogSnapshot(Base):
    """models.dev / sync snapshot metadata (not raw provider topology)."""

    __tablename__ = "inference_catalog_snapshots"
    __table_args__ = (
        Index("ix_inference_catalog_snapshots_synced_at", "synced_at"),
        UniqueConstraint("snapshot_version", name="uq_inference_catalog_snapshots_version"),
    )

    snapshot_version: Mapped[str] = mapped_column(Text, nullable=False)
    previous_version: Mapped[str | None] = mapped_column(Text)
    synced_at: Mapped[datetime] = mapped_column(nullable=False)
    models_accepted: Mapped[int] = mapped_column(Integer, default=0)
    models_rejected: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class InferenceCatalogEntry(Base):
    """Materialized catalog entry for a snapshot (provider + model identity)."""

    __tablename__ = "inference_catalog_entries"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_version",
            "provider_id",
            "model_id",
            name="uq_inference_catalog_entries_snapshot_provider_model",
        ),
        Index("ix_inference_catalog_entries_provider", "provider_id"),
        Index("ix_inference_catalog_entries_model_id", "model_id"),
        Index("ix_inference_catalog_entries_snapshot_provider", "snapshot_version", "provider_id"),
        Index("ix_inference_catalog_entries_status", "status"),
    )

    snapshot_version: Mapped[str] = mapped_column(Text, nullable=False)
    provider_id: Mapped[str] = mapped_column(Text, nullable=False)
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    descriptor: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class InferenceRoutingDecision(Base):
    """Materialized routing decision for a single inference attempt."""

    __tablename__ = "inference_routing_decisions"
    __table_args__ = (
        Index("ix_inference_routing_decisions_inference_id", "inference_id"),
        Index("ix_inference_routing_decisions_created_at", "created_at"),
    )

    inference_id: Mapped[str] = mapped_column(Text, nullable=False)
    routing_decision_id: Mapped[str] = mapped_column(Text, nullable=False)
    decision: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class InferencePolicyChain(Base):
    """Linked policy gate results for an inference."""

    __tablename__ = "inference_policy_chains"
    __table_args__ = (
        Index("ix_inference_policy_chains_inference_id", "inference_id"),
        UniqueConstraint("chain_id", name="uq_inference_policy_chains_chain_id"),
    )

    inference_id: Mapped[str] = mapped_column(Text, nullable=False)
    chain_id: Mapped[str] = mapped_column(Text, nullable=False)
    gates: Mapped[list[Any]] = mapped_column(JSONB, default=list)


class InferenceModelPin(Base):
    """Pinned model identity for embeddings / reproducibility."""

    __tablename__ = "inference_model_pins"
    __table_args__ = (
        UniqueConstraint(
            "scope_type",
            "scope_id",
            "provider_id",
            "model_id",
            name="uq_inference_model_pins_scope_provider_model",
        ),
        Index("ix_inference_model_pins_provider_model", "provider_id", "model_id"),
    )

    scope_type: Mapped[str] = mapped_column(Text, nullable=False)
    scope_id: Mapped[str] = mapped_column(Text, nullable=False)
    provider_id: Mapped[str] = mapped_column(Text, nullable=False)
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    pin_version: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_dimensions: Mapped[int | None] = mapped_column(Integer)
    pinned_by: Mapped[str] = mapped_column(Text, nullable=False)
    pinned_at: Mapped[datetime] = mapped_column(nullable=False)


class StreamingToken(Base):
    """Single-use streaming or builder token."""

    __tablename__ = "streaming_tokens"
    __table_args__ = (
        Index("idx_streaming_tokens_run", "run_id"),
        Index("idx_streaming_tokens_type", "token_type"),
        Index("idx_streaming_tokens_expires", "expires_at"),
    )

    token: Mapped[str] = mapped_column(Text, primary_key=True)
    run_id: Mapped[str | None] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(Text, nullable=False)
    token_type: Mapped[str] = mapped_column(Text, nullable=False, default="streaming")
    workflow_id: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    used_at: Mapped[datetime | None]


class Organization(Base):
    """Tenant organization (v1.4.0 multi-tenancy)."""

    __tablename__ = "organizations"
    __table_args__ = ()

    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    owner_actor: Mapped[str] = mapped_column(Text, nullable=False)
    namespace: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="ACTIVE")
    quotas: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


organization_members = Table(
    "organization_members",
    Base.metadata,
    Column("id", Text, primary_key=True),
    Column(
        "organization_id",
        Text,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("actor", Text, nullable=False),
    Column("org_role", Text, nullable=False),
    Column("rbac_role", Text, nullable=False),
    Column("joined_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("organization_id", "actor", name="uq_organization_members_org_actor"),
    Index("idx_org_members_actor", "actor"),
)

organization_quotas_usage = Table(
    "organization_quotas_usage",
    Base.metadata,
    Column("organization_id", Text, ForeignKey("organizations.id"), primary_key=True),
    Column("storage_bytes_used", BigInteger, nullable=False, server_default="0"),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)


class WorkflowSchedule(Base):
    __tablename__ = "workflow_schedules"
    __table_args__ = (
        Index("idx_schedules_next_run", "next_run_at", postgresql_where=text("status = 'ACTIVE'")),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(Text, nullable=False)
    workflow_version: Mapped[int | None]
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None]
    schedule_type: Mapped[str] = mapped_column(Text, nullable=False)
    schedule_value: Mapped[str] = mapped_column(Text, nullable=False)
    input_state: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    actor: Mapped[str] = mapped_column(Text, nullable=False)
    namespace: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="ACTIVE")
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_run_at: Mapped[datetime | None]
    max_runs: Mapped[int | None]
    run_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_by: Mapped[str | None]
    locked_until: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
