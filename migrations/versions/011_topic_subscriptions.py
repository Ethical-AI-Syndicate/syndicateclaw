"""Add topic_subscriptions table for v1.3.0 messaging protocol.

Revision ID: 011_topic_subscriptions
Revises: 010_agent_messages
Create Date: 2026-03-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "011_topic_subscriptions"
down_revision: str | None = "010_agent_messages"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "topic_subscriptions",
        sa.Column("id", sa.Text(), primary_key=True, nullable=False),
        sa.Column(
            "agent_id",
            sa.Text(),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("namespace", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("agent_id", "topic", name="uq_topic_subscriptions"),
    )
    op.create_index("idx_topic_subs_topic", "topic_subscriptions", ["topic", "namespace"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_topic_subs_topic", table_name="topic_subscriptions")
    op.drop_table("topic_subscriptions")
