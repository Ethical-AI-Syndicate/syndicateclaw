"""Add NOT NULL namespace to policy_rules.

Revision ID: 021_namespace_policy_rules
Revises: 020_namespace_agent_messages
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "021_namespace_policy_rules"
down_revision: str | None = "020_namespace_agent_messages"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "policy_rules",
        sa.Column("namespace", sa.Text(), nullable=True, server_default="default"),
    )
    op.execute("UPDATE policy_rules SET namespace = 'default' WHERE namespace IS NULL")
    op.alter_column(
        "policy_rules",
        "namespace",
        nullable=False,
        server_default=None,
    )
    op.drop_constraint("policy_rules_name_key", "policy_rules", type_="unique")
    op.create_unique_constraint(
        "uq_policy_rules_name_namespace",
        "policy_rules",
        ["name", "namespace"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_policy_rules_name_namespace", "policy_rules", type_="unique")
    op.create_unique_constraint("policy_rules_name_key", "policy_rules", ["name"])
    op.drop_column("policy_rules", "namespace")
