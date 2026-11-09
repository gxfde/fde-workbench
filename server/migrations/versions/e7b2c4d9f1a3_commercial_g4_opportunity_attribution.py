"""商业化 G4：商机归属与渠道保护（commercial_opportunities + commercial_opportunity_rules）。

任务书 §8（T-09 商机归属与渠道保护）的落地形（ADR-009）：
- commercial_opportunities：七步链路（报备→企业确认→平台确认归属→保护期→售前→
  撮合→结算）的商机主体行；归属是本域事实，**企业侧立项路径无任何写路径可触碰
  本行**（不自动易主的结构性保证）。
  CHECK 联锁含「保护中必有起止时刻」——**结构上不可能出现永久锁定企业**。
- commercial_opportunity_rules：五个规则位（保护期长度／续期条件／客户自主选择权／
  争议处理机制／归属判定），**迁移播种一律 unset**——规则数值本期不定数，任何路径
  都不得预写业务默认值（成文规则：docs/commercialization/rules/opportunity-attribution-rules.md）。

**未改动既有表**（零加列）；dispatch 侧仅在 channel_guard 增一条惰性附加判定。

Backup hint: additive only; downgrade drops child-first
(commercial_opportunity_rules → commercial_opportunities).
"""
import sqlalchemy as sa
from alembic import op

revision = "e7b2c4d9f1a3"
down_revision = "c4f7a2d9e1b6"
branch_labels = None
depends_on = None


def _timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "commercial_opportunity_rules",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value_kind", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=12), server_default="unset", nullable=False),
        sa.Column("days", sa.Integer(), nullable=True),
        sa.Column("criteria", sa.String(length=500), nullable=True),
        sa.Column("source_uri", sa.String(length=500), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("configured_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("configured_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("key"),
        sa.ForeignKeyConstraint(["configured_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "status IN ('unset', 'configured')",
            name="ck_commercial_opportunity_rules_status",
        ),
        sa.CheckConstraint(
            "value_kind IN ('days', 'criteria')",
            name="ck_commercial_opportunity_rules_value_kind",
        ),
        sa.CheckConstraint(
            "status <> 'unset' OR (days IS NULL AND criteria IS NULL)",
            name="ck_commercial_opportunity_rules_unset_has_no_value",
        ),
        sa.CheckConstraint(
            "status <> 'configured' OR ("
            "(value_kind = 'days' AND days IS NOT NULL AND days > 0 AND criteria IS NULL) OR "
            "(value_kind = 'criteria' AND criteria IS NOT NULL AND days IS NULL))",
            name="ck_commercial_opportunity_rules_configured_shape",
        ),
        sa.CheckConstraint(
            "status <> 'configured' OR (source_uri IS NOT NULL AND content_hash IS NOT NULL)",
            name="ck_commercial_opportunity_rules_configured_has_evidence",
        ),
    )

    op.create_table(
        "commercial_opportunities",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("enterprise_code", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("status", sa.String(length=24), server_default="submitted", nullable=False),
        sa.Column("reported_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("reported_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("source_uri", sa.String(length=500), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("enterprise_confirmed_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("enterprise_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("enterprise_confirmation_uri", sa.String(length=500), nullable=True),
        sa.Column("enterprise_confirmation_hash", sa.String(length=64), nullable=True),
        sa.Column("attribution_owner_user_id", sa.String(length=36), nullable=True),
        sa.Column("attribution_confirmed_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("attribution_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attribution_uri", sa.String(length=500), nullable=True),
        sa.Column("attribution_hash", sa.String(length=64), nullable=True),
        sa.Column("protection_status", sa.String(length=16), server_default="unconfigured", nullable=False),
        sa.Column("protection_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("protection_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("protection_renewal_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("protection_renewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("presales_owner_user_id", sa.String(length=36), nullable=True),
        sa.Column("matched_delivery_package_id", sa.String(length=36), nullable=True),
        sa.Column("customer_choice_package_id", sa.String(length=36), nullable=True),
        sa.Column("settled_ledger_entry_id", sa.String(length=36), nullable=True),
        sa.Column("rule_snapshot", sa.JSON(), nullable=True),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disputed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dispute_uri", sa.String(length=500), nullable=True),
        sa.Column("dispute_hash", sa.String(length=64), nullable=True),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["reported_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["enterprise_confirmed_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["attribution_owner_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["attribution_confirmed_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["presales_owner_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["matched_delivery_package_id"], ["delivery_packages.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["customer_choice_package_id"], ["delivery_packages.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["settled_ledger_entry_id"], ["commercial_revenue_ledger.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "status IN ('submitted', 'enterprise_confirmed', 'attribution_confirmed', "
            "'presales', 'matched', 'settled', 'disputed', 'withdrawn')",
            name="ck_commercial_opportunities_status",
        ),
        sa.CheckConstraint(
            "protection_status IN ('unconfigured', 'active', 'expired', 'revoked')",
            name="ck_commercial_opportunities_protection_status",
        ),
        sa.CheckConstraint(
            "attribution_owner_user_id IS NULL OR attribution_confirmed_at IS NOT NULL",
            name="ck_commercial_opportunities_attribution_shape",
        ),
        sa.CheckConstraint(
            "status NOT IN ('presales', 'matched', 'settled') "
            "OR attribution_owner_user_id IS NOT NULL",
            name="ck_commercial_opportunities_stage_requires_owner",
        ),
        sa.CheckConstraint(
            "protection_status <> 'active' OR "
            "(protection_started_at IS NOT NULL AND protection_expires_at IS NOT NULL)",
            name="ck_commercial_opportunities_protection_window",
        ),
        sa.CheckConstraint(
            "protection_status <> 'active' OR protection_expires_at > protection_started_at",
            name="ck_commercial_opportunities_protection_order",
        ),
    )
    op.create_index(
        "ix_commercial_opportunities_enterprise",
        "commercial_opportunities",
        ["enterprise_code"],
    )
    op.create_index(
        "ix_commercial_opportunities_reporter",
        "commercial_opportunities",
        ["reported_by_user_id"],
    )
    op.create_index(
        "ix_commercial_opportunities_status",
        "commercial_opportunities",
        ["status"],
    )

    # 规则位种子：**全部 unset**（规则数值本期不定数——不得预写业务默认值）
    op.execute(
        sa.text(
            "INSERT INTO commercial_opportunity_rules "
            "(key, value_kind, status, created_at, updated_at) VALUES "
            "('protection_period_days', 'days', 'unset', now(), now()), "
            "('renewal_conditions', 'criteria', 'unset', now(), now()), "
            "('customer_choice', 'criteria', 'unset', now(), now()), "
            "('dispute_handling', 'criteria', 'unset', now(), now()), "
            "('attribution_criteria', 'criteria', 'unset', now(), now())"
        )
    )


def downgrade() -> None:
    op.drop_table("commercial_opportunities")
    op.drop_table("commercial_opportunity_rules")
