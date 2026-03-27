"""Plugin audit event types — sequencing only.

Revision ID: 024_plugin_event_types
Revises: 023_performance_indexes

`audit_events.event_type` is free-form TEXT (no CHECK constraint), so no DB
change is required for plugin.* event names. This revision exists for Alembic
chain integrity and operational documentation.
"""

from collections.abc import Sequence

revision: str = "024_plugin_event_types"
down_revision: str | None = "023_performance_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
