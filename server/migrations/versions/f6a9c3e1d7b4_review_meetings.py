"""评审会三表 + T2 强制门基座（goal-d5，技术实施方案 §2 / PartyMode §6）

review_meetings（+gate_tier/triggered_by_run_id/trigger/min_difficulty 决议
增量，D7 关联落会议侧）/ review_meeting_turns / review_meeting_minutes
（sealed_sha256 不可变）。纯增量零改既有表；triggered_by_run_id 为软引用
不设 FK（沿 agent_runs.retry_of 偏离先例，允许 run 归档清理）。

Backup hint: additive only; downgrade drops the three tables child-first.
"""
import sqlalchemy as sa
from alembic import op


revision = "f6a9c3e1d7b4"
down_revision = "d9c3e7f1a5b8"
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
        "review_meetings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("template_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="live", nullable=False),
        # 评审对象只读引用（solution_id/problem refs + sha256 快照指针）
        sa.Column("topic_refs", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("turn_budget", sa.Integer(), server_default=sa.text("2"), nullable=False),
        sa.Column("hosted_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("gate_tier", sa.String(length=16), server_default="lite", nullable=False),
        sa.Column("trigger", sa.String(length=16), server_default="manual", nullable=False),
        # D7：关联落会议侧；软引用（无 FK，允许 run 归档）
        sa.Column("triggered_by_run_id", sa.String(length=36), nullable=True),
        sa.Column("min_difficulty", sa.String(length=16), nullable=True),
        sa.Column("convened_by_agent_id", sa.String(length=36), nullable=True),
        sa.Column("degraded", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["hosted_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["convened_by_agent_id"], ["agent_registry.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "status IN ('live', 'paused', 'closed')", name="ck_review_meetings_status"
        ),
        sa.CheckConstraint(
            "gate_tier IN ('lite', 'std', 'full')", name="ck_review_meetings_gate_tier"
        ),
        sa.CheckConstraint(
            "trigger IN ('mandatory', 'adhoc', 'manual')", name="ck_review_meetings_trigger"
        ),
        sa.CheckConstraint("turn_budget >= 0", name="ck_review_meetings_turn_budget"),
    )
    op.create_index(
        "ix_review_meetings_project_status", "review_meetings", ["project_id", "status"]
    )

    op.create_table(
        "review_meeting_turns",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("meeting_id", sa.String(length=36), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("speaker_agent_id", sa.String(length=36), nullable=True),
        sa.Column("speaker_user_id", sa.String(length=36), nullable=True),
        # 正文 + source_refs + 立场标注（PartyMode §6 原文）
        sa.Column("content", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["meeting_id"], ["review_meetings.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["speaker_agent_id"], ["agent_registry.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["speaker_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("seq >= 1", name="ck_review_meeting_turns_seq"),
        sa.CheckConstraint(
            "(speaker_agent_id IS NOT NULL) <> (speaker_user_id IS NOT NULL)",
            name="ck_review_meeting_turns_speaker",
        ),
        sa.UniqueConstraint("meeting_id", "seq", name="uq_review_meeting_turns_meeting_seq"),
    )
    op.create_index(
        "ix_review_meeting_turns_meeting", "review_meeting_turns", ["meeting_id", "seq"]
    )

    op.create_table(
        "review_meeting_minutes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("meeting_id", sa.String(length=36), nullable=False),
        # 共识点（各带 source_refs）/ 分歧点（双方论点原样保留 + 冲突标注）/
        # 待办（owner 建议）
        sa.Column("consensus", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("disputes", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("todos", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("sealed_sha256", sa.String(length=64), nullable=False),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["meeting_id"], ["review_meetings.id"], ondelete="RESTRICT"
        ),
        sa.CheckConstraint(
            "char_length(sealed_sha256) = 64",
            name="ck_review_meeting_minutes_sealed_len",
        ),
        sa.UniqueConstraint("meeting_id", name="uq_review_meeting_minutes_meeting"),
    )


def downgrade() -> None:
    # 纯增量回滚：子表先删（minutes → turns → meetings）
    op.drop_table("review_meeting_minutes")
    op.drop_index("ix_review_meeting_turns_meeting", table_name="review_meeting_turns")
    op.drop_table("review_meeting_turns")
    op.drop_index("ix_review_meetings_project_status", table_name="review_meetings")
    op.drop_table("review_meetings")
