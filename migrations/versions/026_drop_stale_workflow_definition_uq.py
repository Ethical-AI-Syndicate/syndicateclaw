"""Remove stale unique constraint left alongside namespace composite.

Some databases accumulated ``uq_workflow_definitions_name`` (name-only or
legacy pair) while ``uq_workflow_definitions_name_version_namespace`` is the
canonical constraint. Drop the duplicate so ORM metadata and ``alembic check``
match.

Revision ID: 026_drop_stale_wf_uq
Revises: 025_builder_token_type
"""

from collections.abc import Sequence

from alembic import op

revision: str = "026_drop_stale_wf_uq"
down_revision: str | None = "025_builder_token_type"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE workflow_definitions DROP CONSTRAINT IF EXISTS uq_workflow_definitions_name"
    )


def downgrade() -> None:
    """Recreating the legacy uq is unsafe; leave DB as-is."""
    return
