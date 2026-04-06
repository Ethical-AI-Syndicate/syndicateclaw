"""Add scheduler fields to workflow_runs table.

Revision ID: 017_wf_runs_scheduler_flds
Revises: 016_workflow_schedules
Create Date: 2026-03-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "017_wf_runs_scheduler_flds"
down_revision: str | None = "016_workflow_schedules"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workflow_runs",
        sa.Column("parent_schedule_id", sa.Text(), nullable=True),
    )
    op.add_column(
        "workflow_runs",
        sa.Column("triggered_by", sa.Text(), nullable=True, server_default="MANUAL"),
    )
    op.add_column(
        "workflow_runs",
        sa.Column("namespace", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_workflow_runs_parent_schedule_id",
        "workflow_runs",
        ["parent_schedule_id"],
        unique=False,
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workflow_runs_parent_schedule_id",
        table_name="workflow_runs",
    )
    op.drop_column("workflow_runs", "namespace")
    op.drop_column("workflow_runs", "triggered_by")
    op.drop_column("workflow_runs", "parent_schedule_id")
