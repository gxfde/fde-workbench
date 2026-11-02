"""Workflow 审批反链（V3 T-W4，设计 workflow-dag-v1 §3「审批复用 automation_approvals」）

human_approval 节点复用 automation_approvals 表：``run_id`` 放开为可空（workflow
审批没有 automation_task_run 可挂），新增可空 ``workflow_node_run_id`` 反链节点行
（审批落点据此驱动节点状态机）。CASCADE 沿 workflow_node_runs.run_id 的 CASCADE
语义——审批行是节点等待态的投影，随节点走；审计事实另由 operation_events 承载。

Backup hint: additive/nullable only; downgrade 删除 workflow 审批行后恢复 NOT NULL。
"""
import sqlalchemy as sa
from alembic import op

revision = "d5b8e2f4a7c9"
down_revision = "b7d9f1a3c5e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "automation_approvals",
        sa.Column("workflow_node_run_id", sa.String(length=36), nullable=True),
    )
    op.create_foreign_key(
        "fk_automation_approvals_workflow_node_run_id",
        "automation_approvals",
        "workflow_node_runs",
        ["workflow_node_run_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_automation_approvals_workflow_node",
        "automation_approvals",
        ["workflow_node_run_id"],
    )
    op.alter_column(
        "automation_approvals", "run_id", existing_type=sa.String(length=36), nullable=True
    )


def downgrade() -> None:
    # workflow 审批行（run_id IS NULL）无任务运行可挂，降级前清出
    op.execute("DELETE FROM automation_approvals WHERE run_id IS NULL")
    op.alter_column(
        "automation_approvals", "run_id", existing_type=sa.String(length=36), nullable=False
    )
    op.drop_index(
        "ix_automation_approvals_workflow_node", table_name="automation_approvals"
    )
    op.drop_constraint(
        "fk_automation_approvals_workflow_node_run_id",
        "automation_approvals",
        type_="foreignkey",
    )
    op.drop_column("automation_approvals", "workflow_node_run_id")
