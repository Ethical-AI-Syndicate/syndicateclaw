"""Add scopes column to api_keys for scoped key permissions.

Revision ID: 006_api_key_scopes
Revises: 006_envelope_result
Create Date: 2026-03-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "006_api_key_scopes"
down_revision: str | None = "006_envelope_result"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "api_keys",
        sa.Column(
            "scopes",
            postgresql.ARRAY(sa.TEXT()),
            server_default="{}",
            nullable=False,
            comment=(
                "Empty array intentionally grants full access for v1.0 backward "
                "compatibility. See v1.1.0 spec section 4.3.2."
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("api_keys", "scopes")
