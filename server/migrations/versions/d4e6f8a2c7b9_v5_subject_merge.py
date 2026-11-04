"""subject 合并原语（V3 T-O4b，域 2；遗留候选收口）

project_research_subjects 加可空列 merged_into_subject_id：被合并方归档后
指向存续方（复合外键 (project_id, merged_into_subject_id)→(project_id, id)，
RESTRICT）。两条 CHECK：不许自指；指向存在即必须已归档。合并语义（表单/
答案/链接/子对象/个人备忘录/机会画像搬迁与跟踪码不回收）全部由服务层
merge_subject 把守，DB 层只钉「指向 = 归档」这条不变式。

Backup hint: 纯增量（可空列+约束+索引），零数据改写。downgrade 丢弃合并
指向（列删除即失溯源，属回退的应有语义）。
"""
import sqlalchemy as sa
from alembic import op

revision = "d4e6f8a2c7b9"
down_revision = "b5d9e3f7a1c6"
branch_labels = None
depends_on = None

_TABLE = "project_research_subjects"


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column("merged_into_subject_id", sa.String(length=36), nullable=True))
    op.create_foreign_key(
        "fk_project_research_subjects_merged_into",
        _TABLE,
        _TABLE,
        ["project_id", "merged_into_subject_id"],
        ["project_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_project_research_subjects_merge_not_self",
        _TABLE,
        "merged_into_subject_id IS NULL OR id <> merged_into_subject_id",
    )
    op.create_check_constraint(
        "ck_project_research_subjects_merge_archived",
        _TABLE,
        "merged_into_subject_id IS NULL OR status = 'archived'",
    )
    op.create_index(
        "ix_project_research_subjects_merged_into",
        _TABLE,
        ["merged_into_subject_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_project_research_subjects_merged_into", table_name=_TABLE)
    op.drop_constraint("ck_project_research_subjects_merge_archived", _TABLE, type_="check")
    op.drop_constraint("ck_project_research_subjects_merge_not_self", _TABLE, type_="check")
    op.drop_constraint("fk_project_research_subjects_merged_into", _TABLE, type_="foreignkey")
    op.drop_column(_TABLE, "merged_into_subject_id")
