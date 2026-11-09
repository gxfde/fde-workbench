"""商业化 G3：收入科目层与订阅席位计费（任务书 §7 / T-10、T-11、T-13）。

ADR-003 §2.1–§2.5 的落地形（**additive only，零既有表改列**）：

- commercial_split_rules：分成比例配置结构（按角色 × 项目类型）——**本期不落
  数**：ratio_bp 只在 status='configured' 时可非空，unset 行恒 NULL；本期零行。
- commercial_fee_configs：费用/周期配置位（认证费金额、陪跑期限、认证通过线）
  ——**本期全部 unset**（缺省不可收款/不可判通过）。
- commercial_deduction_elections：扣费方式**书面选定**记录（指针 + sha256 指纹）。
- commercial_certification_records：认证挂模拟考核（挂 simulation_evaluations
  指针；通过线未配置 ⇒ pending_threshold，不判定通过）。
- commercial_revenue_ledger：**收入科目层**（ADR-003 §2.1 收入类型→金额→关联
  对象）；三类科目分别记账可分别核对；六项名目只定义归属；分成金额**引用**
  既有分账结果（seat_shares_for），不重算。

**未向 delivery_settlements 加任何列**（ADR-003 §2.1 / 任务书 §0.3 硬约束）。

Backup hint: additive only; downgrade drops child-first
(commercial_revenue_ledger → commercial_certification_records →
commercial_deduction_elections → commercial_fee_configs →
commercial_split_rules).
"""
import sqlalchemy as sa
from alembic import op

revision = "d5f9a3c7e1b4"
down_revision = "b3e7c9d1a5f2"
branch_labels = None
depends_on = None


