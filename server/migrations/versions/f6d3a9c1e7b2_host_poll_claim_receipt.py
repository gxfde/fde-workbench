"""P2′① 宿主轮询领取：agent_runs 状态机扩展 + 宿主领取/回执列（2026-11-08）。

链位：接 V3.1 P0-1 discovery 迁移 c3d5e7f9a1b4 之后（rebase 后线性化——
本迁移与 discovery 迁移原同以 e8b1d5f9a3c7 为父会成双头）。

拍板依据：`docs/audit/下一步实施台账-2026-11-07.md` §11.3（2026-11-07 20:38
用户「确认」＝① 宿主轮询领取，六条决策级约束）：

1. 方向恒为宿主 → 服务端单向（容器不反向连宿主）——本迁移只扩服务端状态面；
2. 领取/回执两条写路由幂等 + 复用既有鉴权，`queued`/`host_running` 纳入
   `agent_runs` 状态机——本迁移扩 status CHECK（`host_running` 新终态前态，
   既有七态不动）；
3. 超时/失联**只标记不自动重试**（H4）——`host_lost_at` 标记列；
4. 凭据只在宿主内存管道、零落盘——服务端只存 `host_token_hash`（sha256，
   供轮换比对与审计，绝不回存明文）；
5. `zcode_contract.py` 唯一 argv/汇总来源——纯路由/状态层，无 CLI 语义；
6. 人工中转仅为降级验证——不设表。

additive-only：4 新列可空有默认；status CHECK 为置换（对齐 T-J2/d9f4a7c2e6b1
先例：加约束值零列重建）。downgrade 逆序还原。

Backup hint: additive only; downgrade restores previous CHECK + drops columns.
"""
import sqlalchemy as sa
from alembic import op

revision = "f6d3a9c1e7b2"
down_revision = "c3d5e7f9a1b4"
branch_labels = None
depends_on = None

_OLD_STATUS_CHECK = (
    "status IN ('queued', 'running', 'completed', 'succeeded_but_receipt_invalid',"
    " 'failed', 'timeout', 'budget_exceeded')"
)
_NEW_STATUS_CHECK = (
    "status IN ('queued', 'running', 'host_running', 'completed',"
    " 'succeeded_but_receipt_invalid', 'failed', 'timeout', 'budget_exceeded')"
)


def upgrade() -> None:
    # ① status CHECK 置换：先放宽（加 host_running）再收紧（旧 CHECK 已被
    #    新值域覆盖，直接 drop+create 新的即可——中间无非法值窗口：新 CHECK
    #    是旧值域的超集）。
    op.drop_constraint("ck_agent_runs_status", "agent_runs", type_="check")
    op.create_check_constraint("ck_agent_runs_status", "agent_runs", _NEW_STATUS_CHECK)

    # ② 宿主领取/回执列（additive-only，全部可空）
    op.add_column(
        "agent_runs",
        sa.Column(
            "execution_provider",
            sa.String(length=16),
            nullable=False,
            server_default="sandbox",
        ),
    )
    op.add_column(
        "agent_runs",
        sa.Column("host_claimed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "agent_runs",
        sa.Column("host_token_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "agent_runs",
        sa.Column("host_receipt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "agent_runs",
        sa.Column("host_lost_at", sa.DateTime(timezone=True), nullable=True),
    )
    # 领取面查询索引：待领取 run 按 queued+provider 定位（列表小，单列即可）
    op.create_index("ix_agent_runs_provider_status", "agent_runs", ["execution_provider", "status"])


def downgrade() -> None:
    op.drop_index("ix_agent_runs_provider_status", table_name="agent_runs")
    op.drop_column("agent_runs", "host_lost_at")
    op.drop_column("agent_runs", "host_receipt_at")
    op.drop_column("agent_runs", "host_token_hash")
    op.drop_column("agent_runs", "host_claimed_at")
    op.drop_column("agent_runs", "execution_provider")
    op.drop_constraint("ck_agent_runs_status", "agent_runs", type_="check")
    op.create_check_constraint("ck_agent_runs_status", "agent_runs", _OLD_STATUS_CHECK)
