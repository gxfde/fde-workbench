"""D2 合成裁决：交付包 agent_assisted 协同标记 + 订单难度（goal-d8，PRD §6）

delivery_packages.agent_assisted：接单人显式声明「智能体协同」（PRD §6.3，
D2 裁决三）。声明后才启用 T1–T6 评审强制门与全链路溯源联动；不声明 = 纯
人工交付，行为与 v0.2.0 完全一致。8 态机零改动——本列不是状态，声明动作
只留 OperationEvent 留痕，不进 TRANSITIONS。

delivery_packages.difficulty：订单难度三档（O-4，PRD §6.4）——low=agent
独立出草稿+人终审、medium=agent 草稿+强制终审（T4 升 full）、high=不派发
给智能体（协同声明前置禁入）。发布交付包时由平台侧定档冻结；start_run
按 low→standard / medium→high 映射自动带入 agent_runs.difficulty（T4 免手
报，显式手报与订单不一致 400）。

Backup hint: additive only; downgrade drops the constraint then the columns.
"""
import sqlalchemy as sa
from alembic import op


revision = "b8c2d6f0a4e7"
down_revision = "a7b4d9e2c6f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "delivery_packages",
        sa.Column(
            "agent_assisted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "delivery_packages",
        sa.Column("difficulty", sa.String(length=8), nullable=True),
    )
    op.create_check_constraint(
        "ck_delivery_packages_difficulty",
        "delivery_packages",
        "difficulty IS NULL OR difficulty IN ('low', 'medium', 'high')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_delivery_packages_difficulty", "delivery_packages", type_="check"
    )
    op.drop_column("delivery_packages", "difficulty")
    op.drop_column("delivery_packages", "agent_assisted")
