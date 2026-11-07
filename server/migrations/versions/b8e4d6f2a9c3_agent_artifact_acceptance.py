"""T-B1 agent_artifacts 扩列（goal-tb tb2，2026-11-07）

artifacts 扩列半（封包半挂 D11 立项拍板，本迁移不含 handover_packages）：
① kind CHECK 置换扩 'test_results'（纯枚举扩展零列重建，T-J2 先例）；
② derived_summary JSON 可空列（可重建派生摘要——diff: files_changed/
   additions/deletions；test_results: passed/failed/errors/skipped+exit_code；
   原件本体永不进库，B#6「指针+指纹+可重建派生」）；
③ reviewed_by_user_id（FK users SET NULL）+ reviewed_at（人工接受留痕：
   度量表「智能体产物被人工接受率」此前恒 0 的根因=reviewed 无写路径）。

Backup hint: additive columns + CHECK swap; downgrade restores enum and drops columns.
"""
import sqlalchemy as sa
from alembic import op


revision = "b8e4d6f2a9c3"
down_revision = "d7b2f8a4c1e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_artifacts", sa.Column("derived_summary", sa.JSON(), nullable=True))
    op.add_column("agent_artifacts", sa.Column("reviewed_by_user_id", sa.String(length=36), nullable=True))
    op.add_column("agent_artifacts", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "fk_agent_artifacts_reviewed_by_user_id",
        "agent_artifacts",
        "users",
        ["reviewed_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.drop_constraint("ck_agent_artifacts_kind", "agent_artifacts", type_="check")
    op.create_check_constraint(
        "ck_agent_artifacts_kind",
        "agent_artifacts",
        "kind IN ('code', 'doc', 'diff', 'config', 'test_results')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_agent_artifacts_kind", "agent_artifacts", type_="check")
    op.create_check_constraint(
        "ck_agent_artifacts_kind",
        "agent_artifacts",
        "kind IN ('code', 'doc', 'diff', 'config')",
    )
    op.drop_constraint("fk_agent_artifacts_reviewed_by_user_id", "agent_artifacts", type_="foreignkey")
    op.drop_column("agent_artifacts", "reviewed_at")
    op.drop_column("agent_artifacts", "reviewed_by_user_id")
    op.drop_column("agent_artifacts", "derived_summary")
