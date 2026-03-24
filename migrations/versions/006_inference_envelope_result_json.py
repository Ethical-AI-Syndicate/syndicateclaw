"""Add result_json to inference_request_envelopes for idempotent replay.

Revision ID: 006_envelope_result
Revises: 005_inference
Create Date: 2026-03-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "006_envelope_result"
down_revision: str | None = "005_inference"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "inference_request_envelopes",
        sa.Column("result_json", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("inference_request_envelopes", "result_json")
