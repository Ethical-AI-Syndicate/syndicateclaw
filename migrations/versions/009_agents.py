"""Add agents table for v1.3.0 agent registry.

Revision ID: 009_agents
Revises: 008_streaming_tokens
Create Date: 2026-03-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "009_agents"
down_revision: str | None = "008_streaming_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agents",
        sa.Column("id", sa.Text(), primary_key=True, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("namespace", sa.Text(), nullable=False),
        sa.Column(
            "capabilities",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.Text(), nullable=False, server_default="OFFLINE"),
        sa.Column("registered_by", sa.Text(), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deregistered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("name", "namespace", name="uq_agents_name_namespace"),
    )
    op.create_index("idx_agents_namespace_status", "agents", ["namespace", "status"], unique=False)
    op.create_index(
        "idx_agents_capabilities",
        "agents",
        ["capabilities"],
        unique=False,
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("idx_agents_capabilities", table_name="agents", postgresql_using="gin")
    op.drop_index("idx_agents_namespace_status", table_name="agents")
    op.drop_table("agents")
