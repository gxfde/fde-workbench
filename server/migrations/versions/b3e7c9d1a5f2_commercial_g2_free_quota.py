"""商业化 G2：企业免费额度（enterprise_quota_subjects + enterprise_free_quota）。

任务书 T-07 目标模型的落地形（ADR-004 主体认定 + ADR-007 人工确认默认）：
- enterprise_quota_subjects：PK=规范化统一社会信用代码（mod-31 校验位服务层
  验证）——**额度键挂主体而非账号**（换账号不重置的结构性保证）；
- enterprise_free_quota：每主体一份，granted→in_progress→completed 三态
  CHECK 联锁（绑定账号/完成时刻/企业确认的形状约束），**无重置路径**。

Backup hint: additive only; downgrade drops child-first
(enterprise_free_quota → enterprise_quota_subjects).
"""
import sqlalchemy as sa
from alembic import op

revision = "b3e7c9d1a5f2"
down_revision = "e9c4a1f7b3d2"
branch_labels = None
depends_on = None


def _timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "enterprise_quota_subjects",
        sa.Column("subject_key", sa.String(length=18), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column("first_user_id", sa.String(length=36), nullable=False),
        sa.Column("note", sa.String(length=255), nullable=True),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("subject_key"),
        sa.ForeignKeyConstraint(["first_user_id"], ["users.id"], ondelete="RESTRICT"),
    )
    op.create_table(
        "enterprise_free_quota",
        sa.Column("subject_key", sa.String(length=18), nullable=False),
        sa.Column("state", sa.String(length=12), server_default="granted", nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("granted_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("bound_user_id", sa.String(length=36), nullable=True),
        sa.Column("bound_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deliverables", sa.JSON(), nullable=True),
        sa.Column("enterprise_confirmed_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("enterprise_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("subject_key"),
        sa.ForeignKeyConstraint(
            ["subject_key"], ["enterprise_quota_subjects.subject_key"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["granted_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["bound_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["enterprise_confirmed_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.CheckConstraint(
            "state IN ('granted', 'in_progress', 'completed')",
            name="ck_enterprise_free_quota_state",
        ),
        sa.CheckConstraint(
            "(state = 'granted' AND bound_user_id IS NULL AND completed_at IS NULL "
            "AND enterprise_confirmed_at IS NULL) OR "
            "(state <> 'granted' AND bound_user_id IS NOT NULL)",
            name="ck_enterprise_free_quota_bound_shape",
        ),
        sa.CheckConstraint(
            "state != 'completed' AND completed_at IS NULL "
            "OR state = 'completed' AND completed_at IS NOT NULL",
            name="ck_enterprise_free_quota_completed_shape",
        ),
        sa.CheckConstraint(
            "enterprise_confirmed_at IS NULL OR state = 'completed'",
            name="ck_enterprise_free_quota_confirm_requires_completed",
        ),
    )


def downgrade() -> None:
    op.drop_table("enterprise_free_quota")
    op.drop_table("enterprise_quota_subjects")
