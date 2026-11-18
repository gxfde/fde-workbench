"""data_engineering 域模型（AF2-WP1：画像产物落库面）。

DataProfile = 一次资料画像报告：来源文件名 + 逐字节指纹（``input_sha256``
快照可复验）+ 表统计/列统计/关系候选/脱敏样本。纪律：产物是**统计 +
掩码样本**，不含文件字节与敏感列原文（04 §3.2；测试钉
``test_profile_row_persisted_and_readable_via_model``）。

关系候选内嵌于 ``relation_candidates_json``，status 恒 ``candidate``——
不设独立候选表、不设翻转端点：未知关联不能自动变成生产 Join（03 §77），
WP2 受限 Join 走显式审批面时另立契约。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from fde_api.workbench.models import Base, TimestampMixin, new_uuid


class DataProfile(Base, TimestampMixin):
    __tablename__ = "data_profiles"
    __table_args__ = (
        Index("ix_data_profiles_project", "project_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    source_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    table_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # JSON 产物三件：表+列统计 / 关系候选（status 恒 candidate）/ 掩码样本
    tables_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    relation_candidates_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    samples_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "source_name": self.source_name,
            "input_sha256": self.input_sha256,
            "truncated": self.truncated,
            "table_count": self.table_count,
            "tables": self.tables_json,
            "relation_candidates": self.relation_candidates_json,
            "samples": self.samples_json,
            "created_by_user_id": self.created_by_user_id,
            "created_at": str(self.created_at),
            "updated_at": str(self.updated_at),
        }
