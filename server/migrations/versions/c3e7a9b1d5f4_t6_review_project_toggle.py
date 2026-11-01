"""T6 高成本 run 前评审基座（goal-d11，总纲 §2.2 T6）

projects.t6_review_disabled：T6 闸的项目级关闭开关（总纲原文「可按项目
关闭」的忠实落地）。全局阈值在 settings（t6_review_cost_threshold，0=全局
关闭）；项目开关只在本项目关闭 T6 前置评审——默认 false（启用）。

Backup hint: additive only; downgrade drops the column.
"""
import sqlalchemy as sa
from alembic import op

revision = "c3e7a9b1d5f4"
down_revision = "a1d3f5b7c9e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "t6_review_disabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("projects", "t6_review_disabled")
