"""V3.3 M4-WP3 D27：workflow_runs 本体版本五元组不可变快照列（任务书 §9.3）。

链位：接 b7d3f9a1c5e2（本体批注回执面）之后，append-only 单链。

additive-only：``workflow_runs.ontology_snapshot_json`` 新增可空 JSON 列（无默认，
零存量行改写）。五元组语义（§9.3）：``ontology_id`` / ``ontology_version`` /
``tool_logic_action_version`` / ``datasource_mapping_version`` / ``workflow_version``
——start_run 发起时从项目活跃 ``ProjectOntologyBinding`` 冻结快照；项目后续升级
本体绑定绝不影响既有 run 记录（不可变性由 ORM before_update 守卫强制，非仅纪律）。
无活跃绑定的 run 落 NULL（诚实缺省——未使用本体面，不伪造记录）。

Backup hint: additive only; downgrade drops the single column.
"""
import sqlalchemy as sa
from alembic import op

revision = "e1a9d4c7b2f8"
down_revision = "b7d3f9a1c5e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workflow_runs",
        sa.Column("ontology_snapshot_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workflow_runs", "ontology_snapshot_json")
