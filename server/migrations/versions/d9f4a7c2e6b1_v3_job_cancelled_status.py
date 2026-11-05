"""background_jobs 新增 cancelled 终态（V3 T-J2，域 14）

admin 取消 API（POST /api/v1/admin/jobs/{id}/cancel）需要「已取消」与
「跑完/失败」可判别：幂等取消对已取消行回 200 cancelled=false，对
succeeded/failed 回 409 already_terminal——failed+last_error 前缀区分
不了这两种，所以 cancelled 必须是真状态而不是错误标记。

active_key 生成列的表达式对一切非 (pending, queued, running) 状态本就
产出 NULL，cancelled 天然释放 (job_type, target_id) 槽位——迁移因此
只需置换 CHECK 约束，零数据迁移零列重建。downgrade 先把 cancelled
归位 failed（last_error 已带 cancelled_by_admin 前缀，可追溯）。
"""
import sqlalchemy as sa
from alembic import op

revision = "d9f4a7c2e6b1"
down_revision = "e2c6a8f4d1b3"
branch_labels = None
depends_on = None

_JOB_STATUSES_OLD = "status IN ('pending', 'queued', 'running', 'succeeded', 'failed')"
_JOB_STATUSES_NEW = (
    "status IN ('pending', 'queued', 'running', 'succeeded', 'failed', 'cancelled')"
)


def upgrade() -> None:
    op.drop_constraint("ck_background_jobs_status", "background_jobs", type_="check")
    op.create_check_constraint(
        "ck_background_jobs_status", "background_jobs", _JOB_STATUSES_NEW
    )


def downgrade() -> None:
    # 数据先归位旧值域：cancelled → failed（取消本就是「不再执行」的终态，
    # failed 是旧模型里最接近的诚实映射；last_error 前缀保留取消溯源）
    op.execute(
        sa.text("UPDATE background_jobs SET status = 'failed' WHERE status = 'cancelled'")
    )
    op.drop_constraint("ck_background_jobs_status", "background_jobs", type_="check")
    op.create_check_constraint(
        "ck_background_jobs_status", "background_jobs", _JOB_STATUSES_OLD
    )
