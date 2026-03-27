"""Add NOT NULL namespace to workflow_definitions.

Skipped: agents (namespace already present from 009_agents).
Skipped: memory_records (namespace already NOT NULL in schema).

Revision ID: 018_namespace_workflow_definitions
Revises: 015_organization_members
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "018_namespace_workflow_definitions"
down_revision: str | None = "015_organization_members"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workflow_definitions",
        sa.Column("namespace", sa.Text(), nullable=True, server_default="default"),
    )
    op.execute("UPDATE workflow_definitions SET namespace = 'default' WHERE namespace IS NULL")
    op.alter_column(
        "workflow_definitions",
        "namespace",
        nullable=False,
        server_default=None,
    )
    op.drop_constraint("workflow_definitions_name_version_key", "workflow_definitions", type_="unique")
    op.create_unique_constraint(
        "uq_workflow_definitions_name_version_namespace",
        "workflow_definitions",
        ["name", "version", "namespace"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_workflow_definitions_name_version_namespace",
        "workflow_definitions",
        type_="unique",
    )
    op.create_unique_constraint(
        "workflow_definitions_name_version_key",
        "workflow_definitions",
        ["name", "version"],
    )
    op.drop_column("workflow_definitions", "namespace")
