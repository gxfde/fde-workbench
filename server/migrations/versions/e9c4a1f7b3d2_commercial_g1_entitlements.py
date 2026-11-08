"""商业化 G1：权益四分与角色分层（commercial_entitlements + training_entitlements）。

任务书 T-04/T-05 目标模型的落地形（ADR-001/ADR-002/ADR-006 裁决）：
- commercial_entitlements：一人一份（PK=user_id），四类权益独立列组
  （角色分层 R1–R4 可空／年度席位 seat_*／认证 certification_*／交付资格），
  五条 CHECK 闭集；**值域无任何 L 开头角色枚举**（对外 L 编号仅经
  commercial/ladder.py 映射推导，不落库）。
- training_entitlements：培训权益购买行 1:N（training/certification/mentoring），
  valid_until 可空（陪跑期限数值本期不定数，任务书 §1.2-6）。

Backup hint: additive only; downgrade drops child-first
(training_entitlements → commercial_entitlements).
"""
import sqlalchemy as sa
from alembic import op

revision = "e9c4a1f7b3d2"
down_revision = "e7c4a9d2f6b8"  # rebase 重排：挂 #215（V3.1 P1-1）迁移之后，消解同窗口双头
branch_labels = None
depends_on = None


def _timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "commercial_entitlements",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("commercial_role", sa.String(length=2), nullable=True),
        sa.Column("seat_status", sa.String(length=10), server_default="none", nullable=False),
        sa.Column("seat_source", sa.String(length=24), nullable=True),
        sa.Column("seat_activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("seat_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("certification_status", sa.String(length=16), server_default="uncertified", nullable=False),
        sa.Column("certification_source", sa.String(length=120), nullable=True),
        sa.Column("delivery_eligibility", sa.String(length=10), server_default="none", nullable=False),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("user_id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "commercial_role IS NULL OR commercial_role IN ('R1', 'R2', 'R3', 'R4')",
            name="ck_commercial_entitlements_role",
        ),
        sa.CheckConstraint(
            "seat_status IN ('none', 'active')",
            name="ck_commercial_entitlements_seat_status",
        ),
        sa.CheckConstraint(
            "seat_source IS NULL OR seat_source IN "
            "('first_delivery', 'bootcamp_practical', 'bootcamp_mentorship')",
            name="ck_commercial_entitlements_seat_source",
        ),
        sa.CheckConstraint(
            "certification_status IN ('uncertified', 'certified')",
            name="ck_commercial_entitlements_certification",
        ),
        sa.CheckConstraint(
            "delivery_eligibility IN ('none', 'eligible')",
            name="ck_commercial_entitlements_delivery_eligibility",
        ),
    )
    op.create_table(
        "training_entitlements",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("item_type", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=10), server_default="active", nullable=False),
        sa.Column("purchased_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("granted_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("note", sa.String(length=255), nullable=True),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["granted_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "item_type IN ('training', 'certification', 'mentoring')",
            name="ck_training_entitlements_item_type",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'revoked')",
            name="ck_training_entitlements_status",
        ),
    )
    op.create_index(
        "ix_training_entitlements_user",
        "training_entitlements",
        ["user_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_training_entitlements_user", table_name="training_entitlements")
    op.drop_table("training_entitlements")
    op.drop_table("commercial_entitlements")
