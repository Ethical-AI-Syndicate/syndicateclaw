"""Add current_version and updated_by to workflow_definitions.

Revision ID: 013_workflow_defs_ver
Revises: 012_workflow_versions
Create Date: 2026-03-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "013_workflow_defs_ver"
down_revision: str | None = "012_workflow_versions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workflow_definitions",
        sa.Column("current_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column("workflow_definitions", sa.Column("updated_by", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("workflow_definitions", "updated_by")
    op.drop_column("workflow_definitions", "current_version")
