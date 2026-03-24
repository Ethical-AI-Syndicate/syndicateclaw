"""create RBAC tables

Revision ID: 001_rbac
Revises:
Create Date: 2026-03-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "001_rbac"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "principals",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("principal_type", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("principal_type", "name", name="uq_principals_type_name"),
    )

    op.create_table(
        "team_memberships",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("principal_id", sa.Text(), sa.ForeignKey("principals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("team_id", sa.Text(), sa.ForeignKey("principals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("granted_by", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("principal_id", "team_id", name="uq_team_memberships_principal_team"),
    )
    op.create_index("ix_team_memberships_team_id", "team_memberships", ["team_id"])

    op.create_table(
        "roles",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("built_in", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("permissions", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("inherits_from", sa.Text(), nullable=True),
        sa.Column("display_base", sa.Text(), nullable=True),
        sa.Column("scope_type", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("name", "scope_type", name="uq_roles_name_scope"),
    )

    op.create_table(
        "role_assignments",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("principal_id", sa.Text(), sa.ForeignKey("principals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role_id", sa.Text(), sa.ForeignKey("roles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scope_type", sa.Text(), nullable=False),
        sa.Column("scope_id", sa.Text(), nullable=False),
        sa.Column("granted_by", sa.Text(), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.Text(), nullable=True),
        sa.Column("transitional", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_role_assignments_principal_scope",
        "role_assignments",
        ["principal_id", "scope_type", "scope_id"],
    )
    op.create_index("ix_role_assignments_role_id", "role_assignments", ["role_id"])

    op.create_table(
        "deny_assignments",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("principal_id", sa.Text(), sa.ForeignKey("principals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("permission", sa.Text(), nullable=False),
        sa.Column("scope_type", sa.Text(), nullable=False),
        sa.Column("scope_id", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("granted_by", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_deny_assignments_principal_permission",
        "deny_assignments",
        ["principal_id", "permission"],
    )

    op.create_table(
        "namespace_bindings",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("namespace_pattern", sa.Text(), nullable=False),
        sa.Column("team_id", sa.Text(), sa.ForeignKey("principals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("access_level", sa.Text(), nullable=False),
        sa.Column("granted_by", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_namespace_bindings_team_id", "namespace_bindings", ["team_id"])
    op.create_index("ix_namespace_bindings_pattern", "namespace_bindings", ["namespace_pattern"])

    op.create_table(
        "impersonation_sessions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("real_principal_id", sa.Text(), sa.ForeignKey("principals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("effective_principal_id", sa.Text(), sa.ForeignKey("principals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("approval_reference", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("max_duration_seconds", sa.Integer(), nullable=False, server_default=sa.text("3600")),
        sa.Column("permissions_restricted", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_impersonation_sessions_real", "impersonation_sessions", ["real_principal_id"])
    op.create_index("ix_impersonation_sessions_effective", "impersonation_sessions", ["effective_principal_id"])


def downgrade() -> None:
    op.drop_table("impersonation_sessions")
    op.drop_table("namespace_bindings")
    op.drop_table("deny_assignments")
    op.drop_table("role_assignments")
    op.drop_table("roles")
    op.drop_table("team_memberships")
    op.drop_table("principals")
