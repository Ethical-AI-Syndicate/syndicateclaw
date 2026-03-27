"""Add linear head after merge for deterministic downgrade step.

Revision ID: 007_merge_heads_finalize
Revises: 007_merge_heads
Create Date: 2026-03-27
"""

from collections.abc import Sequence


revision: str = "007_merge_heads_finalize"
down_revision: str | Sequence[str] | None = "007_merge_heads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
