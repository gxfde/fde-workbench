"""术语表（V3 T-O1，域 2；设计 ontology-registry-v1 §2.2）与关系类型注册表
（V3 T-O2，§2.3）。

术语表：项目内术语/别名治理——一个规范业务名一行（UNIQUE(project, term)），
别名子表同项目唯一（UNIQUE(project, alias)）——同项目一个名字至多指向一个概念，
是「导入同名重复」（审计附录 D ⑨）的根治面。状态机沿用 guidance 语义：
draft → confirmed → superseded/merged；confirmed 后定义不可原地改（修订走
change_set 新版本，T-O3）；merged 行必须指向保留行（canonical_term_id），
被并掉的术语名与其别名转写为保留行的别名（合并保留来源，服务层保证）。
引用方（研究客体、表单、门禁）只引 term_id，不复制名称。

关系类型注册表：把「关系类型白名单硬编码 2 种」（审计附录 D ③）与
「对象类型 CheckConstraint 硬编码」（同 ②）搬进可注册表。内置五类对象类型与
两类关系类型**留在原处**（存量语义冻结），注册表只做「内置 ∪ 注册」的增量。
project_id 为 NULL = 全局类型（仅 admin 可建），非 NULL = 项目内类型；项目内
类型**遮蔽**同名全局类型（端点约束可按项目定制）。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    JSON,
    String,
    Text,
    UniqueConstraint,
    text,
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

# V3 T-O2：注册表两类——对象类型（subject_type）与关系类型（link_type）。
RELATION_TYPE_KINDS = ("subject_type", "link_type")
# draft（登记未启用）→ active（生效）→ retired（停用：禁新边、存量边只读）。
RELATION_TYPE_STATUSES = ("draft", "active", "retired")


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
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class OntologyRelationType(Base, TimestampMixin, VersionedMixin):
    """关系/对象类型注册（V3 T-O2，设计 ontology-registry-v1 §2.3）。

    一行 = 一个可注册的类型：kind=subject_type（对象类型登记）或 kind=link_type
    （关系类型，可带端点约束）。project_id 为 NULL = 全局类型（仅 admin 可建，
    对所有项目生效）；非 NULL = 项目内类型，并**遮蔽**同名全局类型（端点约束可
    按项目定制）。

    端点约束（allowed_source_types / allowed_target_types）只对 kind=link_type
    有意义：来源对象类型集合 / 目标对象类型集合；服务层据此校验边方向。内置两类
    关系类型（opportunity_role / opportunity_process）不写在本表——它们的端点
    约束是存量语义（冻结），注册表不得覆盖（服务层拒绝注册内置码）。
    """

    __tablename__ = "ontology_relation_types"
    __table_args__ = (
        # 项目内唯一：同项目同 kind 同 code 只有一行
        UniqueConstraint(
            "project_id", "kind", "code", name="uq_ontology_relation_types_project_code"
        ),
        # 全局唯一：project_id IS NULL 的行按 (kind, code) 唯一
        Index(
            "uq_ontology_relation_types_global_code",
            "kind",
            "code",
            unique=True,
            postgresql_where=text("project_id IS NULL"),
        ),
        CheckConstraint(
            "kind IN ('subject_type', 'link_type')",
            name="ck_ontology_relation_types_kind",
        ),
        CheckConstraint(
            "status IN ('draft', 'active', 'retired')",
            name="ck_ontology_relation_types_status",
        ),
        CheckConstraint(
            "json_typeof(allowed_source_types) = 'array' "
            "AND json_typeof(allowed_target_types) = 'array'",
            name="ck_ontology_relation_types_endpoints_json",
        ),
        # 关系类型必须声明端点约束（否则边的方向无从校验）
        CheckConstraint(
            "kind <> 'link_type' OR ("
            "json_array_length(allowed_source_types) > 0 "
            "AND json_array_length(allowed_target_types) > 0)",
            name="ck_ontology_relation_types_link_endpoints",
        ),
        Index("ix_ontology_relation_types_project_kind", "project_id", "kind"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    # NULL = 全局类型（仅 admin 可建）
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    code: Mapped[str] = mapped_column(String(60), nullable=False)
    label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    allowed_source_types: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    allowed_target_types: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
