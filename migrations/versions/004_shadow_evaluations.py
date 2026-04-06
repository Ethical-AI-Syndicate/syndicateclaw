"""create shadow_evaluations table for Phase 1 shadow mode

Revision ID: 004_shadow
Revises: 003_audit
Create Date: 2026-03-24

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "004_shadow"
down_revision: str | None = "003_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shadow_evaluations",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.Text(), nullable=True),
        sa.Column("route_name", sa.Text(), nullable=False),
        sa.Column("http_method", sa.Text(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("principal_id", sa.Text(), nullable=True),
        sa.Column("team_context", sa.Text(), nullable=True),
        sa.Column("team_context_valid", sa.Boolean(), nullable=True),
        sa.Column("required_permission", sa.Text(), nullable=True),
        sa.Column("resolved_scope_type", sa.Text(), nullable=True),
        sa.Column("resolved_scope_id", sa.Text(), nullable=True),
        sa.Column("rbac_decision", sa.Text(), nullable=True),
        sa.Column("rbac_deny_reason", sa.Text(), nullable=True),
        sa.Column("rbac_matched_assignments", postgresql.JSONB(), server_default="[]"),
        sa.Column("rbac_matched_denies", postgresql.JSONB(), server_default="[]"),
        sa.Column("rbac_permission_source", sa.Text(), nullable=True),
        sa.Column("legacy_decision", sa.Text(), nullable=True),
        sa.Column("legacy_deny_reason", sa.Text(), nullable=True),
        sa.Column("agreement", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("disagreement_type", sa.Text(), nullable=True),
        sa.Column("cache_hit", sa.Boolean(), server_default="false"),
        sa.Column("evaluation_latency_us", sa.Integer(), server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_shadow_evaluations_disagreement",
        "shadow_evaluations",
        ["agreement", "disagreement_type"],
    )
    op.create_index("ix_shadow_evaluations_timestamp", "shadow_evaluations", ["created_at"])
    op.create_index("ix_shadow_evaluations_route", "shadow_evaluations", ["route_name"])
    op.create_index("ix_shadow_evaluations_actor", "shadow_evaluations", ["actor"])


def downgrade() -> None:
    op.drop_index("ix_shadow_evaluations_actor", table_name="shadow_evaluations")
    op.drop_index("ix_shadow_evaluations_route", table_name="shadow_evaluations")
    op.drop_index("ix_shadow_evaluations_timestamp", table_name="shadow_evaluations")
    op.drop_index("ix_shadow_evaluations_disagreement", table_name="shadow_evaluations")
    op.drop_table("shadow_evaluations")
