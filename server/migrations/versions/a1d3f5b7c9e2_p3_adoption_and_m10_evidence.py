"""P3 采纳流 + M10 纪要证据基座（goal-d10，PRD §3.2 P3 收口 / PartyMode §8 M10）

project_guidance_analyses：翻译草稿「采纳流」——ready 草稿升格为项目指引
新版本（version_number 递增，status=draft 待人工确认）。source_kind 区分
预调研 DOCX 分析与翻译器草稿两个来源；翻译器来源无源文件，source_file_id /
source_file_version_id 放宽 nullable（source_filename 存
translator:<translation_id> 保持可读可追溯，不放宽）；(project_id,
translation_id) 唯一约束在数据库层防同项目重复采纳。

seat_action_ledger：action_type 放宽 + 'translation'——O-3 翻译器额度随
采纳落账（翻译时无项目维度不计；采纳时刻项目上下文齐备，随路落，决议②）。

Backup hint: additive / constraint-widening only; downgrade narrows back
(translation ledger rows must be deleted before narrowing).
"""
import sqlalchemy as sa
from alembic import op

revision = "a1d3f5b7c9e2"
down_revision = "c5e9b3d7a1f5"
branch_labels = None
depends_on = None

_GUIDANCE_KIND_CHECK = "ck_project_guidance_source_kind"
_LEDGER_ACTION_CHECK = "ck_seat_action_ledger_action_type"
_ADOPTION_UNIQUE = "uq_project_guidance_project_translation"


def upgrade() -> None:
    op.add_column(
        "project_guidance_analyses",
        sa.Column(
            "source_kind",
            sa.String(length=24),
            nullable=False,
            server_default="presurvey_docx",
        ),
    )
    op.create_check_constraint(
        _GUIDANCE_KIND_CHECK,
        "project_guidance_analyses",
        "source_kind IN ('presurvey_docx', 'translator_draft')",
    )
    op.add_column(
        "project_guidance_analyses",
        sa.Column("translation_id", sa.String(length=36), nullable=True),
    )
    op.create_unique_constraint(
        _ADOPTION_UNIQUE, "project_guidance_analyses", ["project_id", "translation_id"]
    )
    # 翻译器来源无源文件：NOT NULL 放宽（旧行不受影响——历史行全有源）。
    op.alter_column("project_guidance_analyses", "source_file_id", nullable=True)
    op.alter_column(
        "project_guidance_analyses", "source_file_version_id", nullable=True
    )

    # O-3 额度枚举放宽：constraint 先删后建（PostgreSQL 无 IF NOT EXISTS 语义）。
    op.drop_constraint(_LEDGER_ACTION_CHECK, "seat_action_ledger", type_="check")
    op.create_check_constraint(
        _LEDGER_ACTION_CHECK,
        "seat_action_ledger",
        "action_type IN ('agent_run', 'meeting_convene', 'ai_chat', 'translation')",
    )


def downgrade() -> None:
    op.drop_constraint(_LEDGER_ACTION_CHECK, "seat_action_ledger", type_="check")
    op.create_check_constraint(
        _LEDGER_ACTION_CHECK,
        "seat_action_ledger",
        "action_type IN ('agent_run', 'meeting_convene', 'ai_chat')",
    )
    op.drop_constraint(_ADOPTION_UNIQUE, "project_guidance_analyses", type_="unique")
    op.drop_column("project_guidance_analyses", "translation_id")
    op.drop_constraint(_GUIDANCE_KIND_CHECK, "project_guidance_analyses", type_="check")
    op.drop_column("project_guidance_analyses", "source_kind")
    # 回窄 nullable 前必须确认无 NULL 行（translator 来源版本未清时回窄会失败——
    # 有意为之：downgrade 不静默丢数据）。
    op.alter_column(
        "project_guidance_analyses",
        "source_file_version_id",
        existing_type=sa.String(length=36),
        nullable=False,
    )
    op.alter_column(
        "project_guidance_analyses",
        "source_file_id",
        existing_type=sa.String(length=36),
        nullable=False,
    )
