"""任务产物→门禁证据候选（V3 T-G1，域 4，WB-DEF-8）

gates 加可空 JSON 列 evidence_candidates：任务完成且自带门禁挂点与证据
指针+指纹时，服务层把该产物登记为候选（建议性，不动 claim_status 与
门禁状态）；人工经既有提交闸采纳后按指纹剪除。审计 WB-DEF-8「任务级
证据与门禁清单双口径脱钩」的候选闭环半边——不自动领用，领用永远是人。

Backup hint: 纯增量（可空 JSON 列），零数据改写。downgrade 丢弃候选
（建议性数据，删除即失提示，属回退的应有语义；已采纳的证据在清单项
与 project_evidence 一等行上，不受影响）。
"""
import sqlalchemy as sa
from alembic import op

revision = "c7e1a9f3b5d8"
down_revision = "d4e6f8a2c7b9"
branch_labels = None
depends_on = None

_TABLE = "gates"


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column("evidence_candidates", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column(_TABLE, "evidence_candidates")
