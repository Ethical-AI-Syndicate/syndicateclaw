"""add owning scope and principal ID columns to existing tables

Revision ID: 002_scope
Revises: 001_rbac
Create Date: 2026-03-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002_scope"
down_revision: Union[str, None] = "001_rbac"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCOPE_TABLES = [
    "workflow_definitions",
    "workflow_runs",
    "memory_records",
    "approval_requests",
    "policy_rules",
]

_PRINCIPAL_ID_COLUMNS = [
    ("workflow_definitions", "owner_principal_id"),
    ("workflow_runs", "initiated_by_principal_id"),
    ("memory_records", "actor_principal_id"),
]


def upgrade() -> None:
    for table in _SCOPE_TABLES:
        op.add_column(table, sa.Column("owning_scope_type", sa.Text(), nullable=True))
        op.add_column(table, sa.Column("owning_scope_id", sa.Text(), nullable=True))

    for table, col in _PRINCIPAL_ID_COLUMNS:
        op.add_column(
            table,
            sa.Column(
                col,
                sa.Text(),
                sa.ForeignKey("principals.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )


def downgrade() -> None:
    for table, col in reversed(_PRINCIPAL_ID_COLUMNS):
        op.drop_column(table, col)

    for table in reversed(_SCOPE_TABLES):
        op.drop_column(table, "owning_scope_id")
        op.drop_column(table, "owning_scope_type")
