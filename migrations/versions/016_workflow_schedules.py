"""Add workflow_schedules table.

Revision ID: 016_workflow_schedules
Revises: 013_workflow_defs_ver
Create Date: 2026-03-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "016_workflow_schedules"
down_revision: str | None = "013_workflow_defs_ver"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_schedules",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("workflow_version", sa.Integer()),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("schedule_type", sa.Text(), nullable=False),
        sa.Column("schedule_value", sa.Text(), nullable=False),
        sa.Column("input_state", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("namespace", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="ACTIVE"),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True)),
        sa.Column("max_runs", sa.Integer()),
        sa.Column("run_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_by", sa.Text()),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "idx_schedules_next_run",
        "workflow_schedules",
        ["next_run_at"],
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )


def downgrade() -> None:
    op.drop_index("idx_schedules_next_run", table_name="workflow_schedules")
    op.drop_table("workflow_schedules")
