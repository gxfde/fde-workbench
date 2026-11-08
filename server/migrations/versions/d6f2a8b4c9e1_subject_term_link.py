"""V3.1 P0-2：ADR-002 稳定 ID 试点——project_research_subjects +term_id
（可空 FK → ontology_terms.id，RESTRICT，2026-11-08）。

任务书 §6：业务对象逐步通过稳定 term_id 关联（先从一个试点实体起步，
不做全库大迁移）。旧行不回填（读路径仍以名字域为权威，双轨兼容）；
术语落定（change-set confirm 物化 create_term 与 create_term 直落
confirmed）时对同名 subject 自动链接（服务层一次性 UPDATE，只链接
term_id IS NULL 的行）。术语行永不物理删除（merged/superseded 是状态），
RESTRICT 不构成生命周期阻塞。

Backup hint: additive only; downgrade drops index/column.
"""
import sqlalchemy as sa
from alembic import op


revision = "d6f2a8b4c9e1"
down_revision = "f6d3a9c1e7b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "project_research_subjects",
        sa.Column("term_id", sa.String(length=36), nullable=True),
    )
    op.create_foreign_key(
        "fk_project_research_subjects_term",
        "project_research_subjects",
        "ontology_terms",
        ["term_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_project_research_subjects_term", "project_research_subjects", ["term_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_project_research_subjects_term", table_name="project_research_subjects")
    op.drop_constraint("fk_project_research_subjects_term", "project_research_subjects", type_="foreignkey")
    op.drop_column("project_research_subjects", "term_id")
