"""本体批注回执面：evidence kind 扩 ``ontology_annotation`` + captured_from 放宽 +
升级留痕增批注指针（D16；决议 03 §6 附注 + m1/ontology-integration-contract.md §5）。

三处变更，全部非破坏性（零存量行改写、零删列删行）：

1. ``ck_project_evidence_kind`` 闭集由 7 种扩为 8 种（加 ``ontology_annotation``）
   ——drop+recreate 同名约束（照 T-16 先例 ``f2a7c4e9b6d3``）；既有行 kind 不动，
   未知 kind 仍被拒（闭集不放宽）。
2. ``project_evidence.captured_from`` 由 String(64) 放宽为 String(128)——冻结契约
   规定 ``captured_from=ontology_review:<package_id>``，而 package_id 是**内容寻址
   的 sha256**（64 hex），前缀 16 字符 ⇒ 合计 80 字符，原 64 上限装不下。只扩不
   截断：截断会破坏内容寻址语义（"重复导出可检测"依赖完整 sha256）。既有行全部
   ≤64 字符 ⇒ 扩容不改任何数据。
3. ``ontology_binding_upgrades`` 增 ``annotation_evidence_id`` 列（可空，
   FK→``project_evidence.id``，ondelete SET NULL）：版本升级的批注回执指针
   （§15「本体发布和版本升级必须记录审批人和证据」）。

Backup hint: 约束级变更 + 列扩容 + 新增可空列；无数据改写。
"""
import sqlalchemy as sa
from alembic import op

revision = "b7d3f9a1c5e2"
down_revision = "c4a8f2e6b1d9"
branch_labels = None
depends_on = None

_KINDS_NEW = (
    "kind IN ('gate', 'task', 'guidance', 'research', 'bridge', 'workflow', "
    "'solution', 'ontology_annotation')"
)
_KINDS_OLD = (
    "kind IN ('gate', 'task', 'guidance', 'research', 'bridge', 'workflow', 'solution')"
)
_CHECK_NAME = "ck_project_evidence_kind"
_FK_NAME = "fk_ontology_binding_upgrades_annotation_evidence_id"


def upgrade() -> None:
    op.drop_constraint(_CHECK_NAME, "project_evidence", type_="check")
    op.create_check_constraint(_CHECK_NAME, "project_evidence", _KINDS_NEW)
    op.alter_column(
        "project_evidence",
        "captured_from",
        existing_type=sa.String(length=64),
        type_=sa.String(length=128),
        existing_nullable=True,
    )
    op.add_column(
        "ontology_binding_upgrades",
        sa.Column("annotation_evidence_id", sa.String(length=36), nullable=True),
    )
    op.create_foreign_key(
        _FK_NAME,
        "ontology_binding_upgrades",
        "project_evidence",
        ["annotation_evidence_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(_FK_NAME, "ontology_binding_upgrades", type_="foreignkey")
    op.drop_column("ontology_binding_upgrades", "annotation_evidence_id")
    op.alter_column(
        "project_evidence",
        "captured_from",
        existing_type=sa.String(length=128),
        type_=sa.String(length=64),
        existing_nullable=True,
    )
    op.drop_constraint(_CHECK_NAME, "project_evidence", type_="check")
    op.create_check_constraint(_CHECK_NAME, "project_evidence", _KINDS_OLD)
