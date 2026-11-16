"""双平行迁移主线收单（merge 迁移，零 DDL）。

SME 交付尾巴轮 handover 三态（e5c8b2d4f7a9，挂 d8b4f6a2c9e7）与 AF1-WP4
（a1e5f9c3d7b2_tool_call_payload_and_eng_marks，同挂 d8b4f6a2c9e7）并行施工
各自入主线，形成双头；本迁移按 M6-WP0 D11 先例（c2a9e7d5b3f1）收单：
down_revision 用双头元组，upgrade/downgrade 零操作。
"""
from alembic import op  # noqa: F401  (merge 迁移保持 import 形状一致)

revision = "b7f2d9e4c6a8"
down_revision = ("e5c8b2d4f7a9", "a1e5f9c3d7b2")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
