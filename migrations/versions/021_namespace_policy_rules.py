"""Add NOT NULL namespace to policy_rules.

Revision ID: 021_namespace_policy_rules
Revises: 020_namespace_agent_messages
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "021_namespace_policy_rules"
down_revision: str | None = "020_namespace_agent_messages"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    pr_cols = {c["name"] for c in insp.get_columns("policy_rules")}
    if "namespace" not in pr_cols:
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
    insp = inspect(bind)
    uq_names = {u["name"] for u in insp.get_unique_constraints("policy_rules")}
    if "policy_rules_name_key" in uq_names:
        op.drop_constraint("policy_rules_name_key", "policy_rules", type_="unique")
    if "uq_policy_rules_name_namespace" not in uq_names:
        op.create_unique_constraint(
            "uq_policy_rules_name_namespace",
            "policy_rules",
            ["name", "namespace"],
        )


def downgrade() -> None:
    op.drop_constraint("uq_policy_rules_name_namespace", "policy_rules", type_="unique")
    op.create_unique_constraint("policy_rules_name_key", "policy_rules", ["name"])
    op.drop_column("policy_rules", "namespace")
