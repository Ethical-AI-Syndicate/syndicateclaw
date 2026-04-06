"""Merge divergent migration heads after v1.1.0 and inference branch.

Revision ID: 007_merge_heads
Revises: 006_api_key_scopes, 373526e19799
Create Date: 2026-03-27
"""

from collections.abc import Sequence

revision: str = "007_merge_heads"
down_revision: str | Sequence[str] | None = (
    "006_api_key_scopes",
    "373526e19799",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
