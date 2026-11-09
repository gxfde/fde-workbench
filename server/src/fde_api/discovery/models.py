"""discovery 模型：抽取行 + 业务事实 + 需求 + 需求来源（V3.1 P0-1 四表）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from fde_api.auth.models import UTCDateTime
from fde_api.workbench.models import Base, TimestampMixin, new_uuid

# 抽取来源：正式纪要（首选）或草稿区活动草稿
SOURCE_TYPES = ("interview_minutes", "transcript_draft")
# 抽取行状态机：queued→running→{review_required|failed}；重跑仅 failed
EXTRACTION_STATUSES = ("queued", "running", "review_required", "failed")
# 事实类型十值：任务书九值 + open_question（七组示例中的开放问题组归一）
FACT_TYPES = (
    "process", "role", "system", "rule", "data_object",
    "metric", "constraint", "pain_point", "decision", "open_question",
)
# 条目分类：对齐 guidance/ai_schema.py 五分类（AI 通道只产前四类的子集）
CLASSIFICATIONS = ("customer_stated", "ai_synthesized", "ai_inferred", "open_question", "human_added")
# 事实审阅态：pending→{accepted|rejected|needs_clarification}；needs_clarification 可再流转
FACT_REVIEW_STATUSES = ("pending", "accepted", "rejected", "needs_clarification")
# 需求类型六值（任务书 §5）
REQUIREMENT_TYPES = ("functional", "non_functional", "data", "integration", "security", "operational")
# 需求优先级（与 key_business_problems 的 severity 三档同构）
REQUIREMENT_PRIORITIES = ("high", "medium", "low")
# 需求状态机：与事实审阅同构（任务书 status+approved_* 字段名照用）
REQUIREMENT_STATUSES = ("pending", "accepted", "rejected", "needs_clarification")

# V31-P1b：抽取器与提示词版本随「分段抽取」升级（v1＝整篇一次成抽 + 原提示词；
# v2＝按行切片分批抽取 + 片级限定提示词 + 行号回基合并）。两者都进幂等键
# （project, source_type, source_id, extractor_version, prompt_version）——版本
# 升级后同源再抽生成新行（产出确实不同），试点期的 v1 行保留为历史事实。
EXTRACTOR_VERSION = "discovery-extractor-v2"
PROMPT_VERSION = "discovery-prompt-v2"

REDACTION_EVENT_TYPE = "discovery.redaction_review"

# V31-P1c：分段合并时被「每片配额」裁掉的条数留痕（不静默丢弃）。
MERGE_QUOTA_EVENT_TYPE = "discovery.merge_quota_capped"


class DiscoveryExtraction(Base, TimestampMixin):
    """一次结构化抽取：状态机 queued→running→{review_required|failed}。

    幂等键 = (project_id, source_type, source_id, extractor_version,
    prompt_version)——同源同版本重复创建返回既有行；源正文 sha 由服务端
    从源行快照（草稿/纪要正文不可变，快照仅供审计对账）。
    """

    __tablename__ = "discovery_extractions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'review_required', 'failed')",
            name="ck_discovery_extractions_status",
        ),
        CheckConstraint(
            "source_type IN ('interview_minutes', 'transcript_draft')",
            name="ck_discovery_extractions_source_type",
        ),
        CheckConstraint(
            "(status <> 'failed') OR (failure_code IS NOT NULL AND failure_code <> '')",
            name="ck_discovery_extractions_failed_reason",
        ),
        CheckConstraint(
            "(status <> 'failed') OR (failure_message IS NOT NULL)",
            name="ck_discovery_extractions_failed_message",
        ),
        CheckConstraint(
            "char_length(source_sha256) = 64",
            name="ck_discovery_extractions_sha_len",
        ),
        UniqueConstraint(
            "project_id", "source_type", "source_id", "extractor_version", "prompt_version",
            name="uq_discovery_extractions_source_version",
        ),
        Index("ix_discovery_extractions_project_status", "project_id", "status"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False)
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued", server_default="queued")
    extractor_version: Mapped[str] = mapped_column(String(40), nullable=False, default=EXTRACTOR_VERSION, server_default=EXTRACTOR_VERSION)
    prompt_version: Mapped[str] = mapped_column(String(40), nullable=False, default=PROMPT_VERSION, server_default=PROMPT_VERSION)
    ai_model: Mapped[str | None] = mapped_column(String(120))
    ai_generated_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    failure_code: Mapped[str | None] = mapped_column(String(60))
    failure_message: Mapped[str | None] = mapped_column(Text)
    # 输出端脱敏复核条目（#160 guidance.redaction_review 同形状）
    redaction_entries: Mapped[list[Any] | None] = mapped_column(JSON(none_as_null=True))


class BusinessFact(Base, TimestampMixin):
    """业务事实行：fact_type 十值 + 五分类 + 行级审阅态 + 来源定位。

    classification 语义：AI 通道只能产 customer_stated（带锚点引述）/
    ai_inferred（显式 inference 标记）/ open_question（needs_clarification）；
    ai_synthesized/human_added 保留给人工补录路径（v1 不开放人工写面）。
    """

    __tablename__ = "business_facts"
    __table_args__ = (
        CheckConstraint(
            "fact_type IN ('process', 'role', 'system', 'rule', 'data_object', "
            "'metric', 'constraint', 'pain_point', 'decision', 'open_question')",
            name="ck_business_facts_fact_type",
        ),
        CheckConstraint(
            "classification IN ('customer_stated', 'ai_synthesized', 'ai_inferred', 'open_question', 'human_added')",
            name="ck_business_facts_classification",
        ),
        CheckConstraint(
            "review_status IN ('pending', 'accepted', 'rejected', 'needs_clarification')",
            name="ck_business_facts_review_status",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_business_facts_confidence_range",
        ),
        CheckConstraint(
            "classification NOT IN ('open_question', 'ai_inferred') OR review_status = 'needs_clarification' OR reviewed_by_user_id IS NOT NULL",
            name="ck_business_facts_inference_review",
        ),
        CheckConstraint(
            "review_status NOT IN ('accepted', 'rejected') OR (reviewed_by_user_id IS NOT NULL AND reviewed_at IS NOT NULL)",
            name="ck_business_facts_review_stamp",
        ),
        CheckConstraint(
            "review_status <> 'pending' OR (reviewed_by_user_id IS NULL AND reviewed_at IS NULL)",
            name="ck_business_facts_pending_unstamped",
        ),
        UniqueConstraint("extraction_id", "fact_type", "subject", "predicate", name="uq_business_facts_batch_identity"),
        Index("ix_business_facts_project_review", "project_id", "review_status"),
        Index("ix_business_facts_extraction", "extraction_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False)
    extraction_id: Mapped[str] = mapped_column(ForeignKey("discovery_extractions.id", ondelete="RESTRICT"), nullable=False)
    fact_type: Mapped[str] = mapped_column(String(20), nullable=False)
    classification: Mapped[str] = mapped_column(String(20), nullable=False, default="customer_stated", server_default="customer_stated")
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    predicate: Mapped[str] = mapped_column(String(200), nullable=False)
    object_value: Mapped[Any] = mapped_column(JSON, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Numeric(3, 2))
    # 来源指针（如 interview_minutes:<id>）+ 定位（line/transcript_segment/char_span）
    source_ref: Mapped[str] = mapped_column(String(80), nullable=False)
    source_locator: Mapped[Any] = mapped_column(JSON, nullable=False)
    review_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", server_default="pending")
    reviewed_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    review_comment: Mapped[str | None] = mapped_column(String(500))


class Requirement(Base, TimestampMixin):
    """结构化需求：审阅态状态机 + 批准人留痕（approved_* 命名照任务书 §5）。

    requirement_key 项目内唯一（服务端派生 R-<uuid8>）；acceptance_criteria
    为字符串列表（≤20 条、每条 ≤500 字）——结构化列表而非自由文本，供
    P0-3 方案条目与 P1-2 测试计划逐条引用。
    """

    __tablename__ = "requirements"
    __table_args__ = (
        CheckConstraint(
            "requirement_type IN ('functional', 'non_functional', 'data', 'integration', 'security', 'operational')",
            name="ck_requirements_type",
        ),
        CheckConstraint(
            "priority IN ('high', 'medium', 'low')",
            name="ck_requirements_priority",
        ),
        CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected', 'needs_clarification')",
            name="ck_requirements_status",
        ),
        CheckConstraint(
            "status NOT IN ('accepted', 'rejected') OR (approved_by_user_id IS NOT NULL AND approved_at IS NOT NULL)",
            name="ck_requirements_review_stamp",
        ),
        CheckConstraint(
            "status <> 'pending' OR (approved_by_user_id IS NULL AND approved_at IS NULL)",
            name="ck_requirements_pending_unstamped",
        ),
        UniqueConstraint("project_id", "requirement_key", name="uq_requirements_project_key"),
        Index("ix_requirements_project_status", "project_id", "status"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False)
    extraction_id: Mapped[str] = mapped_column(ForeignKey("discovery_extractions.id", ondelete="RESTRICT"), nullable=False)
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    requirement_key: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    requirement_type: Mapped[str] = mapped_column(String(20), nullable=False)
    priority: Mapped[str] = mapped_column(String(10), nullable=False, default="medium", server_default="medium")
    acceptance_criteria: Mapped[list[Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", server_default="pending")
    approved_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    review_comment: Mapped[str | None] = mapped_column(String(500))


class RequirementSource(Base, TimestampMixin):
    """需求↔事实/来源关联（任务书：长期用关系表而非 JSON ID 数组）。

    fact_id 可空（需求可只带 source_ref+locator 无事实行）；去重由服务层
    保证（同 requirement 同 fact 或同 (source_ref, locator) 不重复建行）。
    """

    __tablename__ = "requirement_sources"
    __table_args__ = (
        UniqueConstraint("requirement_id", "fact_id", name="uq_requirement_sources_requirement_fact"),
        Index("ix_requirement_sources_requirement", "requirement_id"),
        Index("ix_requirement_sources_fact", "fact_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    requirement_id: Mapped[str] = mapped_column(ForeignKey("requirements.id", ondelete="CASCADE"), nullable=False)
    fact_id: Mapped[str | None] = mapped_column(ForeignKey("business_facts.id", ondelete="RESTRICT"))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(80), nullable=False)
    source_locator: Mapped[Any] = mapped_column(JSON, nullable=False)
