"""Add organization_members table.

Revision ID: 015_organization_members
Revises: 014_organizations
Create Date: 2026-03-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "015_organization_members"
down_revision: str | None = "014_organizations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "organization_members",
        sa.Column("id", sa.Text(), primary_key=True, nullable=False),
        sa.Column(
            "organization_id",
            sa.Text(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("org_role", sa.Text(), nullable=False),
        sa.Column("rbac_role", sa.Text(), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "actor", name="uq_organization_members_org_actor"),
    )
    op.create_index("idx_org_members_actor", "organization_members", ["actor"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_org_members_actor", table_name="organization_members")
    op.drop_table("organization_members")
