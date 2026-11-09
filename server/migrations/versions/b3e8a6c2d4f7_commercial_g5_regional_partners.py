"""商业化 G5：区域合作商能力建设（regional_partner_tiers / regional_partners / regional_sale_gate / regional_service_settlements）。

任务书 §9（T-12a，**不含 T-12b**）的落地形（ADR-005 区域商业化闸）：
- regional_partner_tiers：正式区域合作商三档定价目录（T1/T2/T3，**以 BP v4.0
  为唯一基准**，迁移播种三行——定价定案目录数据）；城市服务伙伴没有档位行
  （按项目结算、不设固定年费是其结构性属性）。
- regional_partners：区域伙伴主体行（四阶段可区分）；CHECK 联锁含
  「前两阶段不授予独家区域权」与「正式档升级书面依据齐备」。
- regional_sale_gate：售卖开关单行表，**迁移播种 closed**——售卖能力默认关闭；
  开启的必要条件（合规条件清单四项：备案/披露/冷静期/两店一年资格）的签署
  证据（指针+指纹+签署时刻）先行登记，CHECK 结构性排除缺件开门。
- regional_service_settlements：城市服务伙伴按项目结算关联行（一单一结），
  **引用既有 G3 科目层** ``commercial_revenue_ledger`` 的 ``project_share`` 行，
  不建第二套结算引擎。

**试运营升级指标与首期金额本期不定数**：原文示例数值一律不落库
（哨兵用例钉死；见 ADR-005 §2.8 与成文规则 §3）——本迁移**不播种任何试运营数值**。

**未改动既有表**（零加列）。

Backup hint: additive only; downgrade drops child-first
(regional_service_settlements → regional_partners → regional_partner_tiers
→ regional_sale_gate).
"""
import sqlalchemy as sa
from alembic import op

revision = "b3e8a6c2d4f7"
down_revision = "e7b2c4d9f1a3"
branch_labels = None
depends_on = None


