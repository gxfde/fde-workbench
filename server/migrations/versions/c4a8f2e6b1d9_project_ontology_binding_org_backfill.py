"""项目本体绑定 org_id 回填并收紧为 NOT NULL（V3.3 WP4 段 2 步 3+4；append-only）。

背景（D7 段 1 预留 → 段 2 兑现）：
- 9d4f2b7e8c1a 建表时 org_id 为**可空预留列**（D7：orgs 轨道未合流，先占位）；
- orgs 多租户轨道合流后，租户归属的唯一诚实来源 = projects.org_id（ADR-M1
  项目域代号制；§15 红线「不允许仅凭客户端/配置传来的 tenant_id 就信任
  租户身份」——org 上下文只能取自服务端推导的项目归属）。

回填：project_ontology_bindings.org_id ← projects.org_id（UPDATE ... FROM
projects，WHERE 守卫 ⇒ 幂等可重放；先例 a5e9c3f1b7d4 的幂等回填口径）。
回填后仍有 NULL ⇒ **响亮失败**（RuntimeError，迁移整体回滚）：其项目自身
无 org 归属 ⇒ 静默留空等于把绑定置于无租户域，违反红线 2（fail-closed：
宁可迁移失败，也不留孤儿归属；对应应用层 409 project_org_missing）。

收紧：op.alter_column(nullable=False)；ORM 侧同步 nullable=False。
downgrade 对称逆向（列恢复可空；已回填的 org 值不撤销——append-only 演进，
数据只增不减）。

回执行要求：项目 org 归属在 orgs 轨道合流后始终非空（orgs 基线迁移已把存量
项目回填到平台内部 org），故本迁移在正常部署路径上不会触发响亮失败分支。
"""
import sqlalchemy as sa
from alembic import op

revision = "c4a8f2e6b1d9"
down_revision = "9d4f2b7e8c1a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 幂等回填：绑定行继承其项目的 org 归属（WHERE 守卫 ⇒ 重放安全）
    op.execute(
        sa.text(
            """
            UPDATE project_ontology_bindings AS b
               SET org_id = p.org_id
              FROM projects AS p
             WHERE p.id = b.project_id
               AND b.org_id IS NULL
               AND p.org_id IS NOT NULL
            """
        )
    )
    # 响亮失败：仍有 NULL ⇒ 其项目无 org 归属（孤儿）⇒ 不得静默留空
    remaining = op.get_bind().execute(
        sa.text(
            "SELECT count(*) FROM project_ontology_bindings WHERE org_id IS NULL"
        )
    ).scalar()
    if remaining:
        raise RuntimeError(
            "c4a8f2e6b1d9: project_ontology_bindings.org_id 回填不完整——"
            f"仍有 {remaining} 行绑定指向无 org 归属的项目（拒绝静默留空；"
            "先为项目补 org 归属再重放本迁移）"
        )
    op.alter_column(
        "project_ontology_bindings",
        "org_id",
        existing_type=sa.String(36),
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "project_ontology_bindings",
        "org_id",
        existing_type=sa.String(36),
        nullable=True,
    )
