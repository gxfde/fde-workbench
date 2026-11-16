"""agent_runs 状态值域 +cancelled（AF1-WP1 定参①，docs/ai-fde/09 §1）

AgentRun 取消入口（POST /api/v1/agents/runs/{id}/cancel）需要「已取消」
与「跑完/失败」可判别——沿 WorkflowRun cancelled 与 background_jobs
T-J2（d9f4a7c2e6b1）同一裁决：幂等取消对已取消行回 cancelled=false，
对终态回 409 already_terminal。零列重建——只需置换 CHECK 约束（T-J2
先例：纯 CHECK 置换零数据迁移）；downgrade 先把 cancelled 归位 failed
（取消本就是「不再执行」的终态，failed 是旧值域最接近的诚实映射）。
"""
import sqlalchemy as sa
from alembic import op

revision = "b3e7a1c9f4d2"
down_revision = "c2a9e7d5b3f1"
branch_labels = None
depends_on = None

_RUN_STATUSES_OLD = (
    "status IN ('queued', 'running', 'host_running', 'completed',"
    " 'succeeded_but_receipt_invalid', 'failed', 'timeout', 'budget_exceeded')"
)
_RUN_STATUSES_NEW = (
    "status IN ('queued', 'running', 'host_running', 'cancelled', 'completed',"
    " 'succeeded_but_receipt_invalid', 'failed', 'timeout', 'budget_exceeded')"
)


def upgrade() -> None:
    op.drop_constraint("ck_agent_runs_status", "agent_runs", type_="check")
    op.create_check_constraint("ck_agent_runs_status", "agent_runs", _RUN_STATUSES_NEW)


def downgrade() -> None:
    op.execute(sa.text("UPDATE agent_runs SET status = 'failed' WHERE status = 'cancelled'"))
    op.drop_constraint("ck_agent_runs_status", "agent_runs", type_="check")
    op.create_check_constraint("ck_agent_runs_status", "agent_runs", _RUN_STATUSES_OLD)
