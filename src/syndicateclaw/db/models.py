from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, _generate_ulid


class WorkflowDefinition(Base):
    __tablename__ = "workflow_definitions"
    __table_args__ = (
        UniqueConstraint("name", "version"),
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    nodes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    edges: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    owner: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    owner_principal_id: Mapped[str | None] = mapped_column(
        ForeignKey("principals.id", ondelete="SET NULL")
    )
    owning_scope_type: Mapped[str | None] = mapped_column(Text)
    owning_scope_id: Mapped[str | None] = mapped_column(Text)

    runs: Mapped[list[WorkflowRun]] = relationship(back_populates="workflow", lazy="selectin")


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (
        Index("ix_workflow_runs_status", "status"),
        Index("ix_workflow_runs_initiated_by", "initiated_by"),
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
    parent_run: Mapped[WorkflowRun | None] = relationship(remote_side="WorkflowRun.id", lazy="selectin")
    node_executions: Mapped[list[NodeExecution]] = relationship(back_populates="run", lazy="selectin")


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
    __table_args__ = (
        UniqueConstraint("name"),
    )

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
        Index("ix_policy_rules_resource_type", "resource_type"),
        Index("ix_policy_rules_enabled", "enabled"),
    )

    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
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
        default=lambda: datetime.now(timezone.utc),
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
        default=lambda: datetime.now(timezone.utc),
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


# ---------------------------------------------------------------------------
# RBAC tables (Phase 0 — Gate 2)
# ---------------------------------------------------------------------------


class Principal(Base):
    """Identity record for users, service accounts, and teams."""
    __tablename__ = "principals"
    __table_args__ = (
        UniqueConstraint("principal_type", "name"),
    )

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
        back_populates="principal", lazy="selectin",
    )


class TeamMembership(Base):
    __tablename__ = "team_memberships"
    __table_args__ = (
        UniqueConstraint("principal_id", "team_id"),
        Index("ix_team_memberships_team_id", "team_id"),
    )

    principal_id: Mapped[str] = mapped_column(
        ForeignKey("principals.id", ondelete="CASCADE"), nullable=False,
    )
    team_id: Mapped[str] = mapped_column(
        ForeignKey("principals.id", ondelete="CASCADE"), nullable=False,
    )
    granted_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc),
    )
    granted_by: Mapped[str] = mapped_column(Text, nullable=False)

    principal: Mapped[Principal] = relationship(
        foreign_keys=[principal_id], lazy="selectin",
    )
    team: Mapped[Principal] = relationship(
        foreign_keys=[team_id], lazy="selectin",
    )


class Role(Base):
    __tablename__ = "roles"
    __table_args__ = (
        UniqueConstraint("name", "scope_type"),
    )

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
        ForeignKey("principals.id", ondelete="CASCADE"), nullable=False,
    )
    role_id: Mapped[str] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), nullable=False,
    )
    scope_type: Mapped[str] = mapped_column(Text, nullable=False)
    scope_id: Mapped[str] = mapped_column(Text, nullable=False)
    granted_by: Mapped[str] = mapped_column(Text, nullable=False)
    granted_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc),
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
        ForeignKey("principals.id", ondelete="CASCADE"), nullable=False,
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
        ForeignKey("principals.id", ondelete="CASCADE"), nullable=False,
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
        ForeignKey("principals.id", ondelete="CASCADE"), nullable=False,
    )
    effective_principal_id: Mapped[str] = mapped_column(
        ForeignKey("principals.id", ondelete="CASCADE"), nullable=False,
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
