"""项目本体绑定与升级留痕（V3.3 WP4 段 1；additive；hex 链重接主线）。

规格 = Fde-Ontology docs/v3.3/m1/ontology-data-model.md §3；D7 决策单：
org_id 预留可空列，orgs 轨道合流后回填 NOT NULL（段 2）。评审 W-A（m2/02 报告）：
单活跃绑定 uq 带 active_marker（retired 行 NULL 退出唯一键，MySQL 无部分
索引的标准等价）——全量 uq 会卡死 retire+successor 升级流。时间戳 DDL
对齐主线兄弟迁移惯例。原 0043 编号形态重接主线 hex 链
（down_revision=c8e2a6f0b9d4，主线已废弃 0002-0042 旧链）——内容不变，
仅链位与 id 形态对齐主线纪律
（tests/test_migrations.py::_parse_migration_graph 只认 [a-f0-9]+）。
"""
import sqlalchemy as sa
from alembic import op

revision = "9d4f2b7e8c1a"
down_revision = "c8e2a6f0b9d4"
branch_labels = None
depends_on = None


def _timestamps():
    # 主线 PG 惯例（orgs 基线 a5e9c3f1b7d4 同款）：server_default now()；
    # updated_at 的更新时间戳由 ORM 层 TimestampMixin.onupdate=func.now() 负责
    # （PG 无 ON UPDATE CURRENT_TIMESTAMP）。原 0043 编号形态的 MySQL 方言 DDL
    # 已随主线全 PG 化退役。
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade():
    op.create_table(
        "project_ontology_bindings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=True),  # D7 段 1：预留
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("ontology_id", sa.String(36), nullable=False),
        sa.Column("pinned_version_id", sa.String(36), nullable=False),
        sa.Column("pinned_version", sa.String(32), nullable=False, server_default=""),
        sa.Column("binding_role", sa.String(40), nullable=False, server_default="primary"),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("active_marker", sa.String(16), nullable=True),  # W-A：active 行占用，其余 NULL
        sa.Column("bound_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("approved_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('active', 'upgrade_pending', 'retired')",
            name="ck_project_ontology_bindings_status",
        ),
        sa.UniqueConstraint(
            "project_id",
            "ontology_id",
            "active_marker",
            name="uq_project_ontology_bindings_project_ontology_active",
        ),
        sa.Index("ix_project_ontology_bindings_project", "project_id"),
        sa.Index("ix_project_ontology_bindings_org", "org_id"),
    )
    op.create_table(
        "ontology_binding_upgrades",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("binding_id", sa.String(36), sa.ForeignKey("project_ontology_bindings.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("from_version_id", sa.String(36), nullable=False),
        sa.Column("to_version_id", sa.String(36), nullable=False),
        sa.Column("to_version", sa.String(32), nullable=False, server_default=""),
        sa.Column("diff_summary", sa.Text(), nullable=False),
        sa.Column("source_change_set_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="proposed"),
        sa.Column("proposed_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("approved_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("acted_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('proposed', 'approved', 'rejected')", name="ck_ontology_binding_upgrades_status"
        ),
        sa.Index("ix_ontology_binding_upgrades_binding", "binding_id"),
    )


def downgrade():
    op.drop_table("ontology_binding_upgrades")
    op.drop_table("project_ontology_bindings")
