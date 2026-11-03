"""对象类型值域开放（V3 T-O2b，域 2；设计 ontology-registry-v1 §2.3/§2.4）

三处 subject_type 物理边界从「内置五类枚举」CHECK 放宽为「码格式」CHECK
（小写字母开头、仅含小写字母/数字/下划线、最长 60，对齐注册表 code 列），
同时三列宽度 32→60：project_research_subjects / template_research_forms /
project_research_import_batches。允许域的收窄（内置 ∪ 注册表 active 行、
project 根类型保留、retired 禁新建）由服务层闸门把守，不在 DB 层。

Backup hint: 无数据改写——枚举值是格式的子集，存量行全部兼容；仅列宽放宽
（PG 元数据操作）与约束替换。downgrade 收窄回 32 时若存在长度 >32 的注册
类型在用会因超长失败（值域回退前提是没有这类存量，属预期保护）。
"""
import sqlalchemy as sa
from alembic import op

revision = "b5d9e3f7a1c6"
down_revision = "c9e3a7d1b5f8"
branch_labels = None
depends_on = None

# 与 research/models.py 的 SUBJECT_TYPE_CHECK_SQL 逐字一致（迁移自含，不 import
# 应用代码，避免应用侧漂移拖垮历史迁移）。
_SUBJECT_TYPE_CHECK_SQL = "subject_type ~ '^[a-z][a-z0-9_]{0,59}$'"
_ENUM_CHECKS = {
    "ck_template_research_forms_subject_type": (
        "template_research_forms",
        "subject_type IN ('project', 'department', 'role', 'process', 'opportunity')",
    ),
    "ck_project_research_subjects_subject_type": (
        "project_research_subjects",
        "subject_type IN ('project', 'department', 'role', 'process', 'opportunity')",
    ),
    "ck_project_research_import_batches_subject_type": (
        "project_research_import_batches",
        "subject_type IN ('department', 'role', 'process', 'opportunity')",
    ),
}


def upgrade() -> None:
    for table, _enum_sql in _ENUM_CHECKS.values():
        op.alter_column(
            table,
            "subject_type",
            existing_type=sa.String(length=32),
            type_=sa.String(length=60),
        )
    for constraint_name, (table, _enum_sql) in _ENUM_CHECKS.items():
        op.drop_constraint(constraint_name, table, type_="check")
        op.create_check_constraint(constraint_name, table, _SUBJECT_TYPE_CHECK_SQL)


def downgrade() -> None:
    for constraint_name, (table, enum_sql) in _ENUM_CHECKS.items():
        op.drop_constraint(constraint_name, table, type_="check")
        op.create_check_constraint(constraint_name, table, enum_sql)
    for table in _ENUM_CHECKS.values():
        op.alter_column(
            table[0],
            "subject_type",
            existing_type=sa.String(length=60),
            type_=sa.String(length=32),
        )
