"""术语表 ontology_terms + ontology_term_aliases（V3 T-O1，域 2；设计 ontology-registry-v1 §2.2）

项目内术语/别名治理的唯一性底座：同项目一个名字至多指向一个概念——
UNIQUE(project, term) 治规范名、UNIQUE(project, alias) 治别名（附录 D ⑨
「导入同名重复」的根治面）。状态机沿用 guidance 语义（draft→confirmed→
superseded/merged），merged 行必须指向保留行；关系类型注册（T-O2）与变更集
（T-O3）建在本表之上。

Backup hint: additive only（两张新表，不动任何既有表；aliases 先于 terms
删除）；downgrade 逆序 drop，含索引与约束。
"""
import sqlalchemy as sa
from alembic import op

revision = "a3e7c1f9b5d2"
down_revision = "c1e5f9a3d7b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ontology_terms",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        # 规范业务名（同项目唯一）+ 种类 + 定义（确认后不可原地改）
        sa.Column("term", sa.String(length=120), nullable=False),
        sa.Column("term_type", sa.String(length=32), nullable=False),
        sa.Column("definition", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        # 合并指向：merged 行 → 保留行（自引用外键，PG 允许内联声明）
        sa.Column("canonical_term_id", sa.String(length=36), nullable=True),
        sa.Column("confirmed_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "version", sa.Integer(), server_default=sa.text("1"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["canonical_term_id"], ["ontology_terms.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["confirmed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("project_id", "term", name="uq_ontology_terms_project_term"),
        sa.CheckConstraint(
            "term_type IN ('entity', 'attribute', 'metric', 'alias_target', 'generic')",
            name="ck_ontology_terms_term_type",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'confirmed', 'superseded', 'merged')",
            name="ck_ontology_terms_status",
        ),
        sa.CheckConstraint(
            "status <> 'merged' OR canonical_term_id IS NOT NULL",
            name="ck_ontology_terms_merged_canonical",
        ),
    )
    op.create_index(
        "ix_ontology_terms_project_status", "ontology_terms", ["project_id", "status"]
    )
    op.create_table(
        "ontology_term_aliases",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("term_id", sa.String(length=36), nullable=False),
        # 冗余 project_id：唯一约束按项目隔离，导入去重按项目点查
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("alias", sa.String(length=120), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["term_id"], ["ontology_terms.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "project_id", "alias", name="uq_ontology_term_aliases_project_alias"
        ),
    )
    op.create_index(
        "ix_ontology_term_aliases_term_id", "ontology_term_aliases", ["term_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_ontology_term_aliases_term_id", table_name="ontology_term_aliases")
    op.drop_table("ontology_term_aliases")
    op.drop_index("ix_ontology_terms_project_status", table_name="ontology_terms")
    op.drop_table("ontology_terms")
