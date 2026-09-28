"""remove the abandoned DSH canary control table

Revision ID: 0032_dsh_rollout_control
Revises: 0031_plugin_change_approvals
"""

from alembic import op
from sqlalchemy import inspect


revision = "0032_dsh_rollout_control"
down_revision = "0031_plugin_change_approvals"
branch_labels = None
depends_on = None


def _drop_abandoned_table() -> None:
    if "dsh_rollout_controls" in inspect(op.get_bind()).get_table_names():
        op.drop_table("dsh_rollout_controls")


def upgrade() -> None:
    _drop_abandoned_table()


def downgrade() -> None:
    _drop_abandoned_table()