def _timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "commercial_split_rules",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("role_code", sa.String(length=2), nullable=False),
        sa.Column("project_type", sa.String(length=32), nullable=False),
        sa.Column("ratio_bp", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=12), server_default="unset", nullable=False),
        sa.Column("source_uri", sa.String(length=500), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("configured_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("configured_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["configured_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("role_code", "project_type", name="uq_commercial_split_rules_dimension"),
        sa.CheckConstraint(
            "role_code IN ('R1', 'R2', 'R3', 'R4')", name="ck_commercial_split_rules_role"
        ),
        sa.CheckConstraint(
            "status IN ('unset', 'configured')", name="ck_commercial_split_rules_status"
        ),
        sa.CheckConstraint(
            "status <> 'configured' OR (ratio_bp IS NOT NULL AND ratio_bp >= 0 AND ratio_bp <= 10000)",
            name="ck_commercial_split_rules_ratio_shape",
        ),
        sa.CheckConstraint(
            "status <> 'unset' OR ratio_bp IS NULL",
            name="ck_commercial_split_rules_unset_has_no_ratio",
        ),
    )
    op.create_index(
        "ix_commercial_split_rules_role", "commercial_split_rules", ["role_code"]
    )

    op.create_table(
        "commercial_fee_configs",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value_kind", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=12), server_default="unset", nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("days", sa.Integer(), nullable=True),
        sa.Column("threshold", sa.Numeric(8, 4), nullable=True),
        sa.Column("source_uri", sa.String(length=500), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("configured_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("configured_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("key"),
        sa.ForeignKeyConstraint(["configured_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "status IN ('unset', 'configured')", name="ck_commercial_fee_configs_status"
        ),
        sa.CheckConstraint(
            "value_kind IN ('amount', 'days', 'threshold')",
            name="ck_commercial_fee_configs_value_kind",
        ),
        sa.CheckConstraint(
            "status <> 'unset' OR (amount IS NULL AND days IS NULL AND threshold IS NULL)",
            name="ck_commercial_fee_configs_unset_has_no_value",
        ),
        sa.CheckConstraint(
            "status <> 'configured' OR ("
            "(value_kind = 'amount' AND amount IS NOT NULL AND days IS NULL AND threshold IS NULL) OR "
            "(value_kind = 'days' AND days IS NOT NULL AND amount IS NULL AND threshold IS NULL) OR "
            "(value_kind = 'threshold' AND threshold IS NOT NULL AND amount IS NULL AND days IS NULL))",
            name="ck_commercial_fee_configs_configured_shape",
        ),
        sa.CheckConstraint(
            "status <> 'configured' OR (source_uri IS NOT NULL AND content_hash IS NOT NULL)",
            name="ck_commercial_fee_configs_configured_has_evidence",
        ),
    )

    op.create_table(
        "commercial_deduction_elections",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("method", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=12), server_default="elected", nullable=False),
        sa.Column("source_uri", sa.String(length=500), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("elected_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("elected_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["elected_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "method IN ('one_time', 'annual_installment')",
            name="ck_commercial_deduction_elections_method",
        ),
        sa.CheckConstraint(
            "status IN ('elected', 'superseded')",
            name="ck_commercial_deduction_elections_status",
        ),
    )
    op.create_index(
        "uq_commercial_deduction_elections_active",
        "commercial_deduction_elections",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'elected'"),
    )

    op.create_table(
        "commercial_certification_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("simulation_evaluation_id", sa.String(length=36), nullable=False),
        sa.Column("evaluation_verdict", sa.String(length=16), nullable=False),
        sa.Column("evaluation_score", sa.Numeric(8, 4), nullable=False),
        sa.Column("threshold", sa.Numeric(8, 4), nullable=True),
        sa.Column("status", sa.String(length=24), server_default="pending_threshold", nullable=False),
        sa.Column("source_uri", sa.String(length=500), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("decided_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["simulation_evaluation_id"], ["simulation_evaluations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["decided_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint(
            "user_id",
            "simulation_evaluation_id",
            name="uq_commercial_certification_records_identity",
        ),
        sa.CheckConstraint(
            "status IN ('pending_threshold', 'certified', 'rejected', 'revoked')",
            name="ck_commercial_certification_records_status",
        ),
        sa.CheckConstraint(
            "status <> 'certified' OR threshold IS NOT NULL",
            name="ck_commercial_certification_records_certified_has_threshold",
        ),
    )
    op.create_index(
        "ix_commercial_certification_records_user",
        "commercial_certification_records",
        ["user_id"],
    )

    op.create_table(
        "commercial_revenue_ledger",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("subject_type", sa.String(length=16), nullable=False),
        sa.Column("line_item", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=12), server_default="recorded", nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(length=8), server_default="CNY", nullable=False),
        sa.Column("subject_user_id", sa.String(length=36), nullable=True),
        sa.Column("payee_user_id", sa.String(length=36), nullable=True),
        sa.Column("quote_id", sa.String(length=36), nullable=True),
        sa.Column("payment_id", sa.String(length=36), nullable=True),
        sa.Column("contract_id", sa.String(length=36), nullable=True),
        sa.Column("delivery_settlement_id", sa.String(length=36), nullable=True),
        sa.Column("delivery_package_id", sa.String(length=36), nullable=True),
        sa.Column("training_entitlement_id", sa.String(length=36), nullable=True),
        sa.Column("split_rule_id", sa.String(length=36), nullable=True),
        sa.Column("package_code", sa.String(length=24), nullable=True),
        sa.Column("seat_source", sa.String(length=24), nullable=True),
        sa.Column("fee_key", sa.String(length=64), nullable=True),
        sa.Column("role_code", sa.String(length=2), nullable=True),
        sa.Column("project_type", sa.String(length=32), nullable=True),
        sa.Column("seat_shares", sa.JSON(), nullable=True),
        sa.Column("basis", sa.JSON(), nullable=True),
        sa.Column("source_uri", sa.String(length=500), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("recorded_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["subject_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["payee_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["quote_id"], ["quotes.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["contract_id"], ["contracts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["delivery_settlement_id"], ["delivery_settlements.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["delivery_package_id"], ["delivery_packages.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["training_entitlement_id"], ["training_entitlements.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["split_rule_id"], ["commercial_split_rules.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["recorded_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "subject_type IN ('seat_fee', 'training_fee', 'project_share')",
            name="ck_commercial_revenue_ledger_subject_type",
        ),
        sa.CheckConstraint(
            "line_item IN ('software_subscription', 'enterprise_subscription', 'usage', "
            "'project_fee', 'software_service_fee', 'platform_share')",
            name="ck_commercial_revenue_ledger_line_item",
        ),
        sa.CheckConstraint(
            "status IN ('recorded', 'reconciled', 'voided')",
            name="ck_commercial_revenue_ledger_status",
        ),
        sa.CheckConstraint("amount >= 0", name="ck_commercial_revenue_ledger_amount"),
        sa.CheckConstraint(
            "package_code IS NULL OR package_code IN "
            "('bootcamp_practical', 'bootcamp_mentorship', 'first_delivery')",
            name="ck_commercial_revenue_ledger_package_code",
        ),
        sa.CheckConstraint(
            "seat_source IS NULL OR seat_source IN "
            "('first_delivery', 'bootcamp_practical', 'bootcamp_mentorship')",
            name="ck_commercial_revenue_ledger_seat_source",
        ),
        sa.CheckConstraint(
            "role_code IS NULL OR role_code IN ('R1', 'R2', 'R3', 'R4')",
            name="ck_commercial_revenue_ledger_role_code",
        ),
        sa.CheckConstraint(
            "fee_key IS NULL OR fee_key IN ('certification_fee')",
            name="ck_commercial_revenue_ledger_fee_key",
        ),
        sa.CheckConstraint(
            "quote_id IS NOT NULL OR payment_id IS NOT NULL OR contract_id IS NOT NULL "
            "OR delivery_settlement_id IS NOT NULL OR delivery_package_id IS NOT NULL "
            "OR training_entitlement_id IS NOT NULL OR package_code IS NOT NULL",
            name="ck_commercial_revenue_ledger_association",
        ),
    )
    op.create_index(
        "ix_commercial_revenue_ledger_subject",
        "commercial_revenue_ledger",
        ["subject_type", "status"],
    )
    op.create_index(
        "ix_commercial_revenue_ledger_user",
        "commercial_revenue_ledger",
        ["subject_user_id"],
    )
    op.create_index(
        "ix_commercial_revenue_ledger_occurred",
        "commercial_revenue_ledger",
        ["occurred_at"],
    )

    # 配置位种子：**全部 unset**（认证费金额、陪跑期限、认证通过线本期不落数）。
    op.execute(
        sa.text(
            "INSERT INTO commercial_fee_configs "
            "(key, value_kind, status, created_at, updated_at) VALUES "
            "('certification_fee', 'amount', 'unset', now(), now()), "
            "('mentoring_period_days', 'days', 'unset', now(), now()), "
            "('certification_pass_threshold', 'threshold', 'unset', now(), now())"
        )
    )


def downgrade() -> None:
    op.drop_table("commercial_revenue_ledger")
    op.drop_table("commercial_certification_records")
    op.drop_table("commercial_deduction_elections")
    op.drop_table("commercial_fee_configs")
    op.drop_table("commercial_split_rules")
