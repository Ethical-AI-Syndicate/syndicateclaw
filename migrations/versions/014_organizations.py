"""Add organizations and quotas usage tables.

Revision ID: 014_organizations
Revises: 017_wf_runs_scheduler_flds
Create Date: 2026-03-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision: str = "014_organizations"
down_revision: str | None = "017_wf_runs_scheduler_flds"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    existing = set(insp.get_table_names())
    if "organizations" in existing and "organization_quotas_usage" in existing:
        return
    if "organizations" in existing and "organization_quotas_usage" not in existing:
        op.create_table(
            "organization_quotas_usage",
            sa.Column(
                "organization_id", sa.Text(), sa.ForeignKey("organizations.id"), primary_key=True
            ),
            sa.Column("storage_bytes_used", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
        return

    op.create_table(
        "organizations",
        sa.Column("id", sa.Text(), primary_key=True, nullable=False),
        sa.Column("name", sa.Text(), nullable=False, unique=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("owner_actor", sa.Text(), nullable=False),
        sa.Column("namespace", sa.Text(), nullable=False, unique=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="ACTIVE"),
        sa.Column(
            "quotas",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text(
                "'{"
                '"rate_limit_requests":1000,'
                '"rate_limit_burst":100,'
                '"max_agents":50,'
                '"max_workflows":200,'
                '"max_schedules":100,'
                '"max_memory_records":100000,'
                '"storage_limit_bytes":10737418240'
                "}'::jsonb"
            ),
        ),
        sa.Column(
            "settings",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )

    op.create_table(
        "organization_quotas_usage",
        sa.Column(
            "organization_id", sa.Text(), sa.ForeignKey("organizations.id"), primary_key=True
        ),
        sa.Column("storage_bytes_used", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    names = set(insp.get_table_names())
    if "organization_quotas_usage" in names:
        op.drop_table("organization_quotas_usage")
    if "organizations" in names:
        op.drop_table("organizations")
