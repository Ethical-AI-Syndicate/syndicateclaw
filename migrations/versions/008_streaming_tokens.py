"""Add streaming_tokens table for single-use streaming auth.

Revision ID: 008_streaming_tokens
Revises: 007_merge_heads_finalize
Create Date: 2026-03-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "008_streaming_tokens"
down_revision: str | None = "007_merge_heads_finalize"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "streaming_tokens",
        sa.Column("token", sa.Text(), primary_key=True, nullable=False),
        sa.Column("run_id", sa.Text(), nullable=True),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("token_type", sa.Text(), nullable=False, server_default="streaming"),
        sa.Column("workflow_id", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_streaming_tokens_run", "streaming_tokens", ["run_id"], unique=False)
    op.create_index("idx_streaming_tokens_type", "streaming_tokens", ["token_type"], unique=False)
    op.create_index(
        "idx_streaming_tokens_expires",
        "streaming_tokens",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_streaming_tokens_expires", table_name="streaming_tokens")
    op.drop_index("idx_streaming_tokens_type", table_name="streaming_tokens")
    op.drop_index("idx_streaming_tokens_run", table_name="streaming_tokens")
    op.drop_table("streaming_tokens")
