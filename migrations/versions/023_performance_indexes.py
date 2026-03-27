"""Performance indexes for workflow_runs and audit_events.

Revision ID: 023_performance_indexes
Revises: 021_namespace_policy_rules

Note: idx_schedules_next_run is in 016; idx_messages_* in 010.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "023_performance_indexes"
down_revision: str | None = "021_namespace_policy_rules"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ix_workflow_runs_status / ix_workflow_runs_initiated_by exist on WorkflowRun model.
    # ix_audit_events_resource / ix_audit_events_actor exist on AuditEvent model.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_workflow_runs_namespace_status "
        "ON workflow_runs(namespace, status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_events_actor_created "
        "ON audit_events(actor, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_audit_events_actor_created")
    op.execute("DROP INDEX IF EXISTS idx_workflow_runs_namespace_status")
