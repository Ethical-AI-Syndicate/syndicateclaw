"""Add NOT NULL namespace to agent_messages.

Revision ID: 020_namespace_agent_messages
Revises: 019_namespace_workflow_runs
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "020_namespace_agent_messages"
down_revision: str | None = "019_namespace_workflow_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    am_cols = {c["name"] for c in insp.get_columns("agent_messages")}
    if "namespace" not in am_cols:
        op.add_column(
            "agent_messages",
            sa.Column("namespace", sa.Text(), nullable=True, server_default="default"),
        )
    op.execute("UPDATE agent_messages SET namespace = 'default' WHERE namespace IS NULL")
    op.alter_column(
        "agent_messages",
        "namespace",
        nullable=False,
        server_default=None,
    )


def downgrade() -> None:
    op.drop_column("agent_messages", "namespace")
