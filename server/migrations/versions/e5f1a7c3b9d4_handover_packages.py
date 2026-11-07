"""T-B1 封包半：结项交付包 handover_packages 两表（goal-tb tb4，2026-11-07）

D11 设计草案（台账 §二）+ §十三.4 改名裁决（delivery_package→handover_packages，
与派单 delivery_packages 不混用）；§拍板闸 6⑪（2026-11-07 蔡工委托按建议拍板）。
状态机 draft→sealed→delivered（unseal 仅 sealed→draft；delivered 终态不可逆）；
items=指针+sha256 快照（B#6 真相原则：清单是投影，文件本体永不进库）；
v1 item_type 只开 'artifact'（document/file 留扩展）。

Backup hint: additive only; downgrade drops the two tables child-first.
"""
import sqlalchemy as sa
from alembic import op


revision = "e5f1a7c3b9d4"
down_revision = "b8e4d6f2a9c3"
branch_labels = None
depends_on = None


def _timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "handover_packages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="draft", nullable=False),
        sa.Column("sealed_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=True),
        sa.Column("unsealed_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("unsealed_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("unsealed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sealed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["unsealed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["delivered_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "status IN ('draft', 'sealed', 'delivered')",
            name="ck_handover_packages_status",
        ),
        sa.CheckConstraint(
            "(status = 'draft') = (sealed_at IS NULL)",
            name="ck_handover_packages_state",
        ),
        sa.CheckConstraint(
            "(status = 'draft') OR (sealed_by_user_id IS NOT NULL AND manifest_sha256 IS NOT NULL)",
            name="ck_handover_packages_sealed_complete",
        ),
        sa.CheckConstraint(
            "(status <> 'delivered') OR (delivered_by_user_id IS NOT NULL AND delivered_at IS NOT NULL)",
            name="ck_handover_packages_delivered_complete",
        ),
        sa.CheckConstraint(
            "manifest_sha256 IS NULL OR char_length(manifest_sha256) = 64",
            name="ck_handover_packages_manifest_len",
        ),
    )
    op.create_index(
        "ix_handover_packages_project_status", "handover_packages", ["project_id", "status"]
    )
    op.create_table(
        "handover_package_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("package_id", sa.String(length=36), nullable=False),
        sa.Column("item_type", sa.String(length=16), server_default="artifact", nullable=False),
        # B#6 纪律：纯指针无 FK（产物本体永不进库）
        sa.Column("artifact_id", sa.String(length=36), nullable=True),
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("storage_ref", sa.String(length=255), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["package_id"], ["handover_packages.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "item_type IN ('artifact')",
            name="ck_handover_package_items_type",
        ),
        sa.CheckConstraint(
            "(item_type <> 'artifact') OR artifact_id IS NOT NULL",
            name="ck_handover_package_items_pointer",
        ),
        sa.CheckConstraint("char_length(sha256) = 64", name="ck_handover_package_items_sha_len"),
        sa.UniqueConstraint("package_id", "artifact_id", name="uq_handover_package_items_pkg_artifact"),
    )
    op.create_index("ix_handover_package_items_package", "handover_package_items", ["package_id"])


def downgrade() -> None:
    op.drop_index("ix_handover_package_items_package", table_name="handover_package_items")
    op.drop_table("handover_package_items")
    op.drop_index("ix_handover_packages_project_status", table_name="handover_packages")
    op.drop_table("handover_packages")
