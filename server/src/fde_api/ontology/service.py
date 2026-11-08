"""术语生命周期原语（V3 T-O1）、关系类型注册原语（V3 T-O2）与变更集事务
（V3 T-O3）。

术语（V3 T-O1）：create / confirm / merge（合并保留来源）。
零路由（沿 T-W1 先例）：术语的 REST 面（只读 GET terms 与 change-set 变更面）
随 T-O3 的 routes.py 一并开——设计 §4 里术语唯一公开路径是只读 GET，写路径
一律经 change_sets propose→confirm（AI 候选永不直接写表，沿 guidance
adopt→confirm 样板），本文件的函数就是 confirm 事务里逐项物化的原语。

关系类型（V3 T-O2）：register / retire + 解析查询。设计 §2.3 的注册表把
「关系类型白名单硬编码 2 种」「对象类型 CheckConstraint 硬编码」搬进可注册
表；内置两类关系类型的端点约束是**存量语义（冻结）**，注册表不得覆盖——
注册内置码一律 409 duplicate_code；服务层解析时内置优先，保证「∪ 语义不放
开内置方向校验」（backlog T-O2 风险条）。

变更集（V3 T-O3）：AI 候选唯一入口——propose（形状校验 + 归一化载荷，不触
DB 状态）→ submit（受影响行快照取 base 指纹）→ confirm（复核指纹 + 单事务
逐项物化，全成全败）/ reject（留 reason）。语义裁决（backlog T-O3 实施记录）：
- 修订同名术语 = 原行 definition/term_type 受控改写（仅 change-set confirm
  一条路），旧定义随逐项结果进 `ontology_change_set_confirmed` 事件留档；
  UNIQUE(project, term) 使同名新行不可共存，行级取代（superseded）只发生在
  改名分支（new_term）。
- create_subject / link_subjects 设计列有、本轮不开放（payload_schema 拒）。
- confirm 验收分离：拍板人 ≠ 提交人（沿 gate P0-5 纪律，403）。

不变式（§5 用例 1/2/3/4/7）：
- confirmed 后定义不可原地改——服务层不提供 change-set 之外的任何 definition
  编辑路径；直接编辑（无路由/原语）不可达。
- 合并保留来源——merge_terms 把被并术语的规范名转写为保留行的别名并落逐项
  OperationEvent；被并行的既有别名不动（别名→merged 行→canonical 链可解析，
  不可变优先）。同项目「一个名字至多一个概念」由 create/别名写入共同把守。
- retired 关系类型禁新边、存量边只读——retire 只改注册表状态，不动既有边行。
- AI 候选 confirm 前不物化——propose 只写变更集行本身（用例 1）。

影响分析（V3 T-I1，设计 §5 用例 6 / 验收 O-6）：impact_of_term 列出引用某
术语的研究客体/邻接边/表单。引用合同 = **名字域纽带**——当前实现无 term_id
外键（fde-v2「引用方只引 term_id」未随融合裁决落地），「一个名字一个概念」
（UNIQUE(project, term) + UNIQUE(project, alias)）使名字精确等价概念引用；
生效名字域 = 血缘（根 + 并入来源）内规范名 ∪ 别名（merge_terms 转写来源
规范名为保留行别名、来源自有别名留在来源行，闭包全部可解析到同一概念）。
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from fde_api.auth.models import User
from fde_api.extensions import db
from fde_api.ontology.models import (
    CHANGE_SET_STATUSES,
    RELATION_TYPE_KINDS,
    RELATION_TYPE_STATUSES,
    TERM_TYPES,
    OntologyChangeSet,
    OntologyRelationType,
    OntologyTerm,
    OntologyTermAlias,
)
from fde_api.projects.events import record_event
from fde_api.projects.permissions import project_access
# V3 T-I1 影响分析读 research 三表（models 叶子模块，不回导 ontology——
# 方向恒 research.*_service → ontology.service → research.models，无环）。
from fde_api.research.models import (
    ProjectResearchForm,
    ProjectResearchFormRevision,
    ProjectResearchSubject,
    ProjectResearchSubjectLink,
)
from fde_api.workbench.models import Project

TERM_MAX_LENGTH = 120

# 物化原语允许的落库状态：T-O3 change-set confirm 按载荷逐项直落 confirmed；
# 导入/人工新建默认 draft。
_INITIAL_STATUSES = ("draft", "confirmed")

# ---------------------------------------------------------------------------
# V3 T-O2：关系/对象类型注册表
# ---------------------------------------------------------------------------

RELATION_TYPE_CODE_MAX_LENGTH = 60
RELATION_TYPE_LABEL_MAX_LENGTH = 120
RELATION_TYPE_DESCRIPTION_MAX_LENGTH = 2000
_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

# 内置类型码的保留名单（存量语义冻结，注册表不得覆盖）：
# 内置对象类型 = research/models.py 的 SUBJECT_TYPES；
# 内置关系类型 = research/subject_service.py 的 LINK_SUBJECT_TYPES 的键。
# 两处的一致性由测试钉住（test_ontology_registry.py），避免漂移。
BUILTIN_SUBJECT_TYPE_CODES = frozenset(
    {"project", "department", "role", "process", "opportunity"}
)
BUILTIN_LINK_TYPE_CODES = frozenset({"opportunity_role", "opportunity_process"})

# 注册时的落库状态：从合法状态域派生（'retired' 是终态，不能作为初始态）——
# 'draft' 留给 T-O3 变更集（提出的类型先落 draft，confirm 时转 active）。
_RELATION_TYPE_INITIAL_STATUSES = tuple(
    status for status in RELATION_TYPE_STATUSES if status != "retired"
)
# HTTP 面允许的登记字段
_REGISTER_TYPE_FIELDS = {
    "kind",
    "code",
    "label",
    "description",
    "allowed_source_types",
    "allowed_target_types",
    "scope",
}


class OntologyServiceError(Exception):
    def __init__(self, code: str, message: str, status: int):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _normalize_name(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise OntologyServiceError("invalid_request", f"{field} 必须为字符串。", 400)
    name = value.strip()
    if not name:
        raise OntologyServiceError("invalid_request", f"{field} 不能为空白。", 400)
    if len(name) > TERM_MAX_LENGTH:
        raise OntologyServiceError(
            "invalid_request", f"{field} 长度不能超过 {TERM_MAX_LENGTH}。", 400
        )
    return name


def _normalize_term_type(value: object) -> str:
    if value is None:
        return "generic"
    if not isinstance(value, str) or value not in TERM_TYPES:
        raise OntologyServiceError("invalid_request", "term_type 值无效。", 400)
    return value


def _link_subjects_to_term(session: Session, *, project_id: str, term_id: str, name: str) -> int:
    """ADR-002 稳定 ID 试点：术语落定（confirmed）时自动链接同名调研主体。

    一次性 UPDATE、只链接尚未链接的行（term_id IS NULL）——已链接行不回改，
    术语合并/停用不改写历史行（读路径由 impact_of_term 名字域继续兜底）。
    name 为 String(160) 而 term ≤120：超长主体名天然无匹配（不链接）。
    """
    from fde_api.research.models import ProjectResearchSubject  # 延迟导入防环（research→ontology）

    result = session.execute(
        update(ProjectResearchSubject)
        .where(
            ProjectResearchSubject.project_id == project_id,
            ProjectResearchSubject.name == name,
            ProjectResearchSubject.term_id.is_(None),
        )
        .values(term_id=term_id)
    )
    rowcount = getattr(result, "rowcount", 0)
    return int(rowcount or 0)


def cross_project_name_conflicts(
    session: Session, *, project_id: str, names: list[str]
) -> list[dict[str, Any]]:
    """D-1 只读告警：同名术语/别名在**其它项目**中的分布。

    不阻断、不动项目内唯一约束（多项目隔离是刻意设计）；仅把「同一名字
    在别处也是概念」的事实带给操作者（改名/合并决策输入）。
    """
    if not names:
        return []
    hits: dict[str, set[str]] = {}
    for pid, name in session.execute(
        select(OntologyTerm.project_id, OntologyTerm.term).where(
            OntologyTerm.term.in_(names),
            OntologyTerm.project_id != project_id,
            OntologyTerm.status == "confirmed",
        )
    ):
        hits.setdefault(name, set()).add(pid)
    for pid, name in session.execute(
        select(OntologyTermAlias.project_id, OntologyTermAlias.alias).where(
            OntologyTermAlias.alias.in_(names),
            OntologyTermAlias.project_id != project_id,
        )
    ):
        hits.setdefault(name, set()).add(pid)
    return [
        {"term": name, "project_ids": sorted(pids)} for name, pids in sorted(hits.items())
    ]


def _occupied_term_names(session: Session, *, project_id: str) -> set[str]:
    """项目内名字域占用集（根规范名 ∪ 别名；含 merged/superseded 历史名）。"""
    terms = session.scalars(
        select(OntologyTerm.term).where(OntologyTerm.project_id == project_id)
    ).all()
    aliases = session.scalars(
        select(OntologyTermAlias.alias).where(OntologyTermAlias.project_id == project_id)
    ).all()
    return set(terms) | set(aliases)


def create_term(
    session: Session,
    *,
    project_id: str,
    term: object,
    definition: object,
    actor: User,
    term_type: object = None,
    initial_status: str = "draft",
) -> OntologyTerm:
    """新建术语行（同事务物化原语）：同项目同名唯一；名字不得与既有别名冲突。

    initial_status 仅限 draft/confirmed（T-O3 confirm 载荷直落 confirmed 用，
    语义与 T-S1 种子 initial_status 一致）；definition 一经落行不可原地改。
    """
    name = _normalize_name(term, field="term")
    text = _normalize_name(definition, field="definition")
    kind = _normalize_term_type(term_type)
    if initial_status not in _INITIAL_STATUSES:
        raise OntologyServiceError("invalid_request", "initial_status 值无效。", 400)

    alias_owner = session.scalar(
        select(OntologyTermAlias).where(
            OntologyTermAlias.project_id == project_id,
            OntologyTermAlias.alias == name,
        )
    )
    if alias_owner is not None:
        raise OntologyServiceError(
            "term_exists",
            f"「{name}」已是同项目别名，不能另立术语（请走合并流程）。",
            409,
        )
    duplicate = session.scalar(
        select(OntologyTerm).where(
            OntologyTerm.project_id == project_id, OntologyTerm.term == name
        )
    )
    if duplicate is not None:
        if duplicate.status == "merged" and duplicate.canonical_term_id:
            canonical = session.get(OntologyTerm, duplicate.canonical_term_id)
            raise OntologyServiceError(
                "term_exists",
                f"「{name}」已并入「{canonical.term if canonical else duplicate.canonical_term_id}」，"
                "不能另立术语（引用保留行或走修订）。",
                409,
            )
        raise OntologyServiceError(
            "term_exists", f"术语「{name}」在同项目已存在。", 409
        )

    row = OntologyTerm(
        project_id=project_id,
        term=name,
        term_type=kind,
        definition=text,
        status=initial_status,
        created_by_user_id=actor.id,
    )
    if initial_status == "confirmed":
        # T-O3 confirm 载荷直落 confirmed：拍板人与拍板时刻随物化落行
        row.confirmed_by_user_id = actor.id
        row.confirmed_at = datetime.now(UTC)
    try:
        with session.begin_nested():
            session.add(row)
            session.flush()
    except IntegrityError:
        # 并发同名单：保存点已回退，读回赢家
        winner = session.scalar(
            select(OntologyTerm).where(
                OntologyTerm.project_id == project_id, OntologyTerm.term == name
            )
        )
        if winner is None:
            raise
        raise OntologyServiceError(
            "term_exists", f"术语「{name}」在同项目已存在。", 409
        ) from None
    if initial_status == "confirmed":
        # ADR-002 试点：术语落定即链接同名调研主体（一次性、幂等、可空列）
        _link_subjects_to_term(session, project_id=project_id, term_id=row.id, name=name)
    return row


def confirm_term(session: Session, *, term_id: str, actor: User) -> OntologyTerm:
    """draft → confirmed（拍板）；confirmed 不可重复确认/原地改（409 term_immutable）。"""
    row = session.get(OntologyTerm, term_id)
    if row is None:
        raise OntologyServiceError("term_not_found", "术语不存在。", 404)
    if row.status == "confirmed":
        raise OntologyServiceError(
            "term_immutable",
            "已确认术语不可原地修改（修订走 change_set 新版本）。",
            409,
        )
    if row.status in ("superseded", "merged"):
        raise OntologyServiceError(
            "invalid_transition", f"状态 {row.status} 为终态，不能再确认。", 409
        )
    row.status = "confirmed"
    row.confirmed_by_user_id = actor.id
    row.confirmed_at = datetime.now(UTC)
    row.version += 1
    session.flush()
    return row


def merge_terms(
    session: Session, *, source_id: str, target_id: str, actor: User
) -> dict[str, Any]:
    """source 并入 target（同项目）：source→merged 指向 target，target 转写
    获得 source 规范名作为别名（合并保留来源），逐项落 OperationEvent。

    source 的既有别名不动（别名→merged 行→canonical 一跳可解析）；同项目
    「一个名字至多一个概念」的口径使 target 名下不会撞出同名别名，仍防御性
    跳过占用。重复合并/终态目标是调用方错误，一律 409。
    """
    source = session.get(OntologyTerm, source_id)
    target = session.get(OntologyTerm, target_id)
    if source is None or target is None:
        raise OntologyServiceError("term_not_found", "术语不存在。", 404)
    if source.id == target.id:
        raise OntologyServiceError("merge_invalid", "不能把术语并入自身。", 409)
    if source.project_id != target.project_id:
        raise OntologyServiceError(
            "merge_cross_project", "合并必须发生在同项目内。", 409
        )
    if source.status == "merged":
        raise OntologyServiceError(
            "term_already_merged", "术语已并入其它术语，不能重复合并。", 409
        )
    if source.status == "superseded":
        raise OntologyServiceError(
            "invalid_transition", "已被新版本取代的术语不能参与合并。", 409
        )
    if target.status in ("superseded", "merged"):
        raise OntologyServiceError(
            "merge_target_invalid", "合并目标必须是存活的 draft/confirmed 术语。", 409
        )

    added = _ensure_alias(
        session,
        project_id=target.project_id,
        term_id=target.id,
        alias=source.term,
        actor=actor,
        exclude_term_id=source.id,
    )
    # 链一跳化：曾并入 source 的 merged 行直接重指 target（别名解析恒一跳，
    # 不出现 merged→merged→…链）；被并行既有别名不动（别名→canonical 可解析）。
    dependents = list(
        session.scalars(
            select(OntologyTerm).where(
                OntologyTerm.canonical_term_id == source.id,
                OntologyTerm.status == "merged",
            )
        )
    )
    for dependent in dependents:
        dependent.canonical_term_id = target.id
        dependent.version += 1
    repointed = len(dependents)
    source.status = "merged"
    source.canonical_term_id = target.id
    source.version += 1
    target.version += 1
    session.flush()
    record_event(
        session,
        actor,
        "ontology_term_merged",
        source,
        {
            "merged_term": source.term,
            "canonical_term_id": target.id,
            "canonical_term": target.term,
            "alias_added": added,
            "repointed": repointed,
        },
    )
    return {
        "source": serialize_term(source),
        "target": serialize_term(target),
        "aliases_added": [source.term] if added else [],
    }


def serialize_term(row: OntologyTerm) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "term": row.term,
        "term_type": row.term_type,
        "definition": row.definition,
        "status": row.status,
        "canonical_term_id": row.canonical_term_id,
        "version": row.version,
        "confirmed_by_user_id": row.confirmed_by_user_id,
        "confirmed_at": row.confirmed_at.isoformat() if row.confirmed_at else None,
        "created_by_user_id": row.created_by_user_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _ensure_alias(
    session: Session,
    *,
    project_id: str,
    term_id: str,
    alias: str,
    actor: User,
    exclude_term_id: str | None = None,
) -> bool:
    """写别名（幂等）：同项目一个名字至多一个概念，占用即跳过返回 False。

    exclude_term_id：合并场景排除 source 自身——source 的名字即将让位给
    别名（source 行转 merged，规范名列保留为不可变历史，不构成占用）。
    """
    if session.scalar(
        select(OntologyTermAlias).where(
            OntologyTermAlias.project_id == project_id,
            OntologyTermAlias.alias == alias,
        )
    ) is not None:
        return False
    owner_query = select(OntologyTerm).where(
        OntologyTerm.project_id == project_id, OntologyTerm.term == alias
    )
    if exclude_term_id is not None:
        owner_query = owner_query.where(OntologyTerm.id != exclude_term_id)
    if session.scalar(owner_query) is not None:
        return False
    try:
        with session.begin_nested():
            session.add(
                OntologyTermAlias(
                    project_id=project_id,
                    term_id=term_id,
                    alias=alias,
                    created_by_user_id=actor.id,
                )
            )
            session.flush()
    except IntegrityError:
        return False
    return True


# ---------------------------------------------------------------------------
# V3 T-O2：关系/对象类型注册原语
# ---------------------------------------------------------------------------


def _normalize_kind(value: object) -> str:
    if not isinstance(value, str) or value not in RELATION_TYPE_KINDS:
        raise OntologyServiceError(
            "invalid_request", f"kind 仅可为 {'/'.join(RELATION_TYPE_KINDS)}。", 400
        )
    return value


def _normalize_code(value: object) -> str:
    if not isinstance(value, str):
        raise OntologyServiceError("invalid_request", "code 必须为字符串。", 400)
    code = value.strip()
    if not code:
        raise OntologyServiceError("invalid_request", "code 不能为空白。", 400)
    if len(code) > RELATION_TYPE_CODE_MAX_LENGTH:
        raise OntologyServiceError(
            "invalid_request",
            f"code 长度不能超过 {RELATION_TYPE_CODE_MAX_LENGTH}。",
            400,
        )
    if _CODE_PATTERN.fullmatch(code) is None:
        raise OntologyServiceError(
            "invalid_request",
            "code 只能是小写字母开头、仅含小写字母/数字/下划线。",
            400,
        )
    return code


def _normalize_optional_text(value: object, *, field: str, limit: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise OntologyServiceError("invalid_request", f"{field} 必须为字符串。", 400)
    text = value.strip()
    if not text:
        return None
    if len(text) > limit:
        raise OntologyServiceError(
            "invalid_request", f"{field} 长度不能超过 {limit}。", 400
        )
    return text


def _normalize_endpoints(value: object, *, field: str) -> list[str]:
    """端点约束（对象类型码列表）：非空列表、元素为字符串、去重保序。"""
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise OntologyServiceError("invalid_request", f"{field} 必须为数组。", 400)
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise OntologyServiceError(
                "invalid_request", f"{field} 的元素必须为字符串。", 400
            )
        code = item.strip()
        if not code:
            raise OntologyServiceError(
                "invalid_request", f"{field} 不能含空白元素。", 400
            )
        if len(code) > 32:
            raise OntologyServiceError(
                "invalid_request", f"{field} 的元素长度不能超过 32。", 400
            )
        if code not in result:
            result.append(code)
    return result


def known_subject_type_codes(session: Session, *, project_id: str | None) -> set[str]:
    """已知对象类型码 = 内置五类 ∪ 注册表已登记的对象类型（全局 ∪ 项目内）。

    注册关系类型时校验端点约束引用的是已知类型；顺序有依赖——先登记对象类型，
    再登记引用它的关系类型（错误信息里点明）。
    """
    codes = set(BUILTIN_SUBJECT_TYPE_CODES)
    query = select(OntologyRelationType.code).where(
        OntologyRelationType.kind == "subject_type"
    )
    if project_id:
        query = query.where(
            or_(
                OntologyRelationType.project_id == project_id,
                OntologyRelationType.project_id.is_(None),
            )
        )
    else:
        query = query.where(OntologyRelationType.project_id.is_(None))
    codes.update(session.scalars(query).all())
    return codes


def usable_subject_type_codes(session: Session, *, project_id: str | None) -> set[str]:
    """当前可用于**新建**调研对象的对象类型码（V3 T-O2b 值域开放面）。

    与 ``known_subject_type_codes``（引用解析，含 retired）不同：retire 语义是
    「禁新建、存量只读」（同 T-O2 关系类型的存量边纪律），draft 是未拍板提案
    ——两者都不得开新对象，故只收 active 行。
    """
    codes = set(BUILTIN_SUBJECT_TYPE_CODES)
    query = select(OntologyRelationType.code).where(
        OntologyRelationType.kind == "subject_type",
        OntologyRelationType.status == "active",
    )
    if project_id:
        query = query.where(
            or_(
                OntologyRelationType.project_id == project_id,
                OntologyRelationType.project_id.is_(None),
            )
        )
    else:
        query = query.where(OntologyRelationType.project_id.is_(None))
    codes.update(session.scalars(query).all())
    return codes


def find_relation_type(
    session: Session, *, project_id: str, kind: str, code: str
) -> OntologyRelationType | None:
    """解析生效的类型行：项目内类型遮蔽同名全局类型（项目可定制端点约束）。"""
    if project_id:
        scoped = session.scalar(
            select(OntologyRelationType).where(
                OntologyRelationType.project_id == project_id,
                OntologyRelationType.kind == kind,
                OntologyRelationType.code == code,
            )
        )
        if scoped is not None:
            return scoped
    return session.scalar(
        select(OntologyRelationType).where(
            OntologyRelationType.project_id.is_(None),
            OntologyRelationType.kind == kind,
            OntologyRelationType.code == code,
        )
    )


def list_relation_types(
    session: Session, *, project_id: str
) -> list[OntologyRelationType]:
    """列出对某项目生效的类型行：全局 ∪ 项目内，同 (kind, code) 以项目内为准。"""
    rows = session.scalars(
        select(OntologyRelationType)
        .where(
            or_(
                OntologyRelationType.project_id == project_id,
                OntologyRelationType.project_id.is_(None),
            )
        )
        .order_by(
            OntologyRelationType.kind.asc(),
            OntologyRelationType.code.asc(),
            OntologyRelationType.id.asc(),
        )
    ).all()
    effective: dict[tuple[str, str], OntologyRelationType] = {}
    for row in rows:
        key = (row.kind, row.code)
        if key in effective and row.project_id is None:
            # 全局行已被项目内行遮蔽
            continue
        effective[key] = row
    return sorted(
        effective.values(), key=lambda row: (row.kind, row.code, row.id)
    )


def serialize_relation_type(row: OntologyRelationType) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "scope": "global" if row.project_id is None else "project",
        "kind": row.kind,
        "code": row.code,
        "label": row.label,
        "description": row.description,
        "allowed_source_types": list(row.allowed_source_types or []),
        "allowed_target_types": list(row.allowed_target_types or []),
        "status": row.status,
        "version": row.version,
        "created_by_user_id": row.created_by_user_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def register_relation_type(
    session: Session,
    *,
    project_id: str | None,
    kind: object,
    code: object,
    actor: User,
    label: object = None,
    description: object = None,
    allowed_source_types: object = None,
    allowed_target_types: object = None,
    initial_status: str = "active",
) -> OntologyRelationType:
    """登记一个类型（同事务物化原语）。

    project_id=None = 全局类型（仅 admin 可建）；否则项目内类型。
    内置类型码不可被覆盖（409 duplicate_code）——存量语义冻结。
    端点约束只对 kind=link_type 有意义，且两端都必须非空。
    """
    normalized_kind = _normalize_kind(kind)
    normalized_code = _normalize_code(code)
    if initial_status not in _RELATION_TYPE_INITIAL_STATUSES:
        raise OntologyServiceError("invalid_request", "status 值无效。", 400)
    if normalized_kind == "link_type":
        if normalized_code in BUILTIN_LINK_TYPE_CODES:
            raise OntologyServiceError(
                "duplicate_code",
                f"「{normalized_code}」是内置关系类型，不可被注册表覆盖。",
                409,
            )
    elif normalized_code in BUILTIN_SUBJECT_TYPE_CODES:
        raise OntologyServiceError(
            "duplicate_code",
            f"「{normalized_code}」是内置对象类型，不可被注册表覆盖。",
            409,
        )

    sources = _normalize_endpoints(
        allowed_source_types, field="allowed_source_types"
    )
    targets = _normalize_endpoints(
        allowed_target_types, field="allowed_target_types"
    )
    if normalized_kind == "subject_type":
        if sources or targets:
            raise OntologyServiceError(
                "invalid_request",
                "对象类型不声明端点约束（allowed_source_types/allowed_target_types 必须为空）。",
                400,
            )
    else:
        if not sources or not targets:
            raise OntologyServiceError(
                "invalid_request",
                "关系类型必须声明 allowed_source_types 与 allowed_target_types。",
                400,
            )
        known = known_subject_type_codes(session, project_id=project_id)
        unknown = sorted(
            code for code in (*sources, *targets) if code not in known
        )
        if unknown:
            raise OntologyServiceError(
                "invalid_request",
                "端点约束引用了未登记的对象类型："
                f"{'、'.join(unknown)}（先登记对象类型再登记引用它的关系类型）。",
                400,
            )

    row = OntologyRelationType(
        project_id=project_id,
        kind=normalized_kind,
        code=normalized_code,
        label=_normalize_optional_text(
            label, field="label", limit=RELATION_TYPE_LABEL_MAX_LENGTH
        ),
        description=_normalize_optional_text(
            description,
            field="description",
            limit=RELATION_TYPE_DESCRIPTION_MAX_LENGTH,
        ),
        allowed_source_types=sources,
        allowed_target_types=targets,
        status=initial_status,
        created_by_user_id=actor.id,
    )
    try:
        with session.begin_nested():
            session.add(row)
            session.flush()
    except IntegrityError:
        existing = session.scalar(
            select(OntologyRelationType).where(
                OntologyRelationType.project_id == project_id,
                OntologyRelationType.kind == normalized_kind,
                OntologyRelationType.code == normalized_code,
            )
        )
        if existing is None:
            raise
        raise OntologyServiceError(
            "duplicate_code",
            f"同作用域已存在类型「{normalized_code}」。",
            409,
        ) from None
    return row


def retire_relation_type(
    session: Session, *, relation_type_id: str, actor: User
) -> OntologyRelationType:
    """停用一个类型：禁新边、存量边只读（既有边行不动）。"""
    row = session.get(OntologyRelationType, relation_type_id)
    if row is None:
        raise OntologyServiceError("relation_type_not_found", "类型不存在。", 404)
    if row.status == "retired":
        raise OntologyServiceError(
            "invalid_transition", "类型已停用，不能重复停用。", 409
        )
    row.status = "retired"
    row.version += 1
    session.flush()
    return row


# ---------------------------------------------------------------------------
# V3 T-O3：变更集（批量变更事务单元 + diff 评审 + base 指纹并发防护）
# ---------------------------------------------------------------------------

CHANGE_SET_TITLE_MAX_LENGTH = 200
CHANGE_SET_DESCRIPTION_MAX_LENGTH = 2000
CHANGE_SET_REJECTED_REASON_MAX_LENGTH = 2000
# 批量上限：防 AI 一次灌爆评审面；超出直接 payload_schema
CHANGE_SET_MAX_ITEMS = 50

# 设计 §2.4 载荷动作域。create_subject / link_subjects 设计列有、本轮不开放
# （业务对象候选走既有表单/导入人工路径），propose 时显式点名拒绝。
CHANGE_SET_ACTIONS = (
    "create_term",
    "update_term",
    "merge_terms",
    "register_relation_type",
)
_CHANGE_SET_DEFERRED_ACTIONS = ("create_subject", "link_subjects")
# 每个动作的必填字段（propose 形状校验；值级校验随归一化进行）
_CHANGE_SET_REQUIRED_FIELDS = {
    "create_term": ("term", "definition"),
    "update_term": ("term", "definition"),
    "merge_terms": ("source_term", "target_term"),
    "register_relation_type": ("kind", "code"),
}
# 每个动作允许的字段全集（含可选项；action 本身单列）
_CHANGE_SET_ALLOWED_FIELDS = {
    "create_term": {"term", "definition", "term_type"},
    "update_term": {"term", "definition", "term_type", "new_term"},
    "merge_terms": {"source_term", "target_term"},
    "register_relation_type": {
        "kind",
        "code",
        "label",
        "description",
        "allowed_source_types",
        "allowed_target_types",
    },
}
_ACTION_LABELS = {
    "create_term": "新建术语",
    "update_term": "修订术语",
    "merge_terms": "合并术语",
    "register_relation_type": "登记类型",
}


def _normalize_change_set_title(value: object) -> str:
    if not isinstance(value, str):
        raise OntologyServiceError("invalid_request", "title 必须为字符串。", 400)
    title = value.strip()
    if not title:
        raise OntologyServiceError("invalid_request", "title 不能为空白。", 400)
    if len(title) > CHANGE_SET_TITLE_MAX_LENGTH:
        raise OntologyServiceError(
            "invalid_request",
            f"title 长度不能超过 {CHANGE_SET_TITLE_MAX_LENGTH}。",
            400,
        )
    return title


def _normalize_change_set_item(index: int, raw: object) -> dict[str, Any]:
    """形状 + 值级静态校验并归一化一项候选载荷（不触 DB 状态）。

    返回的字典即 propose 落库的规范形态——submit 的指纹与 confirm 的物化都
    消费同一形态，保证「指纹看到的名字」与「物化写入的名字」恒一致。
    """
    where = f"第 {index + 1} 项"
    if not isinstance(raw, dict):
        raise OntologyServiceError("payload_schema", f"{where}必须为对象。", 400)
    action = raw.get("action")
    if not isinstance(action, str) or not action:
        raise OntologyServiceError("payload_schema", f"{where}缺少 action。", 400)
    if action in _CHANGE_SET_DEFERRED_ACTIONS:
        raise OntologyServiceError(
            "payload_schema",
            f"{where} action={action} 本轮未开放"
            "（业务对象候选走既有表单/导入人工路径）。",
            400,
        )
    if action not in _CHANGE_SET_ALLOWED_FIELDS:
        raise OntologyServiceError(
            "payload_schema",
            f"{where} action 未知（允许：{'/'.join(CHANGE_SET_ACTIONS)}）。",
            400,
        )
    unknown = set(raw) - _CHANGE_SET_ALLOWED_FIELDS[action] - {"action"}
    if unknown:
        raise OntologyServiceError(
            "payload_schema",
            f"{where}含未知字段：{'、'.join(sorted(unknown))}。",
            400,
        )
    missing = [
        field
        for field in _CHANGE_SET_REQUIRED_FIELDS[action]
        if raw.get(field) is None
    ]
    if missing:
        raise OntologyServiceError(
            "payload_schema", f"{where}缺少必填字段：{'、'.join(missing)}。", 400
        )

    item: dict[str, Any] = {"action": action}
    if action == "create_term":
        item["term"] = _normalize_name(raw["term"], field="term")
        item["definition"] = _normalize_name(raw["definition"], field="definition")
        item["term_type"] = _normalize_term_type(raw.get("term_type"))
    elif action == "update_term":
        item["term"] = _normalize_name(raw["term"], field="term")
        item["definition"] = _normalize_name(raw["definition"], field="definition")
        if "term_type" in raw and raw.get("term_type") is not None:
            item["term_type"] = _normalize_term_type(raw.get("term_type"))
        if raw.get("new_term") is not None:
            new_name = _normalize_name(raw["new_term"], field="new_term")
            if new_name != item["term"]:
                # 同名视作原行受控修订；改名才是行级取代（superseded）
                item["new_term"] = new_name
    elif action == "merge_terms":
        item["source_term"] = _normalize_name(raw["source_term"], field="source_term")
        item["target_term"] = _normalize_name(raw["target_term"], field="target_term")
        if item["source_term"] == item["target_term"]:
            raise OntologyServiceError(
                "payload_schema", f"{where}source_term 与 target_term 不能相同。", 400
            )
    else:  # register_relation_type
        item["kind"] = _normalize_kind(raw["kind"])
        item["code"] = _normalize_code(raw["code"])
        item["label"] = _normalize_optional_text(
            raw.get("label"), field="label", limit=RELATION_TYPE_LABEL_MAX_LENGTH
        )
        item["description"] = _normalize_optional_text(
            raw.get("description"),
            field="description",
            limit=RELATION_TYPE_DESCRIPTION_MAX_LENGTH,
        )
        item["allowed_source_types"] = _normalize_endpoints(
            raw.get("allowed_source_types"), field="allowed_source_types"
        )
        item["allowed_target_types"] = _normalize_endpoints(
            raw.get("allowed_target_types"), field="allowed_target_types"
        )
    return item


def _summarize_change_set(items: list[dict[str, Any]]) -> str:
    """人读摘要（按载荷首现序聚合动作计数；服务端生成，不信任候选自报）。"""
    counts: dict[str, int] = {}
    for item in items:
        counts[item["action"]] = counts.get(item["action"], 0) + 1
    return " · ".join(
        f"{_ACTION_LABELS[action]} {count}" for action, count in counts.items()
    )


def propose_change_set(
    session: Session,
    *,
    project_id: str,
    actor: User,
    title: object,
    proposed_json: object,
    description: object = None,
    captured_from: str | None = None,
) -> OntologyChangeSet:
    """新建候选变更集（会话内原语，事务归调用方）：只写变更集行本身，**不触
    术语/类型表**（§5 用例 1：confirm 前不物化）。

    captured_from 标记候选来源（如 ``agent_run:<id>``）——仅服务层原语可写
    （AI 通道），HTTP 人工路径不收该字段。
    """
    normalized_title = _normalize_change_set_title(title)
    optional_description = _normalize_optional_text(
        description,
        field="description",
        limit=CHANGE_SET_DESCRIPTION_MAX_LENGTH,
    )
    if not isinstance(proposed_json, list) or not proposed_json:
        raise OntologyServiceError(
            "payload_schema", "proposed_json 必须为非空数组。", 400
        )
    if len(proposed_json) > CHANGE_SET_MAX_ITEMS:
        raise OntologyServiceError(
            "payload_schema",
            f"proposed_json 最多 {CHANGE_SET_MAX_ITEMS} 项（收到 {len(proposed_json)} 项）。",
            400,
        )
    items = [
        _normalize_change_set_item(index, raw)
        for index, raw in enumerate(proposed_json)
    ]
    if captured_from is not None:
        captured_from = _normalize_optional_text(
            captured_from, field="captured_from", limit=120
        )
    row = OntologyChangeSet(
        project_id=project_id,
        title=normalized_title,
        description=optional_description,
        proposed_json=items,
        diff_summary=_summarize_change_set(items),
        status="draft",
        captured_from=captured_from,
        created_by_user_id=actor.id,
    )
    session.add(row)
    session.flush()
    return row


def _term_snapshot(row: OntologyTerm | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row.id,
        "term": row.term,
        "term_type": row.term_type,
        "definition": row.definition,
        "status": row.status,
        "canonical_term_id": row.canonical_term_id,
        "version": row.version,
    }


def _relation_type_snapshot(row: OntologyRelationType | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row.id,
        "kind": row.kind,
        "code": row.code,
        "label": row.label,
        "description": row.description,
        "allowed_source_types": list(row.allowed_source_types or []),
        "allowed_target_types": list(row.allowed_target_types or []),
        "status": row.status,
        "version": row.version,
    }


def _term_by_name(
    session: Session, *, project_id: str, name: str
) -> OntologyTerm | None:
    return session.scalar(
        select(OntologyTerm).where(
            OntologyTerm.project_id == project_id, OntologyTerm.term == name
        )
    )


def _alias_owner_term_id(
    session: Session, *, project_id: str, alias: str
) -> str | None:
    return session.scalar(
        select(OntologyTermAlias.term_id).where(
            OntologyTermAlias.project_id == project_id,
            OntologyTermAlias.alias == alias,
        )
    )


def existing_term_names(
    session: Session, *, project_id: str, names: list[str]
) -> set[str]:
    """返回 names 中已被术语行（任意状态）或别名占用的名字。

    V3 T-O4 导入去重的占位检查：被占用的名字不再提案 create_term（物化期
    会 409 term_exists），空名字单返回空集。
    """
    if not names:
        return set()
    taken = set(
        session.scalars(
            select(OntologyTerm.term).where(
                OntologyTerm.project_id == project_id,
                OntologyTerm.term.in_(names),
            )
        )
    )
    taken.update(
        session.scalars(
            select(OntologyTermAlias.alias).where(
                OntologyTermAlias.project_id == project_id,
                OntologyTermAlias.alias.in_(names),
            )
        )
    )
    return taken


def _change_set_base_descriptor(
    session: Session, *, project_id: str, items: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """逐项采集「受影响面现状」：submit 与 confirm 复核共用同一采集器——
    指纹同时覆盖「既有行被并发改写」与「占位名凭空出现/消失」两类漂移。"""
    descriptor: list[dict[str, Any]] = []
    for item in items:
        action = item["action"]
        entry: dict[str, Any] = {"action": action}
        if action == "create_term":
            entry["term"] = item["term"]
            entry["existing_term"] = _term_snapshot(
                _term_by_name(session, project_id=project_id, name=item["term"])
            )
            entry["alias_owner_term_id"] = _alias_owner_term_id(
                session, project_id=project_id, alias=item["term"]
            )
        elif action == "update_term":
            entry["term"] = item["term"]
            entry["effective_term"] = item.get("new_term", item["term"])
            entry["target"] = _term_snapshot(
                _term_by_name(session, project_id=project_id, name=item["term"])
            )
            if item.get("new_term"):
                entry["new_name_term"] = _term_snapshot(
                    _term_by_name(
                        session, project_id=project_id, name=item["new_term"]
                    )
                )
                entry["new_name_alias_owner_term_id"] = _alias_owner_term_id(
                    session, project_id=project_id, alias=item["new_term"]
                )
        elif action == "merge_terms":
            entry["source_term"] = item["source_term"]
            entry["target_term"] = item["target_term"]
            entry["source"] = _term_snapshot(
                _term_by_name(
                    session, project_id=project_id, name=item["source_term"]
                )
            )
            entry["target"] = _term_snapshot(
                _term_by_name(
                    session, project_id=project_id, name=item["target_term"]
                )
            )
        else:  # register_relation_type（变更集只登记项目内类型）
            entry["kind"] = item["kind"]
            entry["code"] = item["code"]
            project_row = session.scalar(
                select(OntologyRelationType).where(
                    OntologyRelationType.project_id == project_id,
                    OntologyRelationType.kind == item["kind"],
                    OntologyRelationType.code == item["code"],
                )
            )
            global_row = session.scalar(
                select(OntologyRelationType).where(
                    OntologyRelationType.project_id.is_(None),
                    OntologyRelationType.kind == item["kind"],
                    OntologyRelationType.code == item["code"],
                )
            )
            entry["project_row"] = _relation_type_snapshot(project_row)
            entry["global_row"] = _relation_type_snapshot(global_row)
        descriptor.append(entry)
    return descriptor


def _base_snapshot_sha256(descriptor: list[dict[str, Any]]) -> str:
    payload = json.dumps(
        descriptor, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _lock_change_set(session: Session, row: OntologyChangeSet) -> OntologyChangeSet:
    """CR-021：状态翻转前以行锁重读（for_update + populate_existing）——两拍板人
    并发 confirm、confirm/reject 互斥、双 submit 都在此串行化；锁在手后读到的
    必是已提交真值，「先读后写」竞态（双物化/翻已物化行/重复 version）从根闭合。"""
    return session.execute(
        select(OntologyChangeSet)
        .where(OntologyChangeSet.id == row.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one()


def submit_change_set(
    session: Session, *, row: OntologyChangeSet, actor: User
) -> OntologyChangeSet:
    """draft → in_review：对受影响行快照取 base 指纹（并发防护锚点）。"""
    row = _lock_change_set(session, row)
    if row.status != "draft":
        raise OntologyServiceError(
            "invalid_transition", f"状态 {row.status} 不能提交评审。", 409
        )
    descriptor = _change_set_base_descriptor(
        session, project_id=row.project_id, items=list(row.proposed_json or [])
    )
    row.base_snapshot_sha256 = _base_snapshot_sha256(descriptor)
    row.status = "in_review"
    row.submitted_by_user_id = actor.id
    row.submitted_at = datetime.now(UTC)
    row.version += 1
    session.flush()
    return row


def _materialize_create_term(
    session: Session, *, project_id: str, item: dict[str, Any], actor: User
) -> dict[str, Any]:
    row = create_term(
        session,
        project_id=project_id,
        term=item["term"],
        definition=item["definition"],
        term_type=item.get("term_type"),
        actor=actor,
        initial_status="confirmed",
    )
    return {"action": "create_term", "status": "created", "term_id": row.id, "term": row.term}


def _materialize_update_term(
    session: Session, *, project_id: str, item: dict[str, Any], actor: User
) -> dict[str, Any]:
    """修订术语：同名 = 原行受控改写（仅此一条路，旧定义随事件留档）；
    改名 = 新行 confirmed + 原行 superseded 指 canonical + 原名转别名。"""
    target = _term_by_name(session, project_id=project_id, name=item["term"])
    if target is None:
        raise OntologyServiceError("term_not_found", "术语不存在。", 404)
    if target.status in ("merged", "superseded"):
        raise OntologyServiceError(
            "invalid_transition",
            f"术语「{target.term}」已处于终态 {target.status}，不能修订。",
            409,
        )
    before = {"definition": target.definition, "term_type": target.term_type}
    if item.get("new_term"):
        replacement = create_term(
            session,
            project_id=project_id,
            term=item["new_term"],
            definition=item["definition"],
            term_type=item.get("term_type", target.term_type),
            actor=actor,
            initial_status="confirmed",
        )
        target.status = "superseded"
        target.canonical_term_id = replacement.id
        target.version += 1
        # 原名转写为新一行的别名（合并保留来源同一纪律）
        _ensure_alias(
            session,
            project_id=project_id,
            term_id=replacement.id,
            alias=target.term,
            actor=actor,
            exclude_term_id=target.id,
        )
        session.flush()
        return {
            "action": "update_term",
            "status": "superseded",
            "old_term_id": target.id,
            "old_term": target.term,
            "new_term_id": replacement.id,
            "new_term": replacement.term,
        }
    target.definition = item["definition"]
    if "term_type" in item:
        target.term_type = item["term_type"]
    target.version += 1
    session.flush()
    return {
        "action": "update_term",
        "status": "updated",
        "term_id": target.id,
        "term": target.term,
        "before": before,
        "after": {"definition": target.definition, "term_type": target.term_type},
    }


def _materialize_merge_terms(
    session: Session, *, project_id: str, item: dict[str, Any], actor: User
) -> dict[str, Any]:
    source = _term_by_name(session, project_id=project_id, name=item["source_term"])
    target = _term_by_name(session, project_id=project_id, name=item["target_term"])
    if source is None or target is None:
        raise OntologyServiceError("term_not_found", "术语不存在。", 404)
    outcome = merge_terms(
        session, source_id=source.id, target_id=target.id, actor=actor
    )
    return {
        "action": "merge_terms",
        "status": "merged",
        "source_term_id": source.id,
        "target_term_id": target.id,
        "merged_term": outcome["source"]["term"],
        "canonical_term": outcome["target"]["term"],
    }


def _materialize_register_relation_type(
    session: Session, *, project_id: str, item: dict[str, Any], actor: User
) -> dict[str, Any]:
    # 变更集只登记项目内类型；全局登记走 admin 人工路由（lesson 15 权限口径）
    row = register_relation_type(
        session,
        project_id=project_id,
        kind=item["kind"],
        code=item["code"],
        label=item.get("label"),
        description=item.get("description"),
        allowed_source_types=item.get("allowed_source_types"),
        allowed_target_types=item.get("allowed_target_types"),
        actor=actor,
    )
    return {
        "action": "register_relation_type",
        "status": "registered",
        "relation_type_id": row.id,
        "kind": row.kind,
        "code": row.code,
    }


def confirm_change_set(
    session: Session, *, row: OntologyChangeSet, actor: User
) -> dict[str, Any]:
    """in_review → confirmed（会话内，事务归调用方）：①复核 base 指纹
    （并发漂移 409 base_conflict，不物化）②单事务逐项物化（全成全败，任一项
    失败整体回滚并以 change_set_item_failed 点名）③翻转状态 ④落
    `ontology_change_set_confirmed` 事件携带逐项结果。

    验收分离（P0-5 纪律）：拍板人 ≠ 提交人。
    """
    row = _lock_change_set(session, row)
    if row.status != "in_review":
        raise OntologyServiceError(
            "not_in_review", f"状态 {row.status} 不能确认（仅 in_review 可确认）。", 409
        )
    if row.submitted_by_user_id is not None and row.submitted_by_user_id == actor.id:
        raise OntologyServiceError(
            "change_set_decider_conflict",
            "验收分离：变更集拍板人不能是提交人。",
            403,
        )
    items = list(row.proposed_json or [])
    descriptor = _change_set_base_descriptor(
        session, project_id=row.project_id, items=items
    )
    digest = _base_snapshot_sha256(descriptor)
    if row.base_snapshot_sha256 is None or digest != row.base_snapshot_sha256:
        raise OntologyServiceError(
            "base_conflict",
            "受影响的本体在提交后被并发修改（base 指纹不符），"
            "请重新提交变更集后再拍板。",
            409,
        )

    materializers = {
        "create_term": _materialize_create_term,
        "update_term": _materialize_update_term,
        "merge_terms": _materialize_merge_terms,
        "register_relation_type": _materialize_register_relation_type,
    }
    results: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        try:
            results.append(
                materializers[item["action"]](
                    session, project_id=row.project_id, item=item, actor=actor
                )
            )
        except OntologyServiceError as error:
            raise OntologyServiceError(
                "change_set_item_failed",
                f"第 {index + 1} 项（{item['action']}）物化失败：{error.message}",
                error.status,
            ) from None

    row.status = "confirmed"
    row.confirmed_by_user_id = actor.id
    row.confirmed_at = datetime.now(UTC)
    row.version += 1
    session.flush()
    record_event(
        session,
        actor,
        "ontology_change_set_confirmed",
        row,
        {"results": results, "item_count": len(results)},
    )
    return {"results": results}


def reject_change_set(
    session: Session, *, row: OntologyChangeSet, actor: User, reason: object
) -> OntologyChangeSet:
    """draft/in_review → rejected（只改状态留 reason）。拍板否决同样受
    验收分离约束：拍板人 ≠ 提交人。"""
    row = _lock_change_set(session, row)
    if row.status not in ("draft", "in_review"):
        raise OntologyServiceError(
            "invalid_transition", f"状态 {row.status} 不能否决。", 409
        )
    if row.submitted_by_user_id is not None and row.submitted_by_user_id == actor.id:
        raise OntologyServiceError(
            "change_set_decider_conflict",
            "验收分离：变更集拍板人不能是提交人。",
            403,
        )
    reason_text = _normalize_optional_text(
        reason,
        field="reason",
        limit=CHANGE_SET_REJECTED_REASON_MAX_LENGTH,
    )
    if reason_text is None:
        raise OntologyServiceError("invalid_request", "reason 不能为空白。", 400)
    row.status = "rejected"
    row.rejected_reason = reason_text
    row.version += 1
    session.flush()
    return row


def serialize_change_set(row: OntologyChangeSet) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "title": row.title,
        "description": row.description,
        "proposed_json": list(row.proposed_json or []),
        "diff_summary": row.diff_summary,
        "status": row.status,
        "base_snapshot_sha256": row.base_snapshot_sha256,
        "captured_from": row.captured_from,
        "submitted_by_user_id": row.submitted_by_user_id,
        "submitted_at": row.submitted_at.isoformat() if row.submitted_at else None,
        "confirmed_by_user_id": row.confirmed_by_user_id,
        "confirmed_at": row.confirmed_at.isoformat() if row.confirmed_at else None,
        "rejected_reason": row.rejected_reason,
        "version": row.version,
        "created_by_user_id": row.created_by_user_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


_FACT_TYPE_TO_TERM_TYPE = {
    "metric": "metric",
    "data_object": "attribute",
}
# 其余 fact_type（process/role/system/rule/constraint/pain_point/decision/open_question）→ entity

def generate_discovery_candidates(
    *, actor: User, project_id: str, extraction_id: str
) -> dict[str, Any]:
    """V3.1 P0-2：从已接受访谈事实生成本体术语候选（can_manage）。

    只消费 ``review_status=accepted`` 的 business_facts（任务书：AI 只能创建
    候选、候选必须引用已确认事实）；按 subject 聚组为 create_term 条目走
    既有 change-set 提案→提交→确认管线（captured_from=discovery:<id>）；
    名字域（术语∪别名）已占用的候选跳过。幂等：同抽取至多一个活跃
    （draft/in_review）候选变更集，重复调用返回既有行。
    """
    from fde_api.discovery.models import BusinessFact, DiscoveryExtraction  # 延迟导入防环

    with db.session() as session, session.begin():
        project = _load_project(session, actor, project_id, manage=True)
        extraction = session.get(DiscoveryExtraction, extraction_id)
        if extraction is None or extraction.project_id != project.id:
            raise OntologyServiceError(
                "extraction_not_found", "抽取不存在或不属于该项目。", 404
            )
        if extraction.status != "review_required":
            raise OntologyServiceError(
                "extraction_not_ready",
                "抽取尚未完成（仅 review_required 状态可生成候选）。",
                409,
            )
        captured_from = f"discovery:{extraction.id}"
        existing = session.scalar(
            select(OntologyChangeSet).where(
                OntologyChangeSet.project_id == project.id,
                OntologyChangeSet.captured_from == captured_from,
                OntologyChangeSet.status.in_(("draft", "in_review")),
            )
        )
        if existing is not None:
            return {
                "change_set": serialize_change_set(existing),
                "created": False,
                "skipped": [],
                "cross_project_conflicts": [],
            }
        facts = session.scalars(
            select(BusinessFact)
            .where(
                BusinessFact.extraction_id == extraction.id,
                BusinessFact.review_status == "accepted",
            )
            .order_by(BusinessFact.created_at, BusinessFact.id)
        ).all()
        if not facts:
            raise OntologyServiceError(
                "no_accepted_facts",
                "该抽取尚无已接受的事实：先在事实清单完成审阅再生成候选。",
                409,
            )
        grouped: dict[str, list[tuple[str, str]]] = {}
        for fact in facts:
            value = fact.object_value
            summary_value = (
                value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            )
            grouped.setdefault(fact.subject, []).append(
                (fact.fact_type, f"{fact.predicate}：{summary_value}")
            )
        occupied = _occupied_term_names(session, project_id=project.id)
        items: list[dict[str, Any]] = []
        skipped: list[dict[str, str]] = []
        # 组序取 subject 字典序——facts 的 (created_at, id) 在单事务插入时
        # created_at 全同（事务时间戳）而 id=uuid4 无内在序，组序是抽签
        # （#209 CI 实红：本地插入序 vs CI 字典序翻转）；按字典序迭代使
        # 候选条目与 skipped 双列表同输入恒同序（变更集指纹跨环境稳定）。
        for subject in sorted(grouped):
            typed_summaries = grouped[subject]
            if subject in occupied:
                skipped.append({"term": subject, "reason": "同名术语或别名已存在"})
                continue
            if len(subject) > TERM_MAX_LENGTH:
                skipped.append({"term": subject, "reason": f"名称超过 {TERM_MAX_LENGTH} 字"})
                continue
            # 组内定义取字典序最小摘要——事实行 id 为 uuid4 无内在顺序，
            # 取「最小」保证同输入恒同输出（确定性候选，变更集指纹稳定）。
            definition = min(summary for _, summary in typed_summaries)[:TERM_MAX_LENGTH]
            first_type = sorted({fact_type for fact_type, _ in typed_summaries})[0]
            items.append({
                "action": "create_term",
                "term": subject,
                "definition": definition,
                "term_type": _FACT_TYPE_TO_TERM_TYPE.get(first_type, "entity"),
            })
            occupied.add(subject)
        if not items:
            raise OntologyServiceError(
                "no_candidates",
                "已接受事实未能形成新术语候选（全部已存在或名称超长）。",
                409,
            )
        items = items[:CHANGE_SET_MAX_ITEMS]
        row = propose_change_set(
            session,
            project_id=project.id,
            actor=actor,
            title="访谈事实术语候选（discovery）",
            proposed_json=items,
            description=f"来源抽取 {extraction.id}；仅含人工已接受事实。",
            captured_from=captured_from,
        )
        conflicts = cross_project_name_conflicts(
            session, project_id=project.id, names=[item["term"] for item in items]
        )
        return {
            "change_set": serialize_change_set(row),
            "created": True,
            "skipped": skipped,
            "cross_project_conflicts": conflicts,
        }


def list_discovery_candidates(
    *, actor: User, project_id: str, limit: int = 50
) -> dict[str, Any]:
    """发现域候选变更集清单（can_view）：captured_from=discovery:% 投影。"""
    with db.session() as session, session.begin():
        project = _load_project(session, actor, project_id, manage=False)
        rows = session.scalars(
            select(OntologyChangeSet)
            .where(
                OntologyChangeSet.project_id == project.id,
                OntologyChangeSet.captured_from.is_not(None),
                OntologyChangeSet.captured_from.like("discovery:%"),
            )
            .order_by(OntologyChangeSet.created_at.desc())
            .limit(limit)
        ).all()
        return {"items": [serialize_change_set(row) for row in rows], "limit": limit}


def list_project_terms(
    *, actor: User, project_id: str, q: str | None = None
) -> dict[str, Any]:
    """术语只读面（§4：GET /ontology/terms?q=）：q 大小写不敏感地匹配规范名
    或别名（别名命中返回属主术语行）。can_view。"""
    with db.session() as session:
        project = _load_project(session, actor, project_id, manage=False)
        rows = list(
            session.scalars(
                select(OntologyTerm)
                .where(OntologyTerm.project_id == project.id)
                .order_by(OntologyTerm.term.asc(), OntologyTerm.id.asc())
            )
        )
        aliases_by_term: dict[str, list[str]] = {}
        for alias_row in session.scalars(
            select(OntologyTermAlias).where(
                OntologyTermAlias.project_id == project.id
            )
        ):
            aliases_by_term.setdefault(alias_row.term_id, []).append(alias_row.alias)
        needle = q.strip().lower() if isinstance(q, str) and q.strip() else None
        items = []
        for row in rows:
            names = [row.term, *aliases_by_term.get(row.id, [])]
            if needle is not None and not any(needle in name.lower() for name in names):
                continue
            data = serialize_term(row)
            data["aliases"] = sorted(aliases_by_term.get(row.id, []))
            items.append(data)
        return {"items": items}


# ---------------------------------------------------------------------------
# V3 T-I1：本体变更影响分析（设计 §5 用例 6；验收 O-6）
# ---------------------------------------------------------------------------


def _term_lineage_rows(
    session: Session, *, row: OntologyTerm
) -> list[OntologyTerm]:
    """血缘闭包：请求行沿 canonical 链到根，再收全部并入该根的行。

    merge_terms 保证链一跳化（曾并入 source 的行随合并重指 target），这里仍
    防御性沿链走到底。返回首元素恒为根（canonical_term_id 为 None 的存活行；
    请求行自身是 merged 行时根即其 canonical），其余按 (term, id) 排序——
    输出确定性。
    """
    root = row
    visited = {root.id}
    while root.status == "merged" and root.canonical_term_id:
        nxt = session.get(OntologyTerm, root.canonical_term_id)
        if nxt is None or nxt.project_id != row.project_id or nxt.id in visited:
            break
        root = nxt
        visited.add(root.id)
    # 自根重新收下展（请求行若是 merged 行必在其内——它指向根或链上某行）
    seen = {root.id}
    lineage = [root]
    frontier = [root]
    while frontier:
        current = frontier.pop()
        for child in session.scalars(
            select(OntologyTerm).where(
                OntologyTerm.project_id == row.project_id,
                OntologyTerm.canonical_term_id == current.id,
                OntologyTerm.status == "merged",
            )
        ):
            if child.id not in seen:
                seen.add(child.id)
                lineage.append(child)
                frontier.append(child)
    return [lineage[0], *sorted(lineage[1:], key=lambda item: (item.term, item.id))]


def impact_of_term(
    session: Session, *, project_id: str, term_id: str
) -> dict[str, Any]:
    """影响分析（设计 §5 用例 6）：给定术语，列出引用它的研究客体/邻接边/表单。

    引用合同 = 名字域纽带（模块 docstring）：subject.name 精确命中生效名字域
    即引用该概念——纽带是唯一性不是相似度，子串/大小写变体不算命中。
    对并入行发起查询 = 查其存活概念的影响面（请求行原样返回，血缘解析到根）。
    """
    row = session.get(OntologyTerm, term_id)
    if row is None or row.project_id != project_id:
        raise OntologyServiceError("term_not_found", "术语不存在。", 404)

    lineage = _term_lineage_rows(session, row=row)
    # 生效名字域：只有根的规范名是 term 绑定——并入/被取代行的规范名是
    # 历史名，经合并转写的别名（归保留行）或行自身（转写被占位防御跳过时的
    # 兜底）按 alias 绑定解析。setdefault 全程防御（UNIQUE 语义下同名不可共存）。
    names: dict[str, tuple[str, str]] = {}
    names.setdefault(lineage[0].term, (lineage[0].id, "term"))
    for alias_row in session.scalars(
        select(OntologyTermAlias).where(
            OntologyTermAlias.project_id == project_id,
            OntologyTermAlias.term_id.in_([item.id for item in lineage]),
        )
    ):
        names.setdefault(alias_row.alias, (alias_row.term_id, "alias"))
    for term_row in lineage[1:]:
        names.setdefault(term_row.term, (term_row.id, "alias"))

    subjects = list(
        session.scalars(
            select(ProjectResearchSubject)
            .where(
                ProjectResearchSubject.project_id == project_id,
                ProjectResearchSubject.name.in_(names),
            )
            .order_by(
                ProjectResearchSubject.name.asc(), ProjectResearchSubject.id.asc()
            )
        )
    )
    subject_items = []
    subject_names = {subject.id: subject.name for subject in subjects}
    for subject in subjects:
        owner_id, via = names[subject.name]
        subject_items.append(
            {
                "id": subject.id,
                "subject_key": subject.subject_key,
                "name": subject.name,
                "subject_type": subject.subject_type,
                "status": subject.status,
                "merged_into_subject_id": subject.merged_into_subject_id,
                "matched_via": via,
                "matched_term_id": owner_id,
            }
        )

    subject_ids = list(subject_names)
    link_items: list[dict[str, Any]] = []
    if subject_ids:
        link_rows = list(
            session.scalars(
                select(ProjectResearchSubjectLink)
                .where(
                    ProjectResearchSubjectLink.project_id == project_id,
                    or_(
                        ProjectResearchSubjectLink.source_subject_id.in_(subject_ids),
                        ProjectResearchSubjectLink.target_subject_id.in_(subject_ids),
                    ),
                )
                .order_by(
                    ProjectResearchSubjectLink.link_type.asc(),
                    ProjectResearchSubjectLink.id.asc(),
                )
            )
        )
        endpoint_ids = {
            endpoint_id
            for link in link_rows
            for endpoint_id in (link.source_subject_id, link.target_subject_id)
        }
        endpoint_names: dict[str, str] = {
            endpoint_id: endpoint_name
            for endpoint_id, endpoint_name in session.execute(
                select(
                    ProjectResearchSubject.id, ProjectResearchSubject.name
                ).where(ProjectResearchSubject.id.in_(endpoint_ids))
            ).all()
        }
        for link in link_rows:
            link_items.append(
                {
                    "id": link.id,
                    "link_type": link.link_type,
                    "source_subject_id": link.source_subject_id,
                    "source_subject_name": endpoint_names.get(
                        link.source_subject_id
                    ),
                    "target_subject_id": link.target_subject_id,
                    "target_subject_name": endpoint_names.get(
                        link.target_subject_id
                    ),
                }
            )

    form_items: list[dict[str, Any]] = []
    if subject_ids:
        form_rows = list(
            session.scalars(
                select(ProjectResearchForm)
                .where(
                    ProjectResearchForm.project_id == project_id,
                    ProjectResearchForm.subject_id.in_(subject_ids),
                )
                .order_by(
                    ProjectResearchForm.form_key.asc(), ProjectResearchForm.id.asc()
                )
            )
        )
        revision_ids = [
            form.current_revision_id
            for form in form_rows
            if form.current_revision_id is not None
        ]
        status_by_revision: dict[str, str] = (
            {
                revision_id: revision_status
                for revision_id, revision_status in session.execute(
                    select(
                        ProjectResearchFormRevision.id,
                        ProjectResearchFormRevision.status,
                    ).where(ProjectResearchFormRevision.id.in_(revision_ids))
                ).all()
            }
            if revision_ids
            else {}
        )
        for form in form_rows:
            form_items.append(
                {
                    "id": form.id,
                    "form_key": form.form_key,
                    "name": form.name,
                    "subject_id": form.subject_id,
                    "subject_name": subject_names.get(form.subject_id),
                    "current_revision_status": (
                        status_by_revision.get(form.current_revision_id)
                        if form.current_revision_id is not None
                        else None
                    ),
                }
            )

    return {
        "term": serialize_term(row),
        "resolved": {
            "canonical_term_id": lineage[0].id,
            "lineage_term_ids": [item.id for item in lineage],
            "names": {
                name: {"term_id": owner_id, "via": via}
                for name, (owner_id, via) in sorted(names.items())
            },
        },
        "subjects": subject_items,
        "links": link_items,
        "forms": form_items,
        "counts": {
            "subjects": len(subject_items),
            "links": len(link_items),
            "forms": len(form_items),
        },
    }


def impact_project_term(
    *, actor: User, project_id: str, term_id: str
) -> dict[str, Any]:
    """影响分析只读面（can_view）：GET /ontology/terms/<id>/impact。

    人工评审读面——有意不进 api_catalog（沿 T-O3 纪律：本体治理面 AI 不可
    直达；桌面 T-UI1 GlossaryPage 是预期消费方）。
    """
    with db.session() as session:
        project = _load_project(session, actor, project_id, manage=False)
        return impact_of_term(session, project_id=project.id, term_id=term_id)


# ---------------------------------------------------------------------------
# HTTP 面（人工路径：有意不进 api_catalog）
# ---------------------------------------------------------------------------


def _load_project(
    session: Session, actor: User, project_id: str, *, manage: bool
) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise OntologyServiceError("project_not_found", "项目不存在或已被删除。", 404)
    access = project_access(actor, project)
    if not (access.can_manage if manage else access.can_view):
        raise OntologyServiceError("forbidden", "你没有该项目的本体操作权限。", 403)
    return project


def list_project_relation_types(
    *, actor: User, project_id: str, kind: str | None = None
) -> dict[str, Any]:
    """列出对项目生效的类型（can_view）：全局 ∪ 项目内，项目内遮蔽同名全局。"""
    kind_filter = _normalize_kind(kind) if kind else None
    with db.session() as session:
        project = _load_project(session, actor, project_id, manage=False)
        rows = list_relation_types(session, project_id=project.id)
    if kind_filter is not None:
        rows = [row for row in rows if row.kind == kind_filter]
    return {"items": [serialize_relation_type(row) for row in rows]}


def list_global_relation_types(*, kind: str | None = None) -> dict[str, Any]:
    """列出全局注册的类型行（project_id 为空；require_auth 只读）。

    V3 T-O2c（CR-032 偏差清偿）：全局类型此前只能经项目内只读面
    （GET /projects/<id>/ontology/relation-types，全局 ∪ 项目内合并）消费，
    无项目上下文的消费方（行业模板/调研定义编辑器）拉不到注册类型选项。
    本面**只收全局行**——项目内类型只对本项目生效，进全局模板会在
    其他项目实例化时落空（usable_subject_type_codes 的项目合并面管不着
    定义作者）；值域权威仍在服务端写闸门，此处只提供选项。全状态返回
    （draft/active/retired 同项目面口径），消费方自行过滤 active。
    """
    kind_filter = _normalize_kind(kind) if kind else None
    with db.session() as session:
        rows = session.scalars(
            select(OntologyRelationType)
            .where(OntologyRelationType.project_id.is_(None))
            .order_by(
                OntologyRelationType.kind.asc(),
                OntologyRelationType.code.asc(),
                OntologyRelationType.id.asc(),
            )
        ).all()
    if kind_filter is not None:
        rows = [row for row in rows if row.kind == kind_filter]
    return {"items": [serialize_relation_type(row) for row in rows]}


def create_relation_type(
    *, actor: User, project_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """登记类型（can_manage；scope=global 另需 admin）。人工路径——不进 api_catalog。"""
    if set(payload) - _REGISTER_TYPE_FIELDS:
        raise OntologyServiceError("invalid_request", "请求字段无效。", 400)
    scope = payload.get("scope") or "project"
    if scope not in ("project", "global"):
        raise OntologyServiceError("invalid_request", "scope 仅可为 project/global。", 400)
    with db.session() as session, session.begin():
        project = _load_project(session, actor, project_id, manage=True)
        if scope == "global" and actor.role != "admin":
            raise OntologyServiceError(
                "forbidden", "只有管理员可以登记全局类型。", 403
            )
        row = register_relation_type(
            session,
            project_id=None if scope == "global" else project.id,
            kind=payload.get("kind"),
            code=payload.get("code"),
            label=payload.get("label"),
            description=payload.get("description"),
            allowed_source_types=payload.get("allowed_source_types"),
            allowed_target_types=payload.get("allowed_target_types"),
            actor=actor,
        )
        record_event(
            session,
            actor,
            "ontology_relation_type_registered",
            row,
            {
                "kind": row.kind,
                "code": row.code,
                "scope": scope,
                "allowed_source_types": list(row.allowed_source_types or []),
                "allowed_target_types": list(row.allowed_target_types or []),
            },
        )
        return {"relation_type": serialize_relation_type(row), "created": True}


def retire_project_relation_type(
    *, actor: User, project_id: str, relation_type_id: str
) -> dict[str, Any]:
    """停用类型（can_manage）：禁新边、存量边只读。

    全局类型（project_id 为空）对所有项目生效，只有管理员能停用——否则任一
    项目管理员都能影响别的项目。
    """
    with db.session() as session, session.begin():
        project = _load_project(session, actor, project_id, manage=True)
        row = session.get(OntologyRelationType, relation_type_id)
        if row is None:
            raise OntologyServiceError("relation_type_not_found", "类型不存在。", 404)
        if row.project_id is None:
            if actor.role != "admin":
                raise OntologyServiceError(
                    "forbidden", "只有管理员可以停用全局类型。", 403
                )
        elif row.project_id != project.id:
            raise OntologyServiceError(
                "relation_type_not_found", "类型不存在。", 404
            )
        retired = retire_relation_type(
            session, relation_type_id=relation_type_id, actor=actor
        )
        record_event(
            session,
            actor,
            "ontology_relation_type_retired",
            retired,
            {"kind": retired.kind, "code": retired.code},
        )
        return {"relation_type": serialize_relation_type(retired)}


# ---------------------------------------------------------------------------
# V3 T-O3：变更集 HTTP 面（人工路径——AI 候选经服务层原语，不进 api_catalog）
# ---------------------------------------------------------------------------

# propose 人工载荷字段；captured_from 是 AI 通道专用，人工路径显式拒收
_CHANGE_SET_PAYLOAD_FIELDS = {"title", "description", "proposed_json"}
_REJECT_PAYLOAD_FIELDS = {"reason"}


def _load_change_set(
    session: Session, project: Project, change_set_id: str
) -> OntologyChangeSet:
    row = session.get(OntologyChangeSet, change_set_id)
    if row is None or row.project_id != project.id:
        raise OntologyServiceError("change_set_not_found", "变更集不存在。", 404)
    return row


def propose_project_change_set(
    *, actor: User, project_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """提出候选变更集（can_manage）→ draft：只写变更集行，confirm 前不物化。"""
    if set(payload) - _CHANGE_SET_PAYLOAD_FIELDS:
        raise OntologyServiceError("invalid_request", "请求字段无效。", 400)
    if "captured_from" in payload:
        raise OntologyServiceError(
            "invalid_request", "captured_from 仅限 AI 候选通道，人工路径不可指定。", 400
        )
    if not isinstance(payload.get("proposed_json"), list):
        raise OntologyServiceError(
            "payload_schema", "proposed_json 必须为数组。", 400
        )
    with db.session() as session, session.begin():
        project = _load_project(session, actor, project_id, manage=True)
        row = propose_change_set(
            session,
            project_id=project.id,
            actor=actor,
            title=payload.get("title"),
            proposed_json=payload["proposed_json"],
            description=payload.get("description"),
        )
        # 不落 OperationEvent：变更集行本身即审计记录（设计只强制 confirm 事件）
        return {"change_set": serialize_change_set(row)}


def submit_project_change_set(
    *, actor: User, project_id: str, change_set_id: str
) -> dict[str, Any]:
    """draft → in_review（can_manage）：计算 base 指纹，进入评审。"""
    with db.session() as session, session.begin():
        project = _load_project(session, actor, project_id, manage=True)
        row = _load_change_set(session, project, change_set_id)
        submitted = submit_change_set(session, row=row, actor=actor)
        return {"change_set": serialize_change_set(submitted)}


def confirm_project_change_set(
    *, actor: User, project_id: str, change_set_id: str
) -> dict[str, Any]:
    """拍板确认（can_manage，且 ≠ 提交人）：指纹复核 + 单事务逐项物化。"""
    with db.session() as session, session.begin():
        project = _load_project(session, actor, project_id, manage=True)
        row = _load_change_set(session, project, change_set_id)
        outcome = confirm_change_set(session, row=row, actor=actor)
        return {
            "change_set": serialize_change_set(row),
            "results": outcome["results"],
        }


def reject_project_change_set(
    *, actor: User, project_id: str, change_set_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """否决（can_manage，且 ≠ 提交人）：只改状态留 reason。"""
    if set(payload) - _REJECT_PAYLOAD_FIELDS:
        raise OntologyServiceError("invalid_request", "请求字段无效。", 400)
    with db.session() as session, session.begin():
        project = _load_project(session, actor, project_id, manage=True)
        row = _load_change_set(session, project, change_set_id)
        rejected = reject_change_set(
            session, row=row, actor=actor, reason=payload.get("reason")
        )
        return {"change_set": serialize_change_set(rejected)}


def _normalize_change_set_status(value: object) -> str:
    if not isinstance(value, str) or value not in CHANGE_SET_STATUSES:
        raise OntologyServiceError(
            "invalid_request",
            f"status 仅可为 {'/'.join(CHANGE_SET_STATUSES)}。",
            400,
        )
    return value


def list_project_change_sets(
    *, actor: User, project_id: str, status: str | None = None
) -> dict[str, Any]:
    """变更集列表（can_view）：?status= 过滤，新者在前。"""
    status_filter = _normalize_change_set_status(status) if status else None
    with db.session() as session:
        project = _load_project(session, actor, project_id, manage=False)
        query = (
            select(OntologyChangeSet)
            .where(OntologyChangeSet.project_id == project.id)
            .order_by(
                OntologyChangeSet.created_at.desc(), OntologyChangeSet.id.desc()
            )
        )
        if status_filter is not None:
            query = query.where(OntologyChangeSet.status == status_filter)
        rows = list(session.scalars(query))
        return {"items": [serialize_change_set(row) for row in rows]}


def get_project_change_set(
    *, actor: User, project_id: str, change_set_id: str
) -> dict[str, Any]:
    """变更集详情（can_view）：diff 评审读 proposed_json 与指纹。"""
    with db.session() as session:
        project = _load_project(session, actor, project_id, manage=False)
        row = _load_change_set(session, project, change_set_id)
        return {"change_set": serialize_change_set(row)}
