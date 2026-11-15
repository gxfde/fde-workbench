"""V3.3 M5-WP3③：Glossary 单向晋升 + promoted_readonly 只读投影（改进单 4）。

验收语义（工作令 §3 WP3 条 3 / 模型注释口径）：
- **晋升流**：``status='confirmed'`` 的术语方可晋升进模板包锚点
  （``promoted_readonly=True`` + ``promoted_at``）；draft 不可晋升；跨项目
  术语 404（S-01 不泄露存在性）；重复晋升幂等（不重置 promoted_at）；
- **单向不可逆只读投影**：ORM ``before_update`` 事件守卫——已晋升行的内容列
  （term/definition/term_type/canonical_term_id/status）任何改写在 flush 前
  响亮失败（WP2 回执守卫同款范式）；``False→True`` 的晋升转换本身放行；
- **真实编辑路径拦截**：术语修订唯一路径 = change-set ``update_term`` 动作
  物化（``ontology/service.py`` confirm 全成全败事务）——对已晋升术语的
  confirm 物化必须被锁击穿并整体回滚（service.py 零侵入，锁在 ORM 层）；
- 晋升/清单全程审计留痕；零 DDL（锚点列 WP2 迁移已就位）。
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from datetime import UTC, datetime

from fde_api.ontology.models import OntologyChangeSet, OntologyTerm
from fde_api.workbench.models import OperationEvent, Project

from test_gates_api import admin_client, gate_project  # noqa: F401  (fixture 供给方)


# ---------------------------------------------------------------- helpers


def _confirmed_term(db_session, project_row, name: str, definition: str = "既定口径") -> OntologyTerm:
    row = OntologyTerm(
        project_id=project_row.id,
        term=name,
        definition=definition,
        status="confirmed",
    )
    db_session.add(row)
    db_session.commit()
    return row


def _promote(db_session, actor, project, term_ids):
    from fde_api.ontology.glossary_promotion import promote_glossary_terms

    return promote_glossary_terms(
        db_session, actor=actor, project_id=project["id"], term_ids=term_ids
    )


# ---------------------------------------------------------------- 晋升流


def test_promote_confirmed_term_sets_anchor_and_audits(
    gate_project, db_session, settings, monkeypatch
):
    """confirmed 晋升：锚点落值 + promoted_at + 审计事件。"""
    monkeypatch.setattr(settings, "ontology_enabled", False, raising=False)
    project, _url, leader = gate_project
    project_row = db_session.get(Project, project["id"])
    term = _confirmed_term(db_session, project_row, "批次合格率")
    result = _promote(db_session, leader.user, project, [term.id])
    assert result["promoted_count"] == 1 and result["duplicated_count"] == 0
    db_session.refresh(term)
    assert term.promoted_readonly is True
    assert term.promoted_at is not None
    event = db_session.scalar(
        select(OperationEvent).where(
            OperationEvent.project_id == project["id"],
            OperationEvent.event_type == "glossary_terms_promoted",
        )
    )
    assert event is not None and term.id in event.changes["term_ids"]


def test_promote_rejects_draft_term(gate_project, db_session, settings, monkeypatch):
    """draft 术语不可晋升（只收已确认口径）。"""
    monkeypatch.setattr(settings, "ontology_enabled", False, raising=False)
    project, _url, leader = gate_project
    project_row = db_session.get(Project, project["id"])
    draft = OntologyTerm(project_id=project_row.id, term="草稿词", definition="未确认")
    db_session.add(draft)
    db_session.commit()
    from fde_api.ontology.glossary_promotion import GlossaryPromotionError

    with pytest.raises(GlossaryPromotionError) as excinfo:
        _promote(db_session, leader.user, project, [draft.id])
    assert excinfo.value.code == "term_not_confirmed"


def test_promote_rejects_cross_project_term(gate_project, db_session, settings, monkeypatch):
    """跨项目术语 id → 404（S-01 不泄露存在性）。"""
    monkeypatch.setattr(settings, "ontology_enabled", False, raising=False)
    project, _url, leader = gate_project
    from fde_api.ontology.glossary_promotion import GlossaryPromotionError

    with pytest.raises(GlossaryPromotionError) as excinfo:
        _promote(db_session, leader.user, project, ["term-not-here"])
    assert excinfo.value.status == 404


def test_promote_is_idempotent(gate_project, db_session, settings, monkeypatch):
    """重复晋升幂等：duplicated 计数 + promoted_at 不重置。"""
    monkeypatch.setattr(settings, "ontology_enabled", False, raising=False)
    project, _url, leader = gate_project
    project_row = db_session.get(Project, project["id"])
    term = _confirmed_term(db_session, project_row, "抽检比例")
    first = _promote(db_session, leader.user, project, [term.id])
    db_session.refresh(term)
    promoted_at = term.promoted_at
    second = _promote(db_session, leader.user, project, [term.id])
    assert first["promoted_count"] == 1
    assert second["duplicated_count"] == 1 and second["promoted_count"] == 0
    db_session.refresh(term)
    assert term.promoted_at == promoted_at  # 单向：不重置时间锚


# ---------------------------------------------------------------- 只读投影锁


def test_promotion_lock_blocks_content_column_writes(
    gate_project, db_session, settings, monkeypatch
):
    """已晋升行内容列改写 → flush 前响亮失败（单向不可逆）。"""
    monkeypatch.setattr(settings, "ontology_enabled", False, raising=False)
    project, _url, leader = gate_project
    project_row = db_session.get(Project, project["id"])
    term = _confirmed_term(db_session, project_row, "锁定词")
    _promote(db_session, leader.user, project, [term.id])
    db_session.expire_all()
    locked = db_session.get(OntologyTerm, term.id)
    locked.definition = "被篡改的定义"
    with pytest.raises(RuntimeError, match="promoted_readonly"):
        db_session.flush()
    db_session.rollback()


def test_promotion_lock_blocks_status_demotion(
    gate_project, db_session, settings, monkeypatch
):
    """status 降级（confirmed→draft 绕道编辑）同样被锁。"""
    monkeypatch.setattr(settings, "ontology_enabled", False, raising=False)
    project, _url, leader = gate_project
    project_row = db_session.get(Project, project["id"])
    term = _confirmed_term(db_session, project_row, "状态锁词")
    _promote(db_session, leader.user, project, [term.id])
    db_session.expire_all()
    locked = db_session.get(OntologyTerm, term.id)
    locked.status = "draft"
    with pytest.raises(RuntimeError, match="promoted_readonly"):
        db_session.flush()
    db_session.rollback()


def test_promotion_transition_false_to_true_passes(
    gate_project, db_session, settings, monkeypatch
):
    """晋升转换（False→True + promoted_at）本身放行（守卫不误伤晋升动作）。"""
    monkeypatch.setattr(settings, "ontology_enabled", False, raising=False)
    project, _url, leader = gate_project
    project_row = db_session.get(Project, project["id"])
    term = _confirmed_term(db_session, project_row, "转换放行词")
    # promote 内部即 False→True 转换——不炸即放行成立
    _promote(db_session, leader.user, project, [term.id])
    db_session.refresh(term)
    assert term.promoted_readonly is True


# ---------------------------------------------------------------- 锁装配点


def test_promotion_lock_armed_by_models_module() -> None:
    """⑦ party 评审钉：晋升锁随 ``ontology/models`` 武装，不依赖路由 import 链。

    数据完整性锁的注册点必须贴模型定义（WP2 回执守卫/研究客体守卫同款
    先例）——绕 create_app 的 CLI/维护进程 import 模型即有锁（Winston P2-1）。
    """
    from sqlalchemy import event as sa_event

    from fde_api.ontology import models as ontology_models

    assert sa_event.contains(
        OntologyTerm, "before_update", ontology_models._promotion_no_content_change
    )


# ---------------------------------------------------------------- 真实编辑路径拦截


def test_change_set_update_term_on_promoted_term_is_blocked(
    gate_project, db_session, settings, monkeypatch
):
    """对已晋升术语走 change-set update_term：confirm 物化被锁击穿 + 全成全败回滚。"""
    monkeypatch.setattr(settings, "ontology_enabled", False, raising=False)
    project, _url, leader = gate_project
    project_row = db_session.get(Project, project["id"])
    term = _confirmed_term(db_session, project_row, "晋升后改词", definition="原口径")
    _promote(db_session, leader.user, project, [term.id])
    db_session.commit()

    from fde_api.ontology.service import (
        propose_project_change_set,
        confirm_project_change_set,
        submit_project_change_set,
        OntologyServiceError,
    )

    cs = propose_project_change_set(
        actor=leader.user,
        project_id=project["id"],
        payload={
            "title": "试图改已晋升术语",
            "proposed_json": [
                {"action": "update_term", "term": "晋升后改词", "definition": "被改口径"}
            ],
        },
    )
    change_set_id = cs["change_set"]["id"]
    submit_project_change_set(
        actor=leader.user, project_id=project["id"], change_set_id=change_set_id
    )
    # 验收分离：confirm 拍板人须异于提交人——用 admin（gate.admin）异人拍板
    from fde_api.auth.models import User

    admin_row = db_session.scalar(select(User).where(User.username == "gate.admin"))
    assert admin_row is not None
    with pytest.raises((RuntimeError, OntologyServiceError)):
        confirm_project_change_set(
            actor=admin_row,
            project_id=project["id"],
            change_set_id=change_set_id,
        )
    db_session.rollback()
    db_session.expire_all()
    locked = db_session.get(OntologyTerm, term.id)
    assert locked.definition == "原口径"  # 全成全败：值未被改写
    assert db_session.scalar(
        select(OntologyChangeSet.status).where(OntologyChangeSet.id == change_set_id)
    ) in ("draft", "in_review", "confirmed", "rejected", "superseded")


def test_change_set_merge_terms_on_promoted_source_is_blocked(
    gate_project, db_session, settings, monkeypatch
):
    """P1（评审验证缺口）：merge_terms 物化触已晋升 source 同样被锁 + 回滚保原值。

    merge 物化对 source 写 status='merged' + canonical_term_id——锁拦住后
    「单向不可逆」在该用户路径与 update_term 同水位；若未来物化改走 Core
    update 绕过 ORM 事件，本钉红。
    """
    monkeypatch.setattr(settings, "ontology_enabled", False, raising=False)
    project, _url, leader = gate_project
    project_row = db_session.get(Project, project["id"])
    source = _confirmed_term(db_session, project_row, "晋升后被并词", definition="原口径")
    _confirmed_term(db_session, project_row, "合并保留词", definition="保留口径")
    _promote(db_session, leader.user, project, [source.id])
    db_session.commit()

    from fde_api.ontology.service import (
        propose_project_change_set,
        confirm_project_change_set,
        submit_project_change_set,
        OntologyServiceError,
    )

    cs = propose_project_change_set(
        actor=leader.user,
        project_id=project["id"],
        payload={
            "title": "试图并掉已晋升术语",
            "proposed_json": [
                {
                    "action": "merge_terms",
                    "source_term": "晋升后被并词",
                    "target_term": "合并保留词",
                }
            ],
        },
    )
    change_set_id = cs["change_set"]["id"]
    submit_project_change_set(
        actor=leader.user, project_id=project["id"], change_set_id=change_set_id
    )
    from fde_api.auth.models import User

    admin_row = db_session.scalar(select(User).where(User.username == "gate.admin"))
    assert admin_row is not None
    with pytest.raises((RuntimeError, OntologyServiceError)):
        confirm_project_change_set(
            actor=admin_row,
            project_id=project["id"],
            change_set_id=change_set_id,
        )
    db_session.rollback()
    db_session.expire_all()
    locked = db_session.get(OntologyTerm, source.id)
    assert locked.status == "confirmed"  # 全成全败：未翻 merged
    assert locked.canonical_term_id is None  # 未重指 target
    db_session.rollback()


def test_promote_rejects_oversized_or_non_string_term_ids(
    gate_project, db_session, settings, monkeypatch
):
    """P9（评审边界）：term_ids 条数 ≤200 且元素须非空字符串（与 ③ 对称）。"""
    monkeypatch.setattr(settings, "ontology_enabled", False, raising=False)
    project, _url, leader = gate_project
    from fde_api.ontology.glossary_promotion import GlossaryPromotionError

    with pytest.raises(GlossaryPromotionError) as excinfo:
        _promote(db_session, leader.user, project, [f"t{i}" for i in range(201)])
    assert "200" in str(excinfo.value)
    with pytest.raises(GlossaryPromotionError):
        _promote(db_session, leader.user, project, ["合法", 123])
    db_session.rollback()


def test_promotion_lock_blocks_promoted_at_rewrite(
    gate_project, db_session, settings, monkeypatch
):
    """P8（评审边界）：已晋升行的 promoted_at 时间锚同入锁——单向不重置。"""
    monkeypatch.setattr(settings, "ontology_enabled", False, raising=False)
    project, _url, leader = gate_project
    project_row = db_session.get(Project, project["id"])
    term = _confirmed_term(db_session, project_row, "锚锁词")
    _promote(db_session, leader.user, project, [term.id])
    db_session.expire_all()
    locked = db_session.get(OntologyTerm, term.id)
    locked.promoted_at = datetime(1999, 1, 1, tzinfo=UTC)
    with pytest.raises(RuntimeError, match="promoted_readonly"):
        db_session.flush()
    db_session.rollback()


# ---------------------------------------------------------------- 路由烟测


def test_glossary_promotion_routes_http(
    gate_project, admin_client, client, db_session, settings, monkeypatch
):
    """POST promote（can_manage）+ GET promoted 只读投影清单。"""
    monkeypatch.setattr(settings, "ontology_enabled", False, raising=False)
    project, _url, _leader = gate_project
    project_row = db_session.get(Project, project["id"])
    term = _confirmed_term(db_session, project_row, "路由词")
    pid = project["id"]
    promote = admin_client.post(
        f"/api/v1/projects/{pid}/ontology/glossary/promote",
        json={"term_ids": [term.id]},
    )
    assert promote.status_code == 200, promote.get_data(as_text=True)
    assert promote.json["data"]["promoted_count"] == 1
    listing = admin_client.get(f"/api/v1/projects/{pid}/ontology/glossary/promoted")
    assert listing.status_code == 200, listing.get_data(as_text=True)
    terms = listing.json["data"]["terms"]
    assert any(row["term"] == "路由词" for row in terms)
    assert all(row["promoted_readonly"] is True for row in terms)
