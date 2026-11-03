"""Skill 治理态（V3 T-S1）：draft/in_review/published/deprecated + 版本契约/审核列

skill_definitions 的 status 从扩展共用值域（active/disabled）切到治理四态，
存量数据迁移：active→published（published_by 暂记 created_by、published_at 取
迁移时刻）、disabled→deprecated。版本行补发布治理材料列：input/output schema
（可选契约）、test_report_json（发布四闸之「测试报告或显式 waive」）、
reviewed_by_user_id（审核人留痕）。版本行本身不可变的既有语义不变。

Backup hint: 列全部可空、数据迁移可逆（published→active / deprecated|draft|
in_review→disabled）；downgrade 先换回旧值域再删列。
"""
import sqlalchemy as sa
from alembic import op

revision = "c1e5f9a3d7b2"
down_revision = "d5b8e2f4a7c9"
branch_labels = None
depends_on = None

_SKILL_STATUSES_OLD = "status IN ('active', 'disabled')"
_SKILL_STATUSES_NEW = "status IN ('draft', 'in_review', 'published', 'deprecated')"


def upgrade() -> None:
    # 先加列（数据迁移要写 published_by/at）→ 换值域约束 → 迁数据：
    # 旧约束容不下新值，新约束容不下旧值
    op.add_column(
        "skill_definitions",
        sa.Column("published_by_user_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "skill_definitions",
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_skill_definitions_published_by_user_id",
        "skill_definitions",
        "users",
        ["published_by_user_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint("ck_skill_definitions_status", "skill_definitions", type_="check")
    op.execute(
        "UPDATE skill_definitions SET status = 'published', published_by_user_id = created_by_user_id,"
        " published_at = now() WHERE status = 'active'"
    )
    op.execute("UPDATE skill_definitions SET status = 'deprecated' WHERE status = 'disabled'")
    op.create_check_constraint("ck_skill_definitions_status", "skill_definitions", _SKILL_STATUSES_NEW)
    op.add_column("skill_versions", sa.Column("input_schema_json", sa.JSON(), nullable=True))
    op.add_column("skill_versions", sa.Column("output_schema_json", sa.JSON(), nullable=True))
    op.add_column("skill_versions", sa.Column("test_report_json", sa.JSON(), nullable=True))
    op.add_column(
        "skill_versions",
        sa.Column("reviewed_by_user_id", sa.String(length=36), nullable=True),
    )
    op.create_foreign_key(
        "fk_skill_versions_reviewed_by_user_id",
        "skill_versions",
        "users",
        ["reviewed_by_user_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    # 数据先归位旧值域：published→active；draft/in_review/deprecated 一律 →disabled
    # （治理中未发布的版本在旧模型里本就不可用，disabled 是最接近的诚实映射）
    op.drop_constraint("ck_skill_definitions_status", "skill_definitions", type_="check")
    op.execute("UPDATE skill_definitions SET status = 'active' WHERE status = 'published'")
    op.execute(
        "UPDATE skill_definitions SET status = 'disabled'"
        " WHERE status IN ('deprecated', 'draft', 'in_review')"
    )
    op.create_check_constraint("ck_skill_definitions_status", "skill_definitions", _SKILL_STATUSES_OLD)
    op.drop_constraint(
        "fk_skill_versions_reviewed_by_user_id", "skill_versions", type_="foreignkey"
    )
    op.drop_column("skill_versions", "reviewed_by_user_id")
    op.drop_column("skill_versions", "test_report_json")
    op.drop_column("skill_versions", "output_schema_json")
    op.drop_column("skill_versions", "input_schema_json")
    op.drop_constraint(
        "fk_skill_definitions_published_by_user_id",
        "skill_definitions",
        type_="foreignkey",
    )
    op.drop_column("skill_definitions", "published_at")
    op.drop_column("skill_definitions", "published_by_user_id")
