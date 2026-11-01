"""O-3 额度台账 + T4 难度列（goal-d7，自动交付 §6 / 总纲 §2.2 T4）

seat_action_ledger：O-3「100 次工作台动作/月」计量台账（seat 归集）。一次
动作 = 一条行：agent_run（方案生成 run，发起时刻计；rehearsal: 演练前缀
不计）、meeting_convene（工具面召集，人工开会不占额度）、ai_chat（预调研
AI 分析 worker 成功就绪时计）。over_quota 只标注不拦截——超额转透明计价
加油包，「交付中途绝不静默断供」（自动交付 §6 透明化硬规则）。

agent_runs.difficulty：T4 高难度加座的 run 侧事实（发起人声明，责任人
人工承担——架构方案 §6.4 发起人即责任人；派单订单难度自动带入随 d8）。

Backup hint: additive only; downgrade drops the column then the table.
"""
import sqlalchemy as sa
from alembic import op


revision = "a7b4d9e2c6f1"
down_revision = "f6a9c3e1d7b4"
branch_labels = None
depends_on = None


def _timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column(
            "difficulty",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'standard'"),
        ),
    )
    op.create_check_constraint(
        "ck_agent_runs_difficulty",
        "agent_runs",
        "difficulty IN ('standard', 'high')",
    )

    op.create_table(
        "seat_action_ledger",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        # seat 归集键：动作发起人（run 发起人 / 召集触发 run 的发起人 / 分析创建人）
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("action_type", sa.String(length=24), nullable=False),
        # 溯源指针：run id / meeting id / analysis id（软引用不设 FK，沿
        # agent_runs.retry_of 偏离先例——被引用行允许归档清理）
        sa.Column("ref_id", sa.String(length=64), nullable=True),
        sa.Column("units", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "over_quota", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "action_type IN ('agent_run', 'meeting_convene', 'ai_chat')",
            name="ck_seat_action_ledger_action_type",
        ),
        sa.CheckConstraint("units >= 0", name="ck_seat_action_ledger_units"),
    )
    op.create_index(
        "ix_seat_action_ledger_user_created",
        "seat_action_ledger",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_seat_action_ledger_user_created", table_name="seat_action_ledger"
    )
    op.drop_table("seat_action_ledger")
    op.drop_constraint("ck_agent_runs_difficulty", "agent_runs", type_="check")
    op.drop_column("agent_runs", "difficulty")
