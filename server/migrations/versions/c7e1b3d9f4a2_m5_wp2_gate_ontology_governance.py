"""V3.3 M5-WP2：S-13 证据引用列 + Gate 评估回执 + 验收契约 + 本体依赖锚点 + 晋升锚点。

链位：接 e1a9d4c7b2f8（M4-WP3 D27 五元组快照）之后，append-only 单链。
WP2 全部 DDL 变更收口本文件（工作令 WP2 防冲突铁律：迁移唯一收口）。

additive-only 五组（跨库一律无外键，归属强验由服务层执行）：
1. ``project_evidence`` +5 可空引用列（S-13：ontology_id / pinned_version_id /
   object_ref_id / action_request_id / logic_eval_digest）+ pinned_version 索引
   ——本体引用只作语义增强锚点，严禁替代原始文件指纹，既有唯一键
   uq_project_evidence_fingerprint(project_id, source_uri, content_sha256)
   原样保留（防互踩：引用列不进唯一键，幂等语义零变化）。
2. 新表 ``gate_evaluation_receipts``（D29）：Gate 求值瞬间固化的不可变评估
   回执——输入快照 + 快照哈希 + 当时本体降级态 + D31 处置闭环判定 + 拍板
   结论绑定。历史重放只验回执，免疫实时网络抖动；不可变性由 ORM
   before_update/before_delete 守卫强制（非仅纪律），Agent 与 ontology-service
   均无写通道。
3. 新表 ``acceptance_contracts``：结构化验收契约（输入清单 / 量化规则引用 /
   acceptor 按**角色**判定 / 争议响应 SLA 小时数）。独立实体可换版留档；
   回执只固化签约快照。
4. ``gates`` + ontology_dependency（S-16 内层等级 per-gate 持久锚点，
   NULL=未建档走全局缺省）+ ontology_dependency_baseline_by_user_id
   （S-12 异人判定的基线建档人）。
5. ``ontology_terms`` + promoted_readonly（改进单 4 单向晋升锚点，晋升后
   只读投影）+ promoted_at（晋升时刻；晋升写路径归 WP3 独立模块）。

Backup hint: additive only; downgrade drops the two tables and the four column groups.
"""
import sqlalchemy as sa
from alembic import op

revision = "c7e1b3d9f4a2"
down_revision = "e1a9d4c7b2f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- 1. project_evidence S-13 引用列（可空，零存量行改写）----
    op.add_column(
        "project_evidence",
        sa.Column("ontology_id", sa.String(36), nullable=True),
    )
    op.add_column(
        "project_evidence",
        sa.Column("pinned_version_id", sa.String(36), nullable=True),
    )
    op.add_column(
        "project_evidence",
        sa.Column("object_ref_id", sa.String(36), nullable=True),
    )
    op.add_column(
        "project_evidence",
        sa.Column("action_request_id", sa.String(36), nullable=True),
    )
    op.add_column(
        "project_evidence",
        sa.Column("logic_eval_digest", sa.String(64), nullable=True),
    )
    op.create_check_constraint(
        "ck_project_evidence_logic_digest_len",
        "project_evidence",
        "logic_eval_digest IS NULL OR char_length(logic_eval_digest) = 64",
    )
    op.create_index(
        "ix_project_evidence_pinned_version",
        "project_evidence",
        ["pinned_version_id"],
    )

    # ---- 2. gate_evaluation_receipts（D29 不可变评估回执）----
    op.create_table(
        "gate_evaluation_receipts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "gate_id",
            sa.String(36),
            sa.ForeignKey("gates.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("gate_key", sa.String(10), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("result", sa.String(20), nullable=False),
        sa.Column("decision", sa.String(10), nullable=True),
        sa.Column("input_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("input_snapshot_sha256", sa.String(64), nullable=False),
        sa.Column("ontology_checks_json", sa.JSON(), nullable=False),
        sa.Column("ontology_degradation", sa.String(16), nullable=False, server_default=sa.text("'disabled'")),
        sa.Column(
            "decided_by_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("receipt_sha256", sa.String(64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.CheckConstraint(
            "ontology_degradation IN ('online', 'degraded', 'skipped', 'disabled')",
            name="ck_gate_evaluation_receipts_degradation",
        ),
        sa.CheckConstraint(
            "char_length(input_snapshot_sha256) = 64 "
            "AND char_length(receipt_sha256) = 64",
            name="ck_gate_evaluation_receipts_sha256_len",
        ),
    )
    op.create_index(
        "ix_gate_evaluation_receipts_project_gate",
        "gate_evaluation_receipts",
        ["project_id", "gate_key"],
    )

    # ---- 3. acceptance_contracts（结构化验收契约）----
    op.create_table(
        "acceptance_contracts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("gate_key", sa.String(10), nullable=False),
        sa.Column("items_json", sa.JSON(), nullable=False),
        sa.Column("rule_refs_json", sa.JSON(), nullable=False),
        sa.Column("acceptor_role", sa.String(40), nullable=False),
        sa.Column("sla_hours", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "created_by_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.CheckConstraint("sla_hours > 0", name="ck_acceptance_contracts_sla_positive"),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'superseded')",
            name="ck_acceptance_contracts_status",
        ),
    )
    op.create_index(
        "ix_acceptance_contracts_project_gate_status",
        "acceptance_contracts",
        ["project_id", "gate_key", "status"],
    )

    # ---- 4. gates 本体依赖锚点（S-16 内层 + S-12 基线建档人）----
    op.add_column(
        "gates",
        sa.Column("ontology_dependency", sa.String(12), nullable=True),
    )
    op.add_column(
        "gates",
        sa.Column(
            "ontology_dependency_baseline_by_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_gates_ontology_dependency",
        "gates",
        "ontology_dependency IS NULL OR "
        "ontology_dependency IN ('required', 'optional', 'none')",
    )

    # ---- 5. ontology_terms 晋升锚点（改进单 4；晋升写路径归 WP3）----
    op.add_column(
        "ontology_terms",
        sa.Column(
            "promoted_readonly",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "ontology_terms",
        sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ontology_terms", "promoted_at")
    op.drop_column("ontology_terms", "promoted_readonly")
    op.drop_constraint("ck_gates_ontology_dependency", "gates", type_="check")
    op.drop_column("gates", "ontology_dependency_baseline_by_user_id")
    op.drop_column("gates", "ontology_dependency")
    op.drop_index("ix_acceptance_contracts_project_gate_status", table_name="acceptance_contracts")
    op.drop_table("acceptance_contracts")
    op.drop_index("ix_gate_evaluation_receipts_project_gate", table_name="gate_evaluation_receipts")
    op.drop_table("gate_evaluation_receipts")
    op.drop_index("ix_project_evidence_pinned_version", table_name="project_evidence")
    op.drop_constraint("ck_project_evidence_logic_digest_len", "project_evidence", type_="check")
    op.drop_column("project_evidence", "logic_eval_digest")
    op.drop_column("project_evidence", "action_request_id")
    op.drop_column("project_evidence", "object_ref_id")
    op.drop_column("project_evidence", "pinned_version_id")
    op.drop_column("project_evidence", "ontology_id")
