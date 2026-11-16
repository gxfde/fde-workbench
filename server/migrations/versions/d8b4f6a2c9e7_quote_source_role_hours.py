"""quotes 加 source（报价来源）与 role_hours（角色工时明细）——W3（party 评审）

source：仿真隔离正式化。派单仿真器（dispatch/simulator.py）此前直接构造
status='finalized' 的 Quote 污染首单判定，W1-2 已按 Q-SIM- 前缀启发式排除；
本迁移落正式机制——source 列（manual/simulation），finalize 首单计数改为
``source != 'simulation'``（前缀排除保留作双保险）。存量行经 server_default
归位 manual，行为逐位不变。

role_hours：P7「人力未按角色分列」。可选 JSON（键=角色名、值=该角色 ideal
工时），服务层校验非负且合计=ideal_hours；不填＝维持现状（角色不细分）。
"""
import sqlalchemy as sa
from alembic import op

revision = "d8b4f6a2c9e7"
down_revision = "b3e7a1c9f4d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "quotes",
        sa.Column(
            "source",
            sa.String(length=12),
            nullable=False,
            server_default=sa.text("'manual'"),
        ),
    )
    op.add_column("quotes", sa.Column("role_hours", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("quotes", "role_hours")
    op.drop_column("quotes", "source")