def _timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "regional_partner_tiers",
        sa.Column("tier_code", sa.String(length=8), nullable=False),
        sa.Column("annual_fee_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("included_seats", sa.Integer(), nullable=False),
        sa.Column("transfer_quota_seats", sa.Integer(), nullable=False),
        sa.Column("basis_reference", sa.String(length=200), nullable=False),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("tier_code"),
        sa.CheckConstraint(
            "tier_code IN ('T1', 'T2', 'T3')",
            name="ck_regional_partner_tiers_tier_code",
        ),
        sa.CheckConstraint(
            "annual_fee_amount > 0",
            name="ck_regional_partner_tiers_amount_positive",
        ),
        sa.CheckConstraint(
            "included_seats > 0 AND transfer_quota_seats >= 0 "
            "AND transfer_quota_seats < included_seats",
            name="ck_regional_partner_tiers_seats_shape",
        ),
    )
    # 定价目录种子：以 BP v4.0 为唯一基准（v4.0 终版，经蔡工拍板）
    op.bulk_insert(
        sa.table(
            "regional_partner_tiers",
            sa.column("tier_code"),
            sa.column("annual_fee_amount"),
            sa.column("included_seats"),
            sa.column("transfer_quota_seats"),
            sa.column("basis_reference"),
        ),
        [
            {"tier_code": "T1", "annual_fee_amount": 29800.00, "included_seats": 15,
             "transfer_quota_seats": 7, "basis_reference": "BP v4.0 附录 C（v4.0 终版，经蔡工拍板）"},
            {"tier_code": "T2", "annual_fee_amount": 59800.00, "included_seats": 30,
             "transfer_quota_seats": 15, "basis_reference": "BP v4.0 附录 C（v4.0 终版，经蔡工拍板）"},
            {"tier_code": "T3", "annual_fee_amount": 98000.00, "included_seats": 50,
             "transfer_quota_seats": 25, "basis_reference": "BP v4.0 附录 C（v4.0 终版，经蔡工拍板）"},
        ],
    )

    op.create_table(
        "regional_partners",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("partner_code", sa.String(length=80), nullable=False),
        sa.Column("region_name", sa.String(length=120), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("stage", sa.String(length=20), server_default="city_observer", nullable=False),
        sa.Column("applicant_user_id", sa.String(length=36), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("stage_changed_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("stage_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stage_evidence_uri", sa.String(length=500), nullable=True),
        sa.Column("stage_evidence_hash", sa.String(length=64), nullable=True),
        sa.Column("tier_code", sa.String(length=8), nullable=True),
        sa.Column("exclusive_territory", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["applicant_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["stage_changed_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "stage IN ('city_observer', 'city_service', 'formal_partner', 'regional_agent')",
            name="ck_regional_partners_stage",
        ),
        sa.CheckConstraint(
            "stage NOT IN ('city_observer', 'city_service') OR exclusive_territory = FALSE",
            name="ck_regional_partners_first_two_stages_no_exclusive",
        ),
        sa.CheckConstraint(
            "stage <> 'city_observer' OR (stage_changed_at IS NULL AND stage_evidence_uri IS NULL)",
            name="ck_regional_partners_observer_shape",
        ),
        sa.CheckConstraint(
            "stage <> 'city_service' OR stage_changed_at IS NOT NULL",
            name="ck_regional_partners_service_promoted",
        ),
        sa.CheckConstraint(
            "stage <> 'formal_partner' OR (stage_changed_at IS NOT NULL "
            "AND stage_evidence_uri IS NOT NULL AND stage_evidence_hash IS NOT NULL)",
            name="ck_regional_partners_formal_evidence",
        ),
    )
    op.create_index(
        "ix_regional_partners_stage", "regional_partners", ["stage"], unique=False
    )
    op.create_unique_constraint(
        "uq_regional_partners_partner_code", "regional_partners", ["partner_code"]
    )

    op.create_table(
        "regional_sale_gate",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=10), server_default="closed", nullable=False),
        sa.Column("filing_uri", sa.String(length=500), nullable=True),
        sa.Column("filing_hash", sa.String(length=64), nullable=True),
        sa.Column("filing_signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disclosure_uri", sa.String(length=500), nullable=True),
        sa.Column("disclosure_hash", sa.String(length=64), nullable=True),
        sa.Column("disclosure_signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cooling_off_uri", sa.String(length=500), nullable=True),
        sa.Column("cooling_off_hash", sa.String(length=64), nullable=True),
        sa.Column("cooling_off_signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("qualification_uri", sa.String(length=500), nullable=True),
        sa.Column("qualification_hash", sa.String(length=64), nullable=True),
        sa.Column("qualification_signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opened_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["opened_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "status IN ('closed', 'opened')",
            name="ck_regional_sale_gate_status",
        ),
        sa.CheckConstraint(
            "(filing_uri IS NULL) = (filing_hash IS NULL) AND "
            "(filing_uri IS NULL OR filing_signed_at IS NOT NULL) AND "
            "(disclosure_uri IS NULL) = (disclosure_hash IS NULL) AND "
            "(disclosure_uri IS NULL OR disclosure_signed_at IS NOT NULL) AND "
            "(cooling_off_uri IS NULL) = (cooling_off_hash IS NULL) AND "
            "(cooling_off_uri IS NULL OR cooling_off_signed_at IS NOT NULL) AND "
            "(qualification_uri IS NULL) = (qualification_hash IS NULL) AND "
            "(qualification_uri IS NULL OR qualification_signed_at IS NOT NULL)",
            name="ck_regional_sale_gate_condition_atomic",
        ),
        sa.CheckConstraint(
            "status <> 'opened' OR ("
            "filing_uri IS NOT NULL AND filing_hash IS NOT NULL AND filing_signed_at IS NOT NULL AND "
            "disclosure_uri IS NOT NULL AND disclosure_hash IS NOT NULL AND disclosure_signed_at IS NOT NULL AND "
            "cooling_off_uri IS NOT NULL AND cooling_off_hash IS NOT NULL AND cooling_off_signed_at IS NOT NULL AND "
            "qualification_uri IS NOT NULL AND qualification_hash IS NOT NULL AND qualification_signed_at IS NOT NULL AND "
            "opened_by_user_id IS NOT NULL AND opened_at IS NOT NULL)",
            name="ck_regional_sale_gate_opened_complete",
        ),
    )
    # 售卖开关单行种子：**默认 closed**（售卖能力默认关闭，任务书 §9）
    op.bulk_insert(
        sa.table(
            "regional_sale_gate",
            sa.column("id"),
            sa.column("status"),
        ),
        [
            {"id": "regional-sale-gate", "status": "closed"},
        ],
    )

    op.create_table(
        "regional_service_settlements",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("partner_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("ledger_entry_id", sa.String(length=36), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["partner_id"], ["regional_partners.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["ledger_entry_id"], ["commercial_revenue_ledger.id"], ondelete="RESTRICT"
        ),
    )
    op.create_index(
        "ix_regional_service_settlements_partner",
        "regional_service_settlements",
        ["partner_id"],
        unique=False,
    )
    op.create_unique_constraint(
        "uq_regional_service_settlements_ledger",
        "regional_service_settlements",
        ["ledger_entry_id"],
    )


def downgrade() -> None:
    # child-first 可逆
    op.drop_constraint(
        "uq_regional_service_settlements_ledger", "regional_service_settlements", type_="unique"
    )
    op.drop_index(
        "ix_regional_service_settlements_partner", table_name="regional_service_settlements"
    )
    op.drop_table("regional_service_settlements")
    op.drop_table("regional_sale_gate")
    op.drop_constraint(
        "uq_regional_partners_partner_code", "regional_partners", type_="unique"
    )
    op.drop_index("ix_regional_partners_stage", table_name="regional_partners")
    op.drop_table("regional_partners")
    op.drop_table("regional_partner_tiers")
