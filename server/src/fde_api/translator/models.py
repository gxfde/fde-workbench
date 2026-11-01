"""翻译器门户模型（goal-d9，PRD §3.2 P3）。

翻译器 = 创业者/售前（L2/L3）的轻量结构化输入通道：引导式表单 → AI 翻译
管道 → guidance 全契约草稿落库。草稿与项目 guidance 录入卡的「采纳流」
（把草稿升格为某项目的预调研分析版）不在本轮范围（挂账台账）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from fde_api.auth.models import UTCDateTime
from fde_api.workbench.models import Base, TimestampMixin, new_uuid


class TranslatorTranslation(Base, TimestampMixin):
    """一次翻译请求的 AI 草稿（AI 只出草稿、confirmed 必须人工——红线）。"""

    __tablename__ = "translator_translations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'ready', 'failed')",
            name="ck_translator_translations_status",
        ),
        Index("ix_translator_translations_creator", "created_by_user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    # 客户画像（industry/scale/region/interview_mode 四字段）
    profile_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    customer_vision: Mapped[str] = mapped_column(Text, nullable=False)
    phase_objective: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", server_default="pending")
    # validate_guidance_output 全契约草稿；None = 尚无 AI 结论
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    ai_model: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    ai_generated_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    failure_code: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    failure_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
