"""V3.3 M5-WP2 合流回植：回执观测值列（双指纹 / gate_ready / disposition_closed）。

链位：接 c7e1b3d9f4a2（M5-WP2 唯一 DDL 收口）之后，append-only 单链。

来源 = 并行评审分支（archive/v33-b-chain @ a59f8f36）的治理快照物理列设计，
经 party 裁决单步④「增量回植」收编：把高频审计查询字段从回执
``ontology_checks_json`` 提升为物理列——查询语义与并行版兼容
（gate_ready IS TRUE / disposition_closed IS TRUE），双指纹诚实可空
（disabled/skipped 档无指纹）。数据源 = 拍板时 governance-summary 透传
（D32 双层指纹），固化语义与既有回执一致（求值瞬间快照）。
回植列不进两级哈希口径（观测值列；结论完整性由既有内容列守卫）。

Backup hint: additive only; downgrade drops the four columns.
"""
import sqlalchemy as sa
from alembic import op

revision = "e9c4b7a1d5f8"
down_revision = "c7e1b3d9f4a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "gate_evaluation_receipts",
        sa.Column("domain_schema_sha256", sa.String(64), nullable=True),
    )
    op.add_column(
        "gate_evaluation_receipts",
        sa.Column("site_binding_sha256", sa.String(64), nullable=True),
    )
    op.add_column(
        "gate_evaluation_receipts",
        sa.Column(
            "gate_ready",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "gate_evaluation_receipts",
        sa.Column("disposition_closed", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    # 合流回植②：WP3 爆炸半径聚合的证据挂钉查询键（诚实可空）
    op.add_column(
        "gate_evaluation_receipts",
        sa.Column("ontology_id", sa.String(36), nullable=True),
    )
    op.add_column(
        "gate_evaluation_receipts",
        sa.Column("pinned_version_id", sa.String(36), nullable=True),
    )
    # 合流回植③：gate_id 放宽为可空（WP3 遥测/爆炸半径聚合只按 project+gate_key
    # 查询，不依赖具体 Gate 行；B 版本无 gate_id 列，A 版超集兼容）
    op.alter_column(
        "gate_evaluation_receipts",
        "gate_id",
        existing_type=sa.String(36),
        nullable=True,
    )
    # 合流回植③：B 版回执创建人审计列（与 decided_by_user_id 互补——
    # created_by = 建行人，decided_by = 拍板人）
    op.add_column(
        "gate_evaluation_receipts",
        sa.Column(
            "created_by_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    # 合流回植③（WP3 依赖）：求值瞬间熔断态（closed|open|half_open）
    op.add_column(
        "gate_evaluation_receipts",
        sa.Column("breaker_state", sa.String(16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("gate_evaluation_receipts", "breaker_state")
    op.drop_column("gate_evaluation_receipts", "created_by_user_id")
    op.alter_column(
        "gate_evaluation_receipts",
        "gate_id",
        existing_type=sa.String(36),
        nullable=False,
    )
    op.drop_column("gate_evaluation_receipts", "pinned_version_id")
    op.drop_column("gate_evaluation_receipts", "ontology_id")
    op.drop_column("gate_evaluation_receipts", "disposition_closed")
    op.drop_column("gate_evaluation_receipts", "gate_ready")
    op.drop_column("gate_evaluation_receipts", "site_binding_sha256")
    op.drop_column("gate_evaluation_receipts", "domain_schema_sha256")
