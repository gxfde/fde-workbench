"""add durable ClawBot command idempotency

Revision ID: 0026_clawbot_command_idempotency
Revises: 0025_dsh_runtime_execution
"""

import sqlalchemy as sa
from alembic import op


revision = "0026_clawbot_command_idempotency"
down_revision = "0025_dsh_runtime_execution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "automation_tasks",
        sa.Column("source_event_id", sa.String(length=160), nullable=True),
    )
    op.create_unique_constraint(
        "uq_automation_tasks_source_event_id",
        "automation_tasks",
        ["source_event_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_automation_tasks_source_event_id",
        "automation_tasks",
        type_="unique",
    )
    op.drop_column("automation_tasks", "source_event_id")
