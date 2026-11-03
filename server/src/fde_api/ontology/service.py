"""术语生命周期原语（V3 T-O1）：create / confirm / merge（合并保留来源）。

零路由（沿 T-W1 先例）：术语的 REST 面（只读 GET terms 与 change-set 变更面）
随 T-O3 的 routes.py 一并开——设计 §4 里术语唯一公开路径是只读 GET，写路径
一律经 change_sets propose→confirm（AI 候选永不直接写表，沿 guidance
adopt→confirm 样板），本文件的函数就是 confirm 事务里逐项物化的原语。

不变式（§5 用例 3/4）：
- confirmed 后定义不可原地改——服务层不提供任何 definition 编辑路径，修订走
  change_set 产生新版本行（T-O3）。
- 合并保留来源——merge_terms 把被并术语的规范名转写为保留行的别名并落逐项
  OperationEvent；被并行的既有别名不动（别名→merged 行→canonical 链可解析，
  不可变优先）。同项目「一个名字至多一个概念」由 create/别名写入共同把守。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from fde_api.auth.models import User
from fde_api.ontology.models import (
    TERM_TYPES,
    OntologyTerm,
    OntologyTermAlias,
)
from fde_api.projects.events import record_event

TERM_MAX_LENGTH = 120

# 物化原语允许的落库状态：T-O3 change-set confirm 按载荷逐项直落 confirmed；
# 导入/人工新建默认 draft。
_INITIAL_STATUSES = ("draft", "confirmed")


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
