"""项目本体绑定与升级留痕（V3.3 任务书 §5.2；规格 = Fde-Ontology docs/v3.3/m1/ontology-data-model.md §3）。

**两段交付（D7 决策单，m2/00-m2-work-order.md）**：段 1 建表时 org_id 为可空
预留列；段 2（orgs 多租户轨道合流后）由迁移 c4a8f2e6b1d9 回填为**项目归属**
（projects.org_id）并收紧 NOT NULL；I5 运行时调用的 org 上下文段 2 起同样取
项目归属（D10 段 2；段 1 的 FDE_ONTOLOGY_ORG_ID 配置已退役）。

硬规则（§5.2 + I5）：
- 绑定必须指向已发布版本（draft 拒绝=409——由 service 层经 runtime 核实，I5/D10）；
- 一个项目可绑定多个本体；同项目同本体**单活跃**绑定：
  uq(project_id, ontology_id, active_marker)，retired 行 active_marker=NULL
  （MySQL 无部分索引的标准 NULL 等价；评审 W-A：全量 uq 会卡死 retire+successor 流）；
- 版本升级必须差异审查+批准（ontology_binding_upgrades 留痕，retire 不删行；
  status 含 upgrade_pending——data-model §3 原文）；
- 保留历史绑定与执行时版本。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from fde_api.auth.models import (
    Base,
)
from fde_api.workbench.models import TimestampMixin, VersionedMixin, new_uuid

ACTIVE_MARKER = "active"  # active_marker 列的占用值；retired/upgrade_pending 为 NULL


class ProjectOntologyBinding(Base, TimestampMixin, VersionedMixin):
    __tablename__ = "project_ontology_bindings"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'upgrade_pending', 'retired')",
            name="ck_project_ontology_bindings_status",
        ),
        # 单活跃绑定（评审 W-A）：retired 行以 NULL marker 退出唯一键
        UniqueConstraint(
            "project_id",
            "ontology_id",
            "active_marker",
            name="uq_project_ontology_bindings_project_ontology_active",
        ),
        Index("ix_project_ontology_bindings_project", "project_id"),
        Index("ix_project_ontology_bindings_org", "org_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    # D10 段 2：org 归属 = 项目归属（projects.org_id）；9d4f2b7e8c1a 建表时的
    # 可空预留列由 c4a8f2e6b1d9 回填并收紧为 NOT NULL（孤儿行响亮失败）
    org_id: Mapped[str] = mapped_column(String(36), nullable=False)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    ontology_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # opaque 指针（→ ontology-service ontology_versions.id，无 FK 跨库）
    pinned_version_id: Mapped[str] = mapped_column(String(36), nullable=False)
    pinned_version: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    binding_role: Mapped[str] = mapped_column(String(40), nullable=False, default="primary")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    # 唯一键状态位：status='active' ⇔ 'active'，其余 NULL（service 层同步维护）
    active_marker: Mapped[str | None] = mapped_column(String(16), nullable=True)
    bound_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    approved_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "ontology_id": self.ontology_id,
            "org_id": self.org_id,
            "pinned_version_id": self.pinned_version_id,
            "pinned_version": self.pinned_version,
            "binding_role": self.binding_role,
            "status": self.status,
            "version": self.version,
            "bound_by_user_id": self.bound_by_user_id,
            "approved_by_user_id": self.approved_by_user_id,
            "created_at": str(self.created_at),
            "updated_at": str(self.updated_at),
        }


class OntologyBindingUpgrade(Base, TimestampMixin):
    """升级留痕（§5.2："版本升级必须有差异审查和批准"+"保留历史绑定和执行时使用的版本"）。"""

    __tablename__ = "ontology_binding_upgrades"
    __table_args__ = (
        CheckConstraint(
            "status IN ('proposed', 'approved', 'rejected')", name="ck_ontology_binding_upgrades_status"
        ),
        Index("ix_ontology_binding_upgrades_binding", "binding_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    binding_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("project_ontology_bindings.id", ondelete="RESTRICT"), nullable=False
    )
    from_version_id: Mapped[str] = mapped_column(String(36), nullable=False)
    to_version_id: Mapped[str] = mapped_column(String(36), nullable=False)
    to_version: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    # opaque → ontology-service GET /change-sets/{id}（差异审查证据，I7 指针化）
    diff_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_change_set_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="proposed")
    proposed_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    approved_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    acted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # D16：批注回执指针——升级审批携带的 ontology_annotation 证据行
    # （§15 版本升级必须记录审批人和证据）
    annotation_evidence_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("project_evidence.id", ondelete="SET NULL"), nullable=True
    )

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "binding_id": self.binding_id,
            "from_version_id": self.from_version_id,
            "to_version_id": self.to_version_id,
            "to_version": self.to_version,
            "diff_summary": self.diff_summary,
            "source_change_set_id": self.source_change_set_id,
            "status": self.status,
            "proposed_by_user_id": self.proposed_by_user_id,
            "approved_by_user_id": self.approved_by_user_id,
            "acted_at": str(self.acted_at) if self.acted_at is not None else None,
            "annotation_evidence_id": self.annotation_evidence_id,
        }
