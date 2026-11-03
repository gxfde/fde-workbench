"""术语生命周期原语（V3 T-O1）与关系类型注册原语（V3 T-O2）。

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

不变式（§5 用例 3/4/7）：
- confirmed 后定义不可原地改——服务层不提供任何 definition 编辑路径，修订走
  change_set 产生新版本行（T-O3）。
- 合并保留来源——merge_terms 把被并术语的规范名转写为保留行的别名并落逐项
  OperationEvent；被并行的既有别名不动（别名→merged 行→canonical 链可解析，
  不可变优先）。同项目「一个名字至多一个概念」由 create/别名写入共同把守。
- retired 关系类型禁新边、存量边只读——retire 只改注册表状态，不动既有边行。
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from fde_api.auth.models import User
from fde_api.extensions import db
from fde_api.ontology.models import (
    RELATION_TYPE_KINDS,
    RELATION_TYPE_STATUSES,
    TERM_TYPES,
    OntologyRelationType,
    OntologyTerm,
    OntologyTermAlias,
)
from fde_api.projects.events import record_event
from fde_api.projects.permissions import project_access
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
        raise OntologyServiceError("forbidden", "你没有该项目的类型注册表操作权限。", 403)
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
