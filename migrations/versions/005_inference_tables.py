"""inference provider tables: idempotency, catalog, routing, policy chains, pins

Revision ID: 005_inference
Revises: 004_shadow
Create Date: 2026-03-24

Additive only. No provider topology table — YAML remains authoritative (spec).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "005_inference"
down_revision: Union[str, None] = "004_shadow"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "inference_request_envelopes",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("request_hash", sa.Text(), nullable=False),
        sa.Column("inference_id", sa.Text(), nullable=False),
        sa.Column("system_config_version", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("trace_id", sa.Text(), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("idempotency_key", name="uq_inference_request_envelopes_idempotency_key"),
    )
    op.create_index(
        "ix_inference_request_envelopes_stale_sweep",
        "inference_request_envelopes",
        ["status", "updated_at"],
    )
    op.create_index(
        "ix_inference_request_envelopes_inference_id",
        "inference_request_envelopes",
        ["inference_id"],
    )
    op.create_index(
        "ix_inference_request_envelopes_trace_id",
        "inference_request_envelopes",
        ["trace_id"],
    )

    op.create_table(
        "inference_decision_records",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("inference_id", sa.Text(), nullable=False),
        sa.Column("trace_id", sa.Text(), nullable=True),
        sa.Column("policy_chain_id", sa.Text(), nullable=True),
        sa.Column("capability", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("scope_type", sa.Text(), nullable=False),
        sa.Column("scope_id", sa.Text(), nullable=False),
        sa.Column("resolved_provider_id", sa.Text(), nullable=True),
        sa.Column("resolved_model_id", sa.Text(), nullable=True),
        sa.Column("resolved_provider_type", sa.Text(), nullable=True),
        sa.Column("adapter_protocol", sa.Text(), nullable=True),
        sa.Column("request_payload_hash", sa.Text(), nullable=True),
        sa.Column("response_payload_hash", sa.Text(), nullable=True),
        sa.Column("parent_decision_id", sa.Text(), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("details", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_inference_decision_records_inference_id",
        "inference_decision_records",
        ["inference_id"],
    )
    op.create_index(
        "ix_inference_decision_records_trace_id",
        "inference_decision_records",
        ["trace_id"],
    )
    op.create_index(
        "ix_inference_decision_records_created_at",
        "inference_decision_records",
        ["created_at"],
    )
    op.create_index(
        "ix_inference_decision_records_policy_chain_id",
        "inference_decision_records",
        ["policy_chain_id"],
    )
    op.create_index(
        "ix_inference_decision_records_capability_status",
        "inference_decision_records",
        ["capability", "status"],
    )

    op.create_table(
        "inference_catalog_snapshots",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("snapshot_version", sa.Text(), nullable=False),
        sa.Column("previous_version", sa.Text(), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("models_accepted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("models_rejected", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("summary", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("snapshot_version", name="uq_inference_catalog_snapshots_version"),
    )
    op.create_index(
        "ix_inference_catalog_snapshots_synced_at",
        "inference_catalog_snapshots",
        ["synced_at"],
    )

    op.create_table(
        "inference_catalog_entries",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("snapshot_version", sa.Text(), nullable=False),
        sa.Column("provider_id", sa.Text(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("descriptor", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "snapshot_version",
            "provider_id",
            "model_id",
            name="uq_inference_catalog_entries_snapshot_provider_model",
        ),
    )
    op.create_index(
        "ix_inference_catalog_entries_provider",
        "inference_catalog_entries",
        ["provider_id"],
    )
    op.create_index(
        "ix_inference_catalog_entries_model_id",
        "inference_catalog_entries",
        ["model_id"],
    )
    op.create_index(
        "ix_inference_catalog_entries_snapshot_provider",
        "inference_catalog_entries",
        ["snapshot_version", "provider_id"],
    )
    op.create_index(
        "ix_inference_catalog_entries_status",
        "inference_catalog_entries",
        ["status"],
    )

    op.create_table(
        "inference_routing_decisions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("inference_id", sa.Text(), nullable=False),
        sa.Column("routing_decision_id", sa.Text(), nullable=False),
        sa.Column("decision", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_inference_routing_decisions_inference_id",
        "inference_routing_decisions",
        ["inference_id"],
    )
    op.create_index(
        "ix_inference_routing_decisions_created_at",
        "inference_routing_decisions",
        ["created_at"],
    )

    op.create_table(
        "inference_policy_chains",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("inference_id", sa.Text(), nullable=False),
        sa.Column("chain_id", sa.Text(), nullable=False),
        sa.Column("gates", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("chain_id", name="uq_inference_policy_chains_chain_id"),
    )
    op.create_index(
        "ix_inference_policy_chains_inference_id",
        "inference_policy_chains",
        ["inference_id"],
    )

    op.create_table(
        "inference_model_pins",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("scope_type", sa.Text(), nullable=False),
        sa.Column("scope_id", sa.Text(), nullable=False),
        sa.Column("provider_id", sa.Text(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("pin_version", sa.Text(), nullable=False),
        sa.Column("embedding_dimensions", sa.Integer(), nullable=True),
        sa.Column("pinned_by", sa.Text(), nullable=False),
        sa.Column("pinned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "scope_type",
            "scope_id",
            "provider_id",
            "model_id",
            name="uq_inference_model_pins_scope_provider_model",
        ),
    )
    op.create_index(
        "ix_inference_model_pins_provider_model",
        "inference_model_pins",
        ["provider_id", "model_id"],
    )


def downgrade() -> None:
    op.drop_table("inference_model_pins")
    op.drop_table("inference_policy_chains")
    op.drop_table("inference_routing_decisions")
    op.drop_table("inference_catalog_entries")
    op.drop_table("inference_catalog_snapshots")
    op.drop_table("inference_decision_records")
    op.drop_table("inference_request_envelopes")
