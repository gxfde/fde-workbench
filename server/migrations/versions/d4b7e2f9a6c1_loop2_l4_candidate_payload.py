"""学习闭环 2.0 L4（迁移①）：三载体候选载荷列＋workbench 适配档扩值。

- ``improvement_proposals`` 加 ``candidate_payload_json``（JSON NOT NULL，
  server_default '{}'）——AI 蒸馏返件经人工采纳后随提案入档的三载体载荷
  （lesson_entry / skill_version_draft / prompt_overlay_fragment）。与
  ``override_json`` 分工：override＝run 参数；candidate_payload＝三载体载荷
  （L5 发布通道的执行输入）。仍只是提案入档，热生效须经 release_channel。
- ``simulation_runs.adapter_mode`` 列宽 String(8)→String(16)＋CHECK 闭集扩
  ``'workbench'``——**设计稿 v1.1 勘误**：§2.1 只记了 ADAPTER_MODES/
  build_adapter 两处注册，漏记列宽（"workbench" 9 字符＞8）与表上 CHECK
  闭集两处落点；不随迁则 workbench 运行行在 DB 层必被拒。

幂等：加列一次＋alter 一次＋drop/create CHECK 各一次。downgrade 对称可逆；
若存量 ``workbench`` 行非零，旧 CHECK 重建会被 PG 如实拒绝（fail-closed，
不带错跑——b5d9e2f4a7c1 同款）。

Backup hint: 加列（server_default '{}' 零回填）＋列宽变更（PG 变宽＝元数据
级）＋约束级变更（drop+create 同名约束）；零数据改写。
"""
from alembic import op
import sqlalchemy as sa

revision = "d4b7e2f9a6c1"
down_revision = "d4b8e1f6a9c3"
branch_labels = None
depends_on = None

_ADAPTER_CHECK = "ck_simulation_runs_adapter_mode"
_NEW_CHECK = "adapter_mode IN ('real', 'mock', 'workbench')"
_OLD_CHECK = "adapter_mode IN ('real', 'mock')"


def upgrade() -> None:
    op.add_column(
        "improvement_proposals",
        sa.Column(
            "candidate_payload_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
    )
    op.alter_column(
        "simulation_runs",
        "adapter_mode",
        type_=sa.String(length=16),
        existing_type=sa.String(length=8),
        existing_nullable=False,
    )
    op.drop_constraint(_ADAPTER_CHECK, "simulation_runs", type_="check")
    op.create_check_constraint(_ADAPTER_CHECK, "simulation_runs", _NEW_CHECK)


def downgrade() -> None:
    # workbench 行非零时旧 CHECK 重建失败（PG 建约束即校验存量）＝如实拒绝。
    op.drop_constraint(_ADAPTER_CHECK, "simulation_runs", type_="check")
    op.create_check_constraint(_ADAPTER_CHECK, "simulation_runs", _OLD_CHECK)
    op.alter_column(
        "simulation_runs",
        "adapter_mode",
        type_=sa.String(length=8),
        existing_type=sa.String(length=16),
        existing_nullable=False,
    )
    op.drop_column("improvement_proposals", "candidate_payload_json")
