"""M5-WP3③：Glossary 单向晋升 + ``promoted_readonly`` 只读投影（改进单 4）。

职责（工作令 §3 WP3 条 3）：把项目已确认术语晋升进模板包锚点
（``OntologyTerm.promoted_readonly``，WP2 迁移 ``b2e8d4c6a9f1`` 已落锚点列）
并**单向不可逆**——晋升后术语成为模板包只读投影，任何内容改写路径在
flush 前响亮失败。

锁的落位（D30 架构纪律：不触碰 ``ontology/service.py`` 2102 行守卫）：
术语修订唯一人工路径 = change-set ``update_term``/``merge_terms`` 动物化
（confirm 全成全败事务）——本模块在 ORM 层（``before_update`` 事件，WP2
GateEvaluationReceipt 守卫同款范式）对**已晋升行**的内容列改写抛
``RuntimeError``，service.confirm 的物化 UPDATE 同样被击穿并随事务整体回滚
（全成全败语义 ⇒ 已晋升术语在物化层天然不可变，无需 service 零侵改）。

单向性：``False→True`` 转换（晋升动作本身 + ``promoted_at`` 首写）放行；
已晋升行（库值 True）的内容列（term/definition/term_type/canonical_term_id/
status）改写一律拒绝——status 降级绕道编辑同样在锁内。项目删除走库级
CASCADE 不经 ORM 事件（WP2 回执守卫同款口径）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from fde_api.ontology.models import OntologyTerm
from fde_api.workbench.models import Project

# M5-WP3⑦（party 评审）：单向晋升只读锁的 ORM 注册点在 ``ontology/models``
# （贴 OntologyTerm 定义，WP2 回执守卫同款先例——绕 create_app 的上下文
# 也武装）；本模块只承载晋升流与只读投影。

# 晋升只读投影清单白名单（对模板包消费方的稳定输出形状）
PROMOTED_TERM_FIELDS = (
    "term_id",
    "term",
    "term_type",
    "definition",
    "promoted_at",
)


class GlossaryPromotionError(ValueError):
    """晋升流失败（code/status 进响应体，形状同 BindingError）。"""

    def __init__(self, message: str, *, status: int = 400, code: str = "invalid_request") -> None:
        super().__init__(message)
        self.status = status
        self.code = code


# ---------------------------------------------------------------- 晋升流


def _load_promotion_project(session: Session, actor: Any, project_id: str) -> Project:
    """S-01：项目不存在或无 manage 权 → 统一 404（不泄露存在性）。"""
    from fde_api.projects.permissions import project_access

    project = session.get(Project, project_id)
    if project is None or not project_access(actor, project).can_manage:
        raise GlossaryPromotionError("project not found", status=404, code="not_found")
    return project


def promote_glossary_terms(
    session: Session,
    *,
    actor: Any,
    project_id: str,
    term_ids: Sequence[str],
) -> dict[str, Any]:
    """批量晋升已确认术语（幂等单向）：锚点落值 + 审计留痕。

    - draft/未确认术语 → 400 ``term_not_confirmed``；
    - 不属于本项目的 term_id → 404（S-01 统一不泄露）；
    - 已晋升行跳过（``duplicated_count``，``promoted_at`` 不重置）。
    """
    from fde_api.projects.events import record_event

    if not isinstance(term_ids, (list, tuple)) or not term_ids:
        raise GlossaryPromotionError("term_ids 必须为非空数组。")
    # M5-WP3 P9（回植前置评审）：与 annotations ≤200 同款容量硬限 + 元素
    # 类型校验（IN 列表撑爆 / 非 str 直达 SQL 的防御）。
    if len(term_ids) > 200:
        raise GlossaryPromotionError("term_ids 条目数超限（≤200）。")
    if not all(isinstance(tid, str) and tid.strip() for tid in term_ids):
        raise GlossaryPromotionError("term_ids 条目必须为非空字符串。")
    project = _load_promotion_project(session, actor, project_id)
    rows = session.scalars(
        select(OntologyTerm).where(OntologyTerm.id.in_(list(term_ids)))
    ).all()
    by_id = {row.id: row for row in rows}
    missing = [tid for tid in term_ids if tid not in by_id or by_id[tid].project_id != project.id]
    if missing:
        raise GlossaryPromotionError(
            "术语不存在或不属于本项目。", status=404, code="not_found"
        )

    promoted: list[str] = []
    duplicated: list[str] = []
    now = datetime.now(UTC)
    for tid in term_ids:
        term = by_id[tid]
        if term.promoted_readonly:
            duplicated.append(tid)
            continue
        if term.status != "confirmed":
            raise GlossaryPromotionError(
                f"术语 {term.term!r} 未确认（status={term.status}），不可晋升。",
                code="term_not_confirmed",
            )
        term.promoted_readonly = True  # False→True 转换（锁的唯一放行窗口）
        if term.promoted_at is None:
            term.promoted_at = now
        promoted.append(tid)
    if promoted:
        record_event(
            session,
            actor,
            "glossary_terms_promoted",
            project,
            {"term_ids": promoted, "duplicated_term_ids": duplicated},
        )
    session.commit()
    return {
        "promoted_count": len(promoted),
        "promoted_term_ids": promoted,
        "duplicated_count": len(duplicated),
        "duplicated_term_ids": duplicated,
    }


def list_promoted_terms(
    session: Session, *, actor: Any, project_id: str
) -> dict[str, Any]:
    """晋升只读投影清单（can_view 只读面；稳定白名单形状）。"""
    from fde_api.projects.permissions import project_access

    project = session.get(Project, project_id)
    if project is None or not project_access(actor, project).can_view:
        raise GlossaryPromotionError("project not found", status=404, code="not_found")
    rows = session.scalars(
        select(OntologyTerm)
        .where(OntologyTerm.project_id == project.id, OntologyTerm.promoted_readonly.is_(True))
        .order_by(OntologyTerm.term)
    ).all()
    return {
        "terms": [
            {
                "term_id": row.id,
                "term": row.term,
                "term_type": row.term_type,
                "definition": row.definition,
                "promoted_readonly": True,
                "promoted_at": str(row.promoted_at) if row.promoted_at else None,
            }
            for row in rows
        ]
    }


__all__ = [
    "GlossaryPromotionError",
    "list_promoted_terms",
    "promote_glossary_terms",
]
