"""变更集 ontology_change_sets（V3 T-O3，域 2；设计 ontology-registry-v1 §2.4）

批量变更事务单元 + diff 评审 + base 指纹并发防护——AI 候选唯一入口：候选载荷
进 proposed_json（captured_from 标来源），人工 submit 算 base_snapshot_sha256
（受影响行快照指纹），confirm 复核指纹后单事务逐项物化（全成全败），逐项结果
落 ontology_change_set_confirmed 事件；rejected 只改状态留 reason。

Backup hint: additive only（一张新表，不动任何既有表）；downgrade 先删索引
再 drop 表。
"""
import sqlalchemy as sa
from alembic import op

revision = "c9e3a7d1b5f8"
down_revision = "b8d3f1a5c7e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ontology_change_sets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        # 变更载荷：[{action, ...action 字段}]（服务层做形状校验与逐项物化）
        sa.Column(
            "proposed_json",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
        # 人读摘要（propose 时按载荷自动生成，不信任候选自报）
        sa.Column("diff_summary", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        # submit 时对受影响行快照取的指纹；confirm 复核（409 base_conflict）
        sa.Column("base_snapshot_sha256", sa.String(length=64), nullable=True),
        # 候选来源标记（如 agent_run:<id>）——仅服务层原语可写
        sa.Column("captured_from", sa.String(length=120), nullable=True),
        sa.Column("submitted_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_reason", sa.Text(), nullable=True),
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
            ["submitted_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'in_review', 'confirmed', 'rejected', 'superseded')",
            name="ck_ontology_change_sets_status",
        ),
    )
    op.create_index(
        "ix_ontology_change_sets_project_status",
        "ontology_change_sets",
        ["project_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ontology_change_sets_project_status", table_name="ontology_change_sets"
    )
    op.drop_table("ontology_change_sets")
