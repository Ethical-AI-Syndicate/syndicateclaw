"""add RBAC columns to audit_events and api_keys

Revision ID: 003_audit
Revises: 002_scope
Create Date: 2026-03-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "003_audit"
down_revision: Union[str, None] = "002_scope"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "audit_events",
        sa.Column("real_actor", sa.Text(), nullable=True),
    )
    op.add_column(
        "audit_events",
        sa.Column("impersonation_session_id", sa.Text(), nullable=True),
    )
    op.add_column(
        "audit_events",
        sa.Column("resource_scope_type", sa.Text(), nullable=True),
    )
    op.add_column(
        "audit_events",
        sa.Column("resource_scope_id", sa.Text(), nullable=True),
    )
    op.add_column(
        "audit_events",
        sa.Column(
            "actor_principal_id",
            sa.Text(),
            sa.ForeignKey("principals.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    op.create_index(
        "ix_audit_events_resource_scope",
        "audit_events",
        ["resource_scope_type", "resource_scope_id"],
    )
    op.create_index(
        "ix_audit_events_actor_principal",
        "audit_events",
        ["actor_principal_id"],
    )

    op.add_column(
        "api_keys",
        sa.Column(
            "actor_principal_id",
            sa.Text(),
            sa.ForeignKey("principals.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("api_keys", "actor_principal_id")

    op.drop_index("ix_audit_events_actor_principal", table_name="audit_events")
    op.drop_index("ix_audit_events_resource_scope", table_name="audit_events")

    op.drop_column("audit_events", "actor_principal_id")
    op.drop_column("audit_events", "resource_scope_id")
    op.drop_column("audit_events", "resource_scope_type")
    op.drop_column("audit_events", "impersonation_session_id")
    op.drop_column("audit_events", "real_actor")
