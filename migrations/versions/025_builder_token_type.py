"""Builder token columns — sequencing only.

Revision ID: 025_builder_token_type
Revises: 024_plugin_event_types

`streaming_tokens` already includes `token_type` and `workflow_id` from
migration 008. No ALTER needed; revision anchors the v1.5.0 builder track.
"""

from collections.abc import Sequence

revision: str = "025_builder_token_type"
down_revision: str | None = "024_plugin_event_types"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
