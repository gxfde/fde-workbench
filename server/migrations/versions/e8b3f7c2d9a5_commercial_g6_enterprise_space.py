"""商业化 G6：企业空间与企业自助交付（enterprise_triage_decisions / enterprise_paid_option_choices）。

任务书 §10（T-06/T-08）的落地形（ADR-010 企业空间与企业自助交付）：
- enterprise_triage_decisions：三档分流**人工判定**留痕行（交付咨询环节）——
  判定人/时刻/定性依据（rationale 必填）＋可选书面依据（指针＋sha256 指纹，
  同有同无 CHECK）；``tier`` 值域复用 G2 三档定性闭集（单一权威，不另立枚举）；
  系统不做任何硬规则判定（零阈值常量——判定＝人的输入不是计算输出）。
- enterprise_paid_option_choices：付费选项选择行（**append-only**——企业自主
  选择不被取消；换主意＝企业本人再选，旧行 superseded_at 留痕；部分唯一索引
  保证一主体至多一份现行选择；顾问跟进注记三元组原子性 CHECK）。
- enterprise_quota_subjects 加列 problem_description（企业自助注册时描述业务
  问题；可空＝兼容 G2 admin 授予的存量行，零既有语义变化）。

**「同一主体两种状态」不落状态列**——付费交付态＝存在现行选择行（派生读面），
**不是账**：科目层（commercial_revenue_ledger）零触碰，不另立第三套计费口径。

**零播种**：分流判定与付费选择都是业务动作行，不预置任何默认行；
**零金额零数值**（本期不落数值红线——哨兵用例钉住选项载荷无数字）。

Backup hint: additive only; downgrade drops child-first
(enterprise_paid_option_choices → enterprise_triage_decisions → 加列回退)。
"""
import sqlalchemy as sa
from alembic import op

revision = "e8b3f7c2d9a5"
down_revision = "b3e8a6c2d4f7"
branch_labels = None
depends_on = None

_TIERS = ("standardized", "multi_system", "complex")


def _timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    op.add_column(
        "enterprise_quota_subjects",
        sa.Column("problem_description", sa.Text(), nullable=True),
    )
    op.create_table(
        "enterprise_triage_decisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("subject_key", sa.String(length=18), nullable=False),
        sa.Column("tier", sa.String(length=20), nullable=False),
        sa.Column("decided_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("rationale", sa.String(length=2000), nullable=False),
        sa.Column("basis_uri", sa.String(length=500), nullable=True),
        sa.Column("basis_sha256", sa.String(length=64), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        *_timestamp_columns(),
        sa.CheckConstraint(
            f"tier IN {_TIERS!r}", name="ck_enterprise_triage_decisions_tier"
        ),
        sa.CheckConstraint(
            "(basis_uri IS NULL) = (basis_sha256 IS NULL)",
            name="ck_enterprise_triage_decisions_basis_atomic",
        ),
        sa.ForeignKeyConstraint(
            ["subject_key"],
            ["enterprise_quota_subjects.subject_key"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["decided_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_enterprise_triage_decisions_subject",
        "enterprise_triage_decisions",
        ["subject_key"],
    )
    op.create_table(
        "enterprise_paid_option_choices",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("subject_key", sa.String(length=18), nullable=False),
        sa.Column("option_key", sa.String(length=20), nullable=False),
        sa.Column("chosen_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("chosen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("advisor_note", sa.String(length=500), nullable=True),
        sa.Column("advisor_user_id", sa.String(length=36), nullable=True),
        sa.Column("advisor_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamp_columns(),
        sa.CheckConstraint(
            f"option_key IN {_TIERS!r}", name="ck_enterprise_paid_option_choices_option"
        ),
        sa.CheckConstraint(
            "(advisor_note IS NULL) = (advisor_user_id IS NULL) "
            "AND (advisor_note IS NULL) = (advisor_at IS NULL)",
            name="ck_enterprise_paid_option_choices_advisor_atomic",
        ),
        sa.ForeignKeyConstraint(
            ["subject_key"],
            ["enterprise_quota_subjects.subject_key"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["chosen_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["advisor_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_enterprise_paid_option_choices_subject",
        "enterprise_paid_option_choices",
        ["subject_key"],
    )
    op.create_index(
        "uq_enterprise_paid_option_choices_active",
        "enterprise_paid_option_choices",
        ["subject_key"],
        unique=True,
        postgresql_where=sa.text("superseded_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_enterprise_paid_option_choices_active", table_name="enterprise_paid_option_choices"
    )
    op.drop_index(
        "ix_enterprise_paid_option_choices_subject", table_name="enterprise_paid_option_choices"
    )
    op.drop_table("enterprise_paid_option_choices")
    op.drop_index(
        "ix_enterprise_triage_decisions_subject", table_name="enterprise_triage_decisions"
    )
    op.drop_table("enterprise_triage_decisions")
    op.drop_column("enterprise_quota_subjects", "problem_description")
