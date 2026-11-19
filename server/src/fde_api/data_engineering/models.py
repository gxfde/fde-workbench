"""data_engineering 域模型（AF2-WP1 画像产物 + AF2-WP2 TransformPlan 计划面）。

DataProfile = 一次资料画像报告：来源文件名 + 逐字节指纹（``input_sha256``
快照可复验）+ 表统计/列统计/关系候选/脱敏样本。纪律：产物是**统计 +
掩码样本**，不含文件字节与敏感列原文（04 §3.2；测试钉
``test_profile_row_persisted_and_readable_via_model``）。

关系候选内嵌于 ``relation_candidates_json``，status 恒 ``candidate``——
不设独立候选表、不设翻转端点：未知关联不能自动变成生产 Join（03 §77），
WP2 受限 Join 走显式审批面时另立契约。

TransformPlan = 一次类型化转换计划（AF2-WP2 计划面）：九算子闭集 + 每
算子参数键集精确匹配（无自由表达式槽，03 §5）+ 结构静态校验报告 + op 级
依赖 DAG。纪律：只落**已通过静态校验**的计划（status 恒 ``validated``，
键空间封闭无生产态）；append-only、无 PATCH/DELETE；编译执行面归 WP3
design-first 门，本表不含任何可执行工件。
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
    # 画像来源二态（AF2-WP1 第二批 / D5）：file=资料侧上传（第一批）；connector=
    # 连接器侧 DB 内省（经 ontology_client 1.3.8-af2，掩码在 runtime 沙箱完成）
    source_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="file")
    # connector 快照锚四件（版本快照钉版本；file 画像为 NULL）
    ontology_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ontology_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    snapshot_sha256: Mapped[str | None] = mapped_column(String(80), nullable=True)
    data_source_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
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
            "source_kind": self.source_kind,
            "input_sha256": self.input_sha256,
            "ontology_id": self.ontology_id,
            "ontology_version_id": self.ontology_version_id,
            "snapshot_sha256": self.snapshot_sha256,
            "data_source_key": self.data_source_key,
            "truncated": self.truncated,
            "table_count": self.table_count,
            "tables": self.tables_json,
            "relation_candidates": self.relation_candidates_json,
            "samples": self.samples_json,
            "created_by_user_id": self.created_by_user_id,
            "created_at": str(self.created_at),
            "updated_at": str(self.updated_at),
        }


class TransformPlan(Base, TimestampMixin):
    __tablename__ = "transform_plans"
    __table_args__ = (
        Index("ix_transform_plans_project", "project_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    plan_version: Mapped[str] = mapped_column(String(32), nullable=False)
    # 键空间封闭：计划面唯一状态（无生产态字段，03 §77 / 15 号 §6 不做清单）
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="validated")
    source_profile_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_table: Mapped[str] = mapped_column(String(255), nullable=False)
    # 已通过静态校验的原始计划 + 校验报告（报告内含 DAG 与输出声明）
    plan_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    validation_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    def snapshot(self) -> dict[str, Any]:
        report = self.validation_json or {}
        return {
            "id": self.id,
            "project_id": self.project_id,
            "plan_version": self.plan_version,
            "status": self.status,
            "source_profile_id": self.source_profile_id,
            "source_table": self.source_table,
            "plan": self.plan_json,
            "validation": report,
            "dependency_graph": report.get("dependency_graph") or {},
            "output_columns": report.get("output_columns") or [],
            "created_by_user_id": self.created_by_user_id,
            "created_at": str(self.created_at),
            "updated_at": str(self.updated_at),
        }


class TransformRun(Base, TimestampMixin):
    """一次隔离执行（AF2-WP3，17 号 v1.0 已批规格）。

    纪律：append-only（无 PATCH/DELETE，重跑=新 run）；``idempotency_key``
    唯一＝幂等重放真身；``status`` 闭集 ``succeeded|failed|budget_exhausted|
    internal_inconsistency``（诚实终态，非静默截断）；**账本零行值原文**
    （条目={row_index, reason, column}，04 §3.2）；产物行集封顶落
    ``output_rows_json``；行数守恒机检钉落 ``conservation_json``。
    """

    __tablename__ = "transform_runs"
    __table_args__ = (
        Index("ix_transform_runs_project", "project_id"),
        Index("ix_transform_runs_plan", "plan_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    plan_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("transform_plans.id", ondelete="RESTRICT"), nullable=False
    )
    plan_version: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    input_anchor_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    output_rows_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    output_row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_columns_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    reject_ledger_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    rejected_row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    overflow_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quality_report_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    lineage_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    conservation_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "plan_id": self.plan_id,
            "plan_version": self.plan_version,
            "idempotency_key": self.idempotency_key,
            "status": self.status,
            "failure_reason": self.failure_reason,
            "input_anchor": self.input_anchor_json,
            "output_rows": self.output_rows_json,
            "output_row_count": self.output_row_count,
            "output_columns": self.output_columns_json,
            "reject_ledger": self.reject_ledger_json,
            "rejected_row_count": self.rejected_row_count,
            "overflow_count": self.overflow_count,
            "quality_report": self.quality_report_json,
            "lineage": self.lineage_json,
            "conservation": self.conservation_json,
            "created_by_user_id": self.created_by_user_id,
            "created_at": str(self.created_at),
            "updated_at": str(self.updated_at),
        }
