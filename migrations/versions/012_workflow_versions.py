"""Add workflow versions and archive tables.

Revision ID: 012_workflow_versions
Revises: 011_topic_subscriptions
Create Date: 2026-03-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "012_workflow_versions"
down_revision: str | None = "011_topic_subscriptions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_versions",
        sa.Column("id", sa.Text(), primary_key=True, nullable=False),
        sa.Column(
            "workflow_id",
            sa.Text(),
            sa.ForeignKey("workflow_definitions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("definition", postgresql.JSONB(), nullable=False),
        sa.Column("changed_by", sa.Text(), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("workflow_id", "version", name="uq_workflow_version"),
    )
    op.create_index(
        "idx_workflow_versions_wf",
        "workflow_versions",
        ["workflow_id", sa.text("version DESC")],
        unique=False,
    )

    op.create_table(
        "workflow_versions_archive",
        sa.Column("id", sa.Text(), primary_key=True, nullable=False),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("definition", postgresql.JSONB(), nullable=False),
        sa.Column("changed_by", sa.Text(), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "idx_workflow_versions_archive_wf",
        "workflow_versions_archive",
        ["workflow_id", "version"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_workflow_versions_archive_wf", table_name="workflow_versions_archive")
    op.drop_table("workflow_versions_archive")
    op.drop_index("idx_workflow_versions_wf", table_name="workflow_versions")
    op.drop_table("workflow_versions")
