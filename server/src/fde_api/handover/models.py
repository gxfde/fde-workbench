"""handover 模型：结项交付包两表（D11 草案 §二 + §十三.4 改名裁决）。

真相原则（A1）：清单是**投影**——items 只存指针 + sha256 快照（封包校验
锚），文件本体永不进库（B#6「引用方永不复制真相，只持指针」：artifact_id
无 FK 纯指针，metadata 扫描钉死）；已封存（sealed）清单冻结，manifest_
sha256 = 清单规范化 JSON 哈希，delivered 终态不可逆。

状态机：draft → sealed → delivered；unseal 仅 sealed→draft（清封存三痕，
unsealed_count 累计留痕）；v1 item_type 只开 'artifact'（document/file 留
扩展——版本表已在位，接线归后续轮）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from fde_api.auth.models import UTCDateTime
from fde_api.workbench.models import Base, TimestampMixin, new_uuid

HANDOVER_STATUSES = ("draft", "sealed", "delivered")
ITEM_TYPES_V1 = ("artifact",)  # D11 草案全集 document|file|artifact 的 v1 子集


class HandoverPackage(Base, TimestampMixin):
    """结项交付包：draft（可编辑清单）→ sealed（冻结+manifest 指纹）→ delivered（登记对外交付，不可逆）。"""

    __tablename__ = "handover_packages"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'sealed', 'delivered')",
            name="ck_handover_packages_status",
        ),
        # 状态一致性：draft 无封存痕；非 draft 必有封存人/时；delivered 必有交付人/时
        CheckConstraint(
            "(status = 'draft') = (sealed_at IS NULL)",
            name="ck_handover_packages_state",
        ),
        CheckConstraint(
            "(status = 'draft') OR (sealed_by_user_id IS NOT NULL AND manifest_sha256 IS NOT NULL)",
            name="ck_handover_packages_sealed_complete",
        ),
        CheckConstraint(
            "(status <> 'delivered') OR (delivered_by_user_id IS NOT NULL AND delivered_at IS NOT NULL)",
            name="ck_handover_packages_delivered_complete",
        ),
        CheckConstraint(
            "manifest_sha256 IS NULL OR char_length(manifest_sha256) = 64",
            name="ck_handover_packages_manifest_len",
        ),
        Index("ix_handover_packages_project_status", "project_id", "status"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False)
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    label: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft", server_default="draft")
    # 封存三痕（unseal 清空；再封存覆盖）
    sealed_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    sealed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    manifest_sha256: Mapped[str | None] = mapped_column(String(64))
    # 解封留痕（次数累计；末次操作人/时）
    unsealed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    unsealed_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    unsealed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    # 交付登记（admin 专属动作；终态不可逆）
    delivered_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class HandoverPackageItem(Base, TimestampMixin):
    """包内清单行：指针 + sha256 快照（校验锚）。同包同产物至多一行。"""

    __tablename__ = "handover_package_items"
    __table_args__ = (
        CheckConstraint(
            "item_type IN ('artifact')",
            name="ck_handover_package_items_type",
        ),
        CheckConstraint(
            "(item_type <> 'artifact') OR artifact_id IS NOT NULL",
            name="ck_handover_package_items_pointer",
        ),
        CheckConstraint("char_length(sha256) = 64", name="ck_handover_package_items_sha_len"),
        UniqueConstraint("package_id", "artifact_id", name="uq_handover_package_items_pkg_artifact"),
        Index("ix_handover_package_items_package", "package_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    package_id: Mapped[str] = mapped_column(
        ForeignKey("handover_packages.id", ondelete="CASCADE"), nullable=False
    )
    # v1 只开 artifact（T-B1 验收面）；document/file 类型随版本表接线扩枚举
    item_type: Mapped[str] = mapped_column(String(16), nullable=False, default="artifact", server_default="artifact")
    # B#6 纪律：纯指针无 FK（产物本体在项目工作目录 storage_ref，库内只有指纹）
    artifact_id: Mapped[str | None] = mapped_column(String(36))
    # —— 快照投影（登记入包时刻的冻结值；seal 时与 live 产物行逐项复核）——
    run_id: Mapped[str | None] = mapped_column(String(36))
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
