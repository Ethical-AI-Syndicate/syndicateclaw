"""Add agent_messages table for v1.3.0 messaging protocol.

Revision ID: 010_agent_messages
Revises: 009_agents
Create Date: 2026-03-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "010_agent_messages"
down_revision: str | None = "009_agents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_messages",
        sa.Column("id", sa.Text(), primary_key=True, nullable=False),
        sa.Column("conversation_id", sa.Text(), nullable=False),
        sa.Column("sender", sa.Text(), nullable=False),
        sa.Column("recipient", sa.Text(), nullable=True),
        sa.Column("topic", sa.Text(), nullable=True),
        sa.Column("message_type", sa.Text(), nullable=False),
        sa.Column("content", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("priority", sa.Text(), nullable=False, server_default="NORMAL"),
        sa.Column("status", sa.Text(), nullable=False, server_default="PENDING"),
        sa.Column("ttl_seconds", sa.Integer(), nullable=False, server_default="3600"),
        sa.Column("hop_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("parent_message_id", sa.Text(), nullable=True),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("(NOW() + INTERVAL '1 hour')"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        """
        UPDATE agent_messages
        SET expires_at = created_at + (ttl_seconds * INTERVAL '1 second')
        """
    )
    op.create_index("idx_messages_recipient_status", "agent_messages", ["recipient", "status"], unique=False)
    op.create_index("idx_messages_topic_status", "agent_messages", ["topic", "status"], unique=False)
    op.create_index("idx_messages_conversation", "agent_messages", ["conversation_id"], unique=False)
    op.create_index("idx_messages_sender", "agent_messages", ["sender"], unique=False)
    op.create_index(
        "idx_messages_expires",
        "agent_messages",
        ["expires_at"],
        unique=False,
        postgresql_where=sa.text("status = 'PENDING'"),
    )


def downgrade() -> None:
    op.drop_index("idx_messages_expires", table_name="agent_messages")
    op.drop_index("idx_messages_sender", table_name="agent_messages")
    op.drop_index("idx_messages_conversation", table_name="agent_messages")
    op.drop_index("idx_messages_topic_status", table_name="agent_messages")
    op.drop_index("idx_messages_recipient_status", table_name="agent_messages")
    op.drop_table("agent_messages")
