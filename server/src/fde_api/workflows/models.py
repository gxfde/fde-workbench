"""Workflow 定义表（V3 T-W1；设计 workflow-dag-v1 §2 workflow_definitions + 版本行）。

决策 3：**不复制队列**——workflow 将来是 background_jobs 的一个 job_type；本模块
只有「定义 + 不可变版本」两表，runs / node_runs（T-W2）与执行器（T-W3）后续落地。
版本化沿 WB 已验证的「定义 + 版本行」双表（skill_definitions / skill_versions 同构）：
定义行可改（draft），发布即把 dag_json 快照成版本行，**版本行不可变**；已发布定义
再改动会自动开新草稿版本（version+1），运行时固定引用版本号（fde-v2 教训：跑动中
被改即受影响）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from fde_api.auth.models import UTCDateTime
from fde_api.workbench.models import Base, TimestampMixin, new_uuid

WORKFLOW_STATUSES = ("draft", "published", "archived")
# 没有 condition/wait 节点——when 表达式与 depends_on 已覆盖既有需求；新类型待真实需求
NODE_TYPES = ("call", "skill", "agent", "human_approval")


class WorkflowDefinition(Base, TimestampMixin):
    __tablename__ = "workflow_definitions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'published', 'archived')", name="ck_workflow_definitions_status"
        ),
        CheckConstraint("version >= 1", name="ck_workflow_definitions_version"),
        Index("ix_workflow_definitions_project_status", "project_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    # NULL = 平台模板（仅 admin），非 NULL = 项目内定义
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    dag_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'")
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="draft", server_default="draft"
    )
    # 当前（草稿或已发布）版本号；发布时快照到版本行，再改动则 +1 开新草稿
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    # dag_json 规范化（sort_keys/紧凑）后的 sha256
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    created_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    published_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class WorkflowDefinitionVersion(Base, TimestampMixin):
    """发布快照：一行 = 一个被锁定的 dag_json 版本，**写后不可变**。"""

    __tablename__ = "workflow_definition_versions"
    __table_args__ = (
        UniqueConstraint(
            "definition_id", "version", name="uq_workflow_definition_versions_definition_version"
        ),
        CheckConstraint("version >= 1", name="ck_workflow_definition_versions_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    definition_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_definitions.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    dag_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    published_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    published_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
