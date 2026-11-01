"""P3 翻译器全量 + 终审台拍板收口基座（goal-d9，PRD §3.2 P3 / 总纲 U5）

translator_translations：翻译器门户的 AI 草稿落库表——引导式表单（客户画像
+ 诉求原话 + 阶段目标）→ AI 翻译管道 → validate_guidance_output 全契约校验
→ result_json 落库（confirmed 一律 False：AI 只出草稿，红线）。状态机
pending → running → ready/failed，沿预调研分析的 job 重试语义。

solution_review_checkpoints.handoff_run_id：L3 转人工（E-2）创建的 signoff
checkpoint 与触发 run 的显式软链（nullable）——终审台按 run 配对「接管→拍
板」时长（资深介入时长埋点），拍板事件 payload 经此携带 run_id。软引用无
FK（沿 triggered_by_run_id/retry_of 偏离先例，允许 run 归档清理）。

Backup hint: additive only; downgrade drops the column then the table.
"""
import sqlalchemy as sa
from alembic import op


revision = "c5e9b3d7a1f5"
down_revision = "b8c2d6f0a4e7"
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
    op.create_table(
        "translator_translations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("profile_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("customer_vision", sa.Text(), nullable=False),
        sa.Column("phase_objective", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        # validate_guidance_output 全契约草稿（confirmed 一律 False）
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("ai_model", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("ai_generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("failure_message", sa.Text(), nullable=False, server_default=""),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'ready', 'failed')",
            name="ck_translator_translations_status",
        ),
        sa.Index(
            "ix_translator_translations_creator",
            "created_by_user_id",
            "created_at",
        ),
    )
    op.add_column(
        "solution_review_checkpoints",
        sa.Column("handoff_run_id", sa.String(length=36), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("solution_review_checkpoints", "handoff_run_id")
    op.drop_table("translator_translations")
