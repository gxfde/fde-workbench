"""B#1+B#28+B#2 合并迁移：workflow_runs.hops / gates.lifecycle_version / agent_runs 回执终态

P0 先行批代码级子批（借鉴清单 B#1 跳数熔断 / B#28 门禁 revision CAS+
生命周期版本隔离 / B#2 回执「写错不重做」），一个 revision 覆盖三件——
只做一次 rebuild + alembic upgrade head（总览 §5 迁移窗口合并纪律）。

- workflow_runs.hops：跨「重投代际」（resume_run 拍板重投）累加的链长计数，
  继承不清零；执行器入口超 MAX_RUN_HOPS honest failed(hops_exceeded)。
- gates.lifecycle_version：门禁语法代际（FF stage 语义），现役=1；CAS 拍板
  复用既有 VersionedMixin.version 作 revision（零新列）。
- agent_runs 新终态 succeeded_but_receipt_invalid：业务执行完成但回执/产物
  清单校验失败——独立于 failed（不进 FAILED_STATUSES ⇒ retry_run 拒同键
  重跑，业务动作不重执行）；downgrade 归位 failed（最接近的诚实映射）。
"""
import sqlalchemy as sa
from alembic import op

revision = "b2e8f4a6c9d3"
down_revision = "d9f4a7c2e6b1"
branch_labels = None
depends_on = None

_AGENT_RUN_STATUSES_OLD = (
    "status IN ('queued', 'running', 'completed', 'failed', 'timeout', 'budget_exceeded')"
)
_AGENT_RUN_STATUSES_NEW = (
    "status IN ('queued', 'running', 'completed', 'succeeded_but_receipt_invalid',"
    " 'failed', 'timeout', 'budget_exceeded')"
)


def upgrade() -> None:
    op.add_column(
        "workflow_runs",
        sa.Column("hops", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "gates",
        sa.Column(
            "lifecycle_version", sa.Integer(), nullable=False, server_default=sa.text("1")
        ),
    )
    # 新终态字面量 29 字符 > 旧 String(24)，列先加宽再放行 CHECK。
    op.alter_column(
        "agent_runs", "status", existing_type=sa.String(24), type_=sa.String(40)
    )
    op.drop_constraint("ck_agent_runs_status", "agent_runs", type_="check")
    op.create_check_constraint(
        "ck_agent_runs_status", "agent_runs", _AGENT_RUN_STATUSES_NEW
    )


def downgrade() -> None:
    # 回执终态先归位旧值域：succeeded_but_receipt_invalid → failed（业务已执行
    # 但清单不可信，failed 是旧模型里最接近的诚实映射；产物留痕 reviewed=False
    # 不受列变更影响，溯源走 agent_artifacts/agent_tool_calls）。
    op.execute(
        sa.text(
            "UPDATE agent_runs SET status = 'failed'"
            " WHERE status = 'succeeded_but_receipt_invalid'"
        )
    )
    op.drop_constraint("ck_agent_runs_status", "agent_runs", type_="check")
    op.create_check_constraint(
        "ck_agent_runs_status", "agent_runs", _AGENT_RUN_STATUSES_OLD
    )
    op.alter_column(
        "agent_runs", "status", existing_type=sa.String(40), type_=sa.String(24)
    )
    op.drop_column("gates", "lifecycle_version")
    op.drop_column("workflow_runs", "hops")
