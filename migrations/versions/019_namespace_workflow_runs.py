"""Make workflow_runs.namespace NOT NULL (column added nullable in 017).

Revision ID: 019_namespace_workflow_runs
Revises: 018_namespace_workflow_definitions
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "019_namespace_workflow_runs"
down_revision: str | None = "018_namespace_workflow_definitions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    cols = {c["name"]: c for c in insp.get_columns("workflow_runs")}
    if "namespace" not in cols:
        return
    if cols["namespace"].get("nullable", True):
        op.execute("UPDATE workflow_runs SET namespace = 'default' WHERE namespace IS NULL")
        op.alter_column(
            "workflow_runs",
            "namespace",
            existing_type=sa.Text(),
            nullable=False,
            server_default=None,
        )


def downgrade() -> None:
    op.alter_column(
        "workflow_runs",
        "namespace",
        existing_type=sa.Text(),
        nullable=True,
    )
