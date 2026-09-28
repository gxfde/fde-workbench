"""store idempotent results for approved DSH tools

Revision ID: 0028_approved_tool_results
Revises: 0027_automation_approvals
"""

import sqlalchemy as sa
from alembic import op


revision = "0028_approved_tool_results"
down_revision = "0027_automation_approvals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "automation_approvals",
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "automation_approvals",
        sa.Column("result_json", sa.JSON(), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE automation_approvals "
            "SET result_json = JSON_OBJECT() WHERE result_json IS NULL"
        )
    )
    op.alter_column(
        "automation_approvals",
        "result_json",
        existing_type=sa.JSON(),
        nullable=False,
    )


def downgrade() -> None:
    op.drop_column("automation_approvals", "result_json")
    op.drop_column("automation_approvals", "executed_at")
