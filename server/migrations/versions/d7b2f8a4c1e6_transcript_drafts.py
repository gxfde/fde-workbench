"""T-A9 转写草稿区 + 访谈纪要正式库（goal-tb tb1，2026-11-07）

transcript_drafts（草稿区：T+7 临时区，状态机 draft→promoted|expired|discarded，
墓碑化清空正文/指纹/复核条目）+ interview_minutes（正式库：人工整理纪要 +
客户确认三要素；draft_id 为纯字符串指针，零外键引用草稿行——物理隔离）。

红线锚：录音原件永不进库（本迁移零二进制/零音频列）；转写文本过 T-A2
代号化管线（service 层接线）；无客户确认的转写文本无法进正式库
（ck_transcript_drafts_promoted_triple + service 双闸）。

Backup hint: additive only; downgrade drops the two tables child-first.
"""
import sqlalchemy as sa
from alembic import op


revision = "d7b2f8a4c1e6"
down_revision = "b2e8f4a6c9d3"
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
        "transcript_drafts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
        sa.Column("redaction_entries", sa.JSON(), nullable=True),
        sa.Column("source_kind", sa.String(length=16), server_default="manual", nullable=False),
        sa.Column("engine", sa.String(length=60), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="draft", nullable=False),
        sa.Column("client_confirmed_by", sa.String(length=160), nullable=True),
        sa.Column("client_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("client_confirmation_method", sa.String(length=16), nullable=True),
        sa.Column("promoted_ref", sa.String(length=80), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cleaned_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "status IN ('draft', 'promoted', 'expired', 'discarded')",
            name="ck_transcript_drafts_status",
        ),
        sa.CheckConstraint(
            "source_kind IN ('manual', 'asr')",
            name="ck_transcript_drafts_source_kind",
        ),
        sa.CheckConstraint(
            "client_confirmation_method IS NULL OR client_confirmation_method IN ('verbal', 'written', 'meeting')",
            name="ck_transcript_drafts_confirmation_method",
        ),
        sa.CheckConstraint(
            "(source_kind = 'manual') = (engine IS NULL)",
            name="ck_transcript_drafts_engine_presence",
        ),
        sa.CheckConstraint(
            "(status <> 'draft') OR (content IS NOT NULL AND content_sha256 IS NOT NULL AND redaction_entries IS NOT NULL)",
            name="ck_transcript_drafts_active_content",
        ),
        sa.CheckConstraint(
            "(status = 'draft') OR (content IS NULL AND content_sha256 IS NULL AND redaction_entries IS NULL)",
            name="ck_transcript_drafts_tombstone_content",
        ),
        sa.CheckConstraint(
            "(status <> 'promoted') OR ("
            "client_confirmed_by IS NOT NULL AND client_confirmed_at IS NOT NULL "
            "AND client_confirmation_method IS NOT NULL AND promoted_ref IS NOT NULL)",
            name="ck_transcript_drafts_promoted_triple",
        ),
        sa.CheckConstraint("char_length(content_sha256) = 64", name="ck_transcript_drafts_sha_len"),
    )
    op.create_index(
        "ix_transcript_drafts_project_status", "transcript_drafts", ["project_id", "status"]
    )
    op.create_index(
        "ix_transcript_drafts_purge_due", "transcript_drafts", ["status", "expires_at"]
    )
    op.create_table(
        "interview_minutes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        # 纯字符串指针（无 FK）：正式库不引用草稿行本体（物理隔离）
        sa.Column("draft_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("redaction_hits", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("client_confirmed_by", sa.String(length=160), nullable=False),
        sa.Column("client_confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("client_confirmation_method", sa.String(length=16), nullable=False),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "client_confirmation_method IN ('verbal', 'written', 'meeting')",
            name="ck_interview_minutes_confirmation_method",
        ),
        sa.CheckConstraint("char_length(content_sha256) = 64", name="ck_interview_minutes_sha_len"),
        sa.UniqueConstraint("draft_id", name="uq_interview_minutes_draft"),
    )
    op.create_index(
        "ix_interview_minutes_project_created", "interview_minutes", ["project_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_interview_minutes_project_created", table_name="interview_minutes")
    op.drop_table("interview_minutes")
    op.drop_index("ix_transcript_drafts_purge_due", table_name="transcript_drafts")
    op.drop_index("ix_transcript_drafts_project_status", table_name="transcript_drafts")
    op.drop_table("transcript_drafts")
