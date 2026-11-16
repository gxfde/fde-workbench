"""handover 包清单 item_type 三态全开（artifact/document/file）＋两指针列。

D11 草案全集的 v1 子集（只开 artifact）扩展为三态：document 指针接
project_document_versions（须 confirmed 版本）、file 指针接
project_file_versions（须 available 版本）。指针仍无 FK（B#6 纪律），
恰一指针互斥由 ck_handover_package_items_pointer 重建钉死。存量行全为
artifact（v1 唯一合法类型），行为逐位不变；downgrade 先清非 artifact 行。
"""
import sqlalchemy as sa
from alembic import op

revision = "e5c8b2d4f7a9"
down_revision = "d8b4f6a2c9e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "handover_package_items",
        sa.Column("document_version_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "handover_package_items",
        sa.Column("file_version_id", sa.String(length=36), nullable=True),
    )
    op.drop_constraint("ck_handover_package_items_type", "handover_package_items", type_="check")
    op.drop_constraint("ck_handover_package_items_pointer", "handover_package_items", type_="check")
    op.create_check_constraint(
        "ck_handover_package_items_type",
        "handover_package_items",
        "item_type IN ('artifact', 'document', 'file')",
    )
    op.create_check_constraint(
        "ck_handover_package_items_pointer",
        "handover_package_items",
        "(item_type = 'artifact' AND artifact_id IS NOT NULL AND document_version_id IS NULL AND file_version_id IS NULL)"
        " OR (item_type = 'document' AND artifact_id IS NULL AND document_version_id IS NOT NULL AND file_version_id IS NULL)"
        " OR (item_type = 'file' AND artifact_id IS NULL AND document_version_id IS NULL AND file_version_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.execute("DELETE FROM handover_package_items WHERE item_type <> 'artifact'")
    op.drop_constraint("ck_handover_package_items_type", "handover_package_items", type_="check")
    op.drop_constraint("ck_handover_package_items_pointer", "handover_package_items", type_="check")
    op.create_check_constraint(
        "ck_handover_package_items_type",
        "handover_package_items",
        "item_type IN ('artifact')",
    )
    op.create_check_constraint(
        "ck_handover_package_items_pointer",
        "handover_package_items",
        "(item_type <> 'artifact') OR artifact_id IS NOT NULL",
    )
    op.drop_column("handover_package_items", "file_version_id")
    op.drop_column("handover_package_items", "document_version_id")
