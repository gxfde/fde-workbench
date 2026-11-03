"""术语表（V3 T-O1，域 2；设计 ontology-registry-v1 §2.2）。

项目内术语/别名治理：一个规范业务名一行（UNIQUE(project, term)），别名子表
同项目唯一（UNIQUE(project, alias)）——同项目一个名字至多指向一个概念，是
「导入同名重复」（审计附录 D ⑨）的根治面。状态机沿用 guidance 语义：
draft → confirmed → superseded/merged；confirmed 后定义不可原地改（修订走
change_set 新版本，T-O3）；merged 行必须指向保留行（canonical_term_id），
被并掉的术语名与其别名转写为保留行的别名（合并保留来源，服务层保证）。
引用方（研究客体、表单、门禁）只引 term_id，不复制名称。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from fde_api.auth.models import UTCDateTime
from fde_api.workbench.models import (
    Base,
    TimestampMixin,
    VersionedMixin,
    new_uuid,
)

TERM_TYPES = ("entity", "attribute", "metric", "alias_target", "generic")
# 沿用 guidance 状态机语义：draft（候选）→ confirmed（发布本体）；
# superseded（被新版本取代）/ merged（重复，并入 canonical）为终态。
TERM_STATUSES = ("draft", "confirmed", "superseded", "merged")


class OntologyTerm(Base, TimestampMixin, VersionedMixin):
    __tablename__ = "ontology_terms"
    __table_args__ = (
        UniqueConstraint("project_id", "term", name="uq_ontology_terms_project_term"),
        CheckConstraint(
            "term_type IN ('entity', 'attribute', 'metric', 'alias_target', 'generic')",
            name="ck_ontology_terms_term_type",
        ),
        CheckConstraint(
            "status IN ('draft', 'confirmed', 'superseded', 'merged')",
            name="ck_ontology_terms_status",
        ),
        # merged 行必须指明并入了谁；其余状态允许无指向
        CheckConstraint(
            "status <> 'merged' OR canonical_term_id IS NOT NULL",
            name="ck_ontology_terms_merged_canonical",
        ),
        Index("ix_ontology_terms_project_status", "project_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    term: Mapped[str] = mapped_column(String(120), nullable=False)
    term_type: Mapped[str] = mapped_column(String(32), nullable=False, default="generic")
    # 确认后不可原地改：修订走 change_set 产生新版本行（T-O3），本表无编辑路径
    definition: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    # 合并指向：merged 行 → 保留行（自引用外键，PG 允许内联声明）
    canonical_term_id: Mapped[str | None] = mapped_column(
        ForeignKey("ontology_terms.id", ondelete="SET NULL")
    )
    confirmed_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class OntologyTermAlias(Base, TimestampMixin):
    __tablename__ = "ontology_term_aliases"
    __table_args__ = (
        # 同项目别名唯一：别名与规范名共用「一个名字一个概念」的唯一性口径
        UniqueConstraint(
            "project_id", "alias", name="uq_ontology_term_aliases_project_alias"
        ),
        Index("ix_ontology_term_aliases_term_id", "term_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    term_id: Mapped[str] = mapped_column(
        ForeignKey("ontology_terms.id", ondelete="CASCADE"), nullable=False
    )
    # 冗余 project_id：唯一约束按项目隔离，导入去重按项目点查（不随 term 迁移改写）
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    alias: Mapped[str] = mapped_column(String(120), nullable=False)
    created_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
