"""关系/对象类型注册表 ontology_relation_types（V3 T-O2，域 2；设计 ontology-registry-v1 §2.3）

把「关系类型白名单硬编码 2 种」「对象类型 CheckConstraint 硬编码」（审计附录
D ②③）的扩展面搬进可注册表：一行 = 一个类型（kind=subject_type 对象类型登记 /
kind=link_type 关系类型 + 端点约束）。project_id 为 NULL = 全局类型（仅 admin
可建，对所有项目生效），非 NULL = 项目内类型并遮蔽同名全局类型。

内置五类对象类型与两类关系类型的端点约束是**存量语义（冻结）**，不搬进本表：
服务层解析时内置优先，注册表不得覆盖内置码。

Backup hint: additive only（一张新表，不动任何既有表）；downgrade 先删两个
索引再 drop 表。
"""
import sqlalchemy as sa
from alembic import op

revision = "b8d3f1a5c7e2"
down_revision = "a3e7c1f9b5d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ontology_relation_types",
        sa.Column("id", sa.String(length=36), nullable=False),
        # NULL = 全局类型（仅 admin 可建）
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("code", sa.String(length=60), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        # 端点约束：来源/目标对象类型码列表（只对 kind=link_type 有意义）
        sa.Column(
            "allowed_source_types",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
        sa.Column(
            "allowed_target_types",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False),
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
            ["created_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        # 项目内唯一：同项目同 kind 同 code 只有一行
        sa.UniqueConstraint(
            "project_id", "kind", "code", name="uq_ontology_relation_types_project_code"
        ),
        sa.CheckConstraint(
            "kind IN ('subject_type', 'link_type')",
            name="ck_ontology_relation_types_kind",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'retired')",
            name="ck_ontology_relation_types_status",
        ),
        sa.CheckConstraint(
            "json_typeof(allowed_source_types) = 'array' "
            "AND json_typeof(allowed_target_types) = 'array'",
            name="ck_ontology_relation_types_endpoints_json",
        ),
        # 关系类型必须声明端点约束（否则边的方向无从校验）
        sa.CheckConstraint(
            "kind <> 'link_type' OR ("
            "json_array_length(allowed_source_types) > 0 "
            "AND json_array_length(allowed_target_types) > 0)",
            name="ck_ontology_relation_types_link_endpoints",
        ),
    )
    # 全局唯一：project_id IS NULL 的行按 (kind, code) 唯一
    op.create_index(
        "uq_ontology_relation_types_global_code",
        "ontology_relation_types",
        ["kind", "code"],
        unique=True,
        postgresql_where=sa.text("project_id IS NULL"),
    )
    op.create_index(
        "ix_ontology_relation_types_project_kind",
        "ontology_relation_types",
        ["project_id", "kind"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ontology_relation_types_project_kind", table_name="ontology_relation_types"
    )
    op.drop_index(
        "uq_ontology_relation_types_global_code", table_name="ontology_relation_types"
    )
    op.drop_table("ontology_relation_types")
