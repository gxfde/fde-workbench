"""一等证据表 project_evidence（V3 T-E1，域 3 底座；设计 ontology-registry-v1 §2.1）。

一次采集、多处引用、不可变、可审计：行 = (project, source_uri, content_sha256)
唯一指纹，指纹即幂等键；只存指针与指纹（红线：原件永远留在项目工作目录，
不进仓库不进数据库）。origin 记「出处+源块」粒度文本（吸收 fde-v2 证据粒度，
如 `gate:G5/客户成功案例` / `访谈纪要 2026-10-30 §3` / `file_version:<uuid>`），
captured_from 标来源通道。引用方（gates 清单项等）只持 evidence_id，不复制指针。
"""
from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from fde_api.workbench.models import Base, TimestampMixin, new_uuid

EVIDENCE_KINDS = ("gate", "task", "guidance", "research", "bridge", "workflow", "solution")
# captured_from 通道：human | bridge_sync:{id} | agent_run:{id} | job:{id} | workflow_node:{id}
CAPTURED_FROM_PREFIXES = ("human", "bridge_sync:", "agent_run:", "job:", "workflow_node:")


class ProjectEvidence(Base, TimestampMixin):
    __tablename__ = "project_evidence"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "source_uri", "content_sha256",
            name="uq_project_evidence_fingerprint",
        ),
        CheckConstraint(
            "kind IN ('gate', 'task', 'guidance', 'research', 'bridge', 'workflow', 'solution')",
            name="ck_project_evidence_kind",
        ),
        CheckConstraint("char_length(content_sha256) = 64", name="ck_project_evidence_sha256_len"),
        Index("ix_project_evidence_project_kind", "project_id", "kind"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    source_uri: Mapped[str] = mapped_column(String(500), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    origin: Mapped[str | None] = mapped_column(Text)
    captured_from: Mapped[str | None] = mapped_column(String(64))
    created_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
