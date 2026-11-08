"""V3.1 P0-2：本体候选与稳定 ID（ADR-002）。

验收面（任务书 §6 + docs/v3.1/decisions/ADR-002）：
- discovery→候选桥：只消费 accepted 事实；同名占用跳过；captured_from
  落 discovery:<id>；幂等（同抽取至多一个活跃候选变更集）；
- 未接受事实零候选（AI 只能创建候选、必须引用已确认事实）；
- 稳定 ID 试点：术语落定（confirm 物化 / create_term 直落 confirmed）自动
  链接同名 subject；旧行（先有 subject 后有术语）同链接=回填；术语合并
  不改写已链接行；无匹配名 subject 保持 NULL；
- 跨项目同名只读告警（D-1）：出现于响应、不阻断、不动唯一约束；
- 权限：生成=can_manage、清单=can_view、跨项目 403/404。
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from test_agents_d4_harness import ApiClient, api_client, issue_access_token, make_user
from test_agents_d4_harness import d4_app, d4_client, d4_settings  # noqa: F401  (pytest fixture)
from test_discovery_extraction import _minutes, _new_project

from fde_api.discovery.models import BusinessFact, DiscoveryExtraction
from fde_api.ontology.models import OntologyChangeSet, OntologyTerm
from fde_api.ontology import service as ontology_service
from fde_api.research.models import ProjectResearchSubject
from fde_api.workbench.models import ProjectMember


def _member_leader(db_session, d4_client, d4_settings, tag: str):
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _new_project(db_session, leader.user, tag)
    return leader, project


def _extraction_with_facts(
    db_session,
    project,
    leader_user,
    *,
    facts: list[dict],
    status: str = "review_required",
) -> DiscoveryExtraction:
    minutes = _minutes(db_session, project, leader_user)
    extraction = DiscoveryExtraction(
        project_id=project.id,
        created_by_user_id=leader_user.id,
        source_type="interview_minutes",
        source_id=minutes.id,
        source_sha256=minutes.content_sha256,
        status=status,
    )
    db_session.add(extraction)
    db_session.flush()
    for spec in facts:
        review_status = spec.get("review_status", "pending")
        stamped = review_status in ("accepted", "rejected")
        db_session.add(BusinessFact(
            project_id=project.id,
            extraction_id=extraction.id,
            fact_type=spec.get("fact_type", "process"),
            classification=spec.get("classification", "customer_stated"),
            subject=spec["subject"],
            predicate=spec["predicate"],
            object_value=spec.get("object_value", "x"),
            source_ref=f"interview_minutes:{minutes.id}",
            source_locator={"type": "line", "line": 1},
            review_status=review_status,
            reviewed_by_user_id=leader_user.id if stamped else None,
            reviewed_at=datetime.now(UTC) if stamped else None,
        ))
    db_session.commit()
    return extraction


# ---------------------------------------------------------------------------
# 候选生成桥


def test_generate_candidates_happy_path(db_session, d4_client, d4_settings) -> None:
    leader, project = _member_leader(db_session, d4_client, d4_settings, "客户L")
    extraction = _extraction_with_facts(db_session, project, leader.user, facts=[
        {"subject": "询盘处理", "predicate": "当前步骤", "object_value": {"step": "销售人工分配"}, "review_status": "accepted"},
        {"subject": "询盘处理", "predicate": "痛点", "object_value": "分配靠人", "review_status": "accepted"},
        {"subject": "生产排程", "predicate": "现状", "object_value": "Excel 排程", "review_status": "accepted"},
        {"subject": "预算额度", "predicate": "疑点", "review_status": "pending"},  # 未接受：不得入候选
    ])
    response = leader.post(
        f"/api/v1/projects/{project.id}/ontology/candidates/generate",
        json={"extraction_id": extraction.id},
    )
    assert response.status_code == 201, response.get_json()
    data = response.get_json()["data"]
    assert data["created"] is True
    change_set = data["change_set"]
    assert change_set["status"] == "draft"
    terms = [item["term"] for item in change_set["proposed_json"]]
    # 组序=subject 字典序（#209 定的口径）；本轮把该口径落到服务层实现，
    # 使固定顺序断言首次真正成立（此前仅改断言、服务层仍随机 ⇒ 约 50% flaky）。
    assert terms == ["生产排程", "询盘处理"], "仅 accepted 事实进候选、按主体聚组；组序=subject 字典序"
    # 顺序稳定性：同输入必同序，不依赖随机 uuid4 id
    assert terms == sorted(terms), "候选条目按 term 字典序稳定输出（同输入恒同输出）"
    by_term = {item["term"]: item for item in change_set["proposed_json"]}
    inquiry = by_term["询盘处理"]
    assert inquiry["action"] == "create_term" and inquiry["term_type"] == "entity"
    assert "当前步骤" in inquiry["definition"]
    assert data["skipped"] == []
    assert data["cross_project_conflicts"] == []
    row = db_session.get(OntologyChangeSet, change_set["id"])
    assert row.captured_from == f"discovery:{extraction.id}"


def test_generate_candidate_order_is_deterministic(db_session, d4_client, d4_settings) -> None:
    """候选条目顺序必须确定（回归：created_at 同事务相同 + id 为 uuid4 随机）。

    背景：business_facts.created_at 默认 now()（PG 事务级常量，同事务内所有
    行相同），id 为 uuid4 随机。原先 ORDER BY(created_at, id) 的 tie-break
    落到随机 UUID ⇒ grouped 键序随机 ⇒ 候选条目顺序抖动。
    修复：查询补确定性 tie-break，且 items 按 term 字典序输出。

    本用例刻意用「每次重建抽取 ⇒ 事实行 UUID 全新」的多次生成，
    断言多次之间顺序完全一致——若实现依赖随机 UUID，多次结果会不同。
    """
    # 三个主体，插入顺序与字典序刻意相反：Z 开头最后、Y 居中、X 最前
    facts = [
        {"subject": "Zulu流程", "predicate": "现状", "review_status": "accepted"},
        {"subject": "Yulu流程", "predicate": "现状", "review_status": "accepted"},
        {"subject": "Xulu流程", "predicate": "现状", "review_status": "accepted"},
    ]
    observed: list[list[str]] = []
    for i in range(6):
        leader, project = _member_leader(db_session, d4_client, d4_settings, f"客户确定性{i}")
        extraction = _extraction_with_facts(db_session, project, leader.user, facts=facts)
        response = leader.post(
            f"/api/v1/projects/{project.id}/ontology/candidates/generate",
            json={"extraction_id": extraction.id},
        )
        assert response.status_code == 201, response.get_json()
        terms = [item["term"] for item in response.get_json()["data"]["change_set"]["proposed_json"]]
        observed.append(terms)
        # 同主体聚成一组（3 条事实 → 3 个主体）
        assert len(terms) == 3, f"按 subject 聚组，实得 {terms}"
    # 顺序确定：所有轮次完全一致（依赖随机 UUID 时必然出现差异）
    assert all(terms == observed[0] for terms in observed), (
        f"同一输入多次生成须完全同序，实得 {observed}"
    )
    # 且为 term 字典序（不随插入序变化）
    assert observed[0] == sorted(observed[0]), f"候选顺序须为 term 字典序，实得 {observed[0]}"
    assert observed[0] == ["Xulu流程", "Yulu流程", "Zulu流程"], f"实得 {observed[0]}"


def test_generate_skips_existing_names_and_reports(db_session, d4_client, d4_settings) -> None:
    leader, project = _member_leader(db_session, d4_client, d4_settings, "客户M")
    db_session.add(OntologyTerm(
        project_id=project.id, term="生产排程", term_type="entity",
        definition="既有术语", status="confirmed", created_by_user_id=leader.user.id,
    ))
    db_session.commit()
    extraction = _extraction_with_facts(db_session, project, leader.user, facts=[
        {"subject": "生产排程", "predicate": "现状", "review_status": "accepted"},
        {"subject": "质检流程", "predicate": "步骤", "review_status": "accepted"},
    ])
    response = leader.post(
        f"/api/v1/projects/{project.id}/ontology/candidates/generate",
        json={"extraction_id": extraction.id},
    )
    assert response.status_code == 201
    data = response.get_json()["data"]
    assert [item["term"] for item in data["change_set"]["proposed_json"]] == ["质检流程"]
    assert data["skipped"] == [{"term": "生产排程", "reason": "同名术语或别名已存在"}]


def test_generate_idempotent_and_gates(db_session, d4_client, d4_settings) -> None:
    leader, project = _member_leader(db_session, d4_client, d4_settings, "客户N")
    # 无 accepted 事实 → 409
    extraction_pending = _extraction_with_facts(db_session, project, leader.user, facts=[
        {"subject": "询盘处理", "predicate": "当前步骤"},
    ])
    denied = leader.post(
        f"/api/v1/projects/{project.id}/ontology/candidates/generate",
        json={"extraction_id": extraction_pending.id},
    )
    assert denied.status_code == 409 and denied.get_json()["error"]["code"] == "no_accepted_facts"

    # running 态 → 409
    extraction_running = _extraction_with_facts(db_session, project, leader.user, status="running", facts=[
        {"subject": "询盘处理", "predicate": "当前步骤", "review_status": "accepted"},
    ])
    assert leader.post(
        f"/api/v1/projects/{project.id}/ontology/candidates/generate",
        json={"extraction_id": extraction_running.id},
    ).status_code == 409

    # happy → 幂等复用
    extraction = _extraction_with_facts(db_session, project, leader.user, facts=[
        {"subject": "询盘处理", "predicate": "当前步骤", "review_status": "accepted"},
    ])
    first = leader.post(
        f"/api/v1/projects/{project.id}/ontology/candidates/generate",
        json={"extraction_id": extraction.id},
    )
    assert first.status_code == 201
    again = leader.post(
        f"/api/v1/projects/{project.id}/ontology/candidates/generate",
        json={"extraction_id": extraction.id},
    )
    assert again.status_code == 200
    assert again.get_json()["data"]["created"] is False
    assert again.get_json()["data"]["change_set"]["id"] == first.get_json()["data"]["change_set"]["id"]

    # 缺参 → 400
    assert leader.post(
        f"/api/v1/projects/{project.id}/ontology/candidates/generate", json={},
    ).status_code == 400


def test_generate_access_control(db_session, d4_client, d4_settings) -> None:
    leader, project = _member_leader(db_session, d4_client, d4_settings, "客户O")
    extraction = _extraction_with_facts(db_session, project, leader.user, facts=[
        {"subject": "询盘处理", "predicate": "当前步骤", "review_status": "accepted"},
    ])
    member_user = make_user(db_session, "fde_engineer")
    db_session.add(ProjectMember(project_id=project.id, user_id=member_user.id, role="member"))
    db_session.commit()
    member = ApiClient(d4_client, member_user, {"Authorization": f"Bearer {issue_access_token(member_user, d4_settings)}"})
    # member（非管理）生成 → 403；读清单 → 200
    assert member.post(
        f"/api/v1/projects/{project.id}/ontology/candidates/generate",
        json={"extraction_id": extraction.id},
    ).status_code == 403
    assert member.get(f"/api/v1/projects/{project.id}/ontology/candidates").status_code == 200
    # 跨项目 leader → 403（非成员）/404（伪造他项目抽取）
    stranger = api_client(d4_client, db_session, d4_settings, "project_lead")
    assert stranger.get(f"/api/v1/projects/{project.id}/ontology/candidates").status_code == 403
    other_leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    other_project = _new_project(db_session, other_leader.user, "客户P")
    assert other_leader.post(
        f"/api/v1/projects/{other_project.id}/ontology/candidates/generate",
        json={"extraction_id": extraction.id},
    ).status_code == 404


def test_cross_project_conflict_warning_readonly(db_session, d4_client, d4_settings) -> None:
    leader_a, project_a = _member_leader(db_session, d4_client, d4_settings, "客户Q")
    leader_b, project_b = _member_leader(db_session, d4_client, d4_settings, "客户R")
    db_session.add(OntologyTerm(
        project_id=project_b.id, term="询盘处理", term_type="entity",
        definition="B 项目同名概念", status="confirmed", created_by_user_id=leader_b.user.id,
    ))
    db_session.commit()
    extraction = _extraction_with_facts(db_session, project_a, leader_a.user, facts=[
        {"subject": "询盘处理", "predicate": "当前步骤", "review_status": "accepted"},
    ])
    response = leader_a.post(
        f"/api/v1/projects/{project_a.id}/ontology/candidates/generate",
        json={"extraction_id": extraction.id},
    )
    assert response.status_code == 201
    conflicts = response.get_json()["data"]["cross_project_conflicts"]
    assert conflicts == [{"term": "询盘处理", "project_ids": [project_b.id]}]
    # 只读：A 项目约束未被触碰（候选照常落 draft，等价于无告警路径）
    assert db_session.query(OntologyChangeSet).filter_by(project_id=project_a.id).count() == 1


def test_candidates_list_projection(db_session, d4_client, d4_settings) -> None:
    leader, project = _member_leader(db_session, d4_client, d4_settings, "客户S")
    extraction = _extraction_with_facts(db_session, project, leader.user, facts=[
        {"subject": "询盘处理", "predicate": "当前步骤", "review_status": "accepted"},
    ])
    leader.post(
        f"/api/v1/projects/{project.id}/ontology/candidates/generate",
        json={"extraction_id": extraction.id},
    )
    # 人工路径 change-set（无 captured_from）不得混入
    leader.post(
        f"/api/v1/projects/{project.id}/ontology/change-sets",
        json={"title": "人工候选", "proposed_json": [{"action": "create_term", "term": "手工术语", "definition": "x"}]},
    )
    listing = leader.get(f"/api/v1/projects/{project.id}/ontology/candidates")
    assert listing.status_code == 200
    items = listing.get_json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["captured_from"].startswith("discovery:")


# ---------------------------------------------------------------------------
# 稳定 ID 试点（ADR-002）


def _accepted_fact_subject(db_session, project, leader_user, subject_name: str) -> DiscoveryExtraction:
    return _extraction_with_facts(db_session, project, leader_user, facts=[
        {"subject": subject_name, "predicate": "当前步骤", "review_status": "accepted"},
    ])


def test_term_materialize_links_same_name_subject(db_session, d4_client, d4_settings) -> None:
    leader, project = _member_leader(db_session, d4_client, d4_settings, "客户T")
    subject = ProjectResearchSubject(
        project_id=project.id, parent_subject_id=None, subject_type="department",
        subject_key=f"dept-{uuid4().hex[:8]}", name="询盘处理",
    )
    db_session.add(subject)
    db_session.commit()
    extraction = _accepted_fact_subject(db_session, project, leader.user, "询盘处理")
    created = leader.post(
        f"/api/v1/projects/{project.id}/ontology/candidates/generate",
        json={"extraction_id": extraction.id},
    )
    change_set_id = created.get_json()["data"]["change_set"]["id"]
    # 提交 + 他人确认（决策分离）→ 物化 create_term → 自动链接
    assert leader.post(
        f"/api/v1/projects/{project.id}/ontology/change-sets/{change_set_id}/submit"
    ).status_code == 200
    admin = api_client(d4_client, db_session, d4_settings, "admin")
    confirmed = admin.post(
        f"/api/v1/projects/{project.id}/ontology/change-sets/{change_set_id}/confirm"
    )
    assert confirmed.status_code == 200, confirmed.get_json()
    db_session.expire_all()
    term = db_session.query(OntologyTerm).filter_by(project_id=project.id, term="询盘处理").one()
    linked = db_session.get(ProjectResearchSubject, subject.id)
    assert linked.term_id == term.id, "术语落定（confirm 物化）自动链接同名主体"


def _confirmed_term(db_session, app, project, actor_user, name: str, definition: str):
    from fde_api.ontology import service as onto

    with app.app_context():
        from fde_api.extensions import db

        with db.session() as session, session.begin():
            row = onto.create_term(
                session,
                project_id=project.id,
                term=name,
                definition=definition,
                actor=actor_user,
                initial_status="confirmed",
            )
            term_id = row.id
    db_session.expire_all()
    return term_id


def test_create_term_confirmed_links_and_old_rows_fill(db_session, d4_app, d4_client, d4_settings) -> None:
    leader, project = _member_leader(db_session, d4_client, d4_settings, "客户U")
    # 先有 subject（旧数据形态，term_id=NULL）
    subject = ProjectResearchSubject(
        project_id=project.id, parent_subject_id=None, subject_type="department",
        subject_key=f"dept-{uuid4().hex[:8]}", name="质检流程",
    )
    other = ProjectResearchSubject(
        project_id=project.id, parent_subject_id=None, subject_type="department",
        subject_key=f"dept-{uuid4().hex[:8]}", name="无关主体",
    )
    db_session.add_all([subject, other])
    db_session.commit()
    term_id = _confirmed_term(db_session, d4_app, project, leader.user, "质检流程", "人工定义")
    linked = db_session.get(ProjectResearchSubject, subject.id)
    untouched = db_session.get(ProjectResearchSubject, other.id)
    assert linked.term_id == term_id, "confirmed 落定即链接同名主体（旧数据回填）"
    assert untouched.term_id is None, "无匹配名主体保持 NULL"
    # 幂等：重复落定同名词被 409（唯一约束），链接不重复触发
    import pytest
    from fde_api.ontology.service import OntologyServiceError

    with pytest.raises(OntologyServiceError) as excinfo:
        _confirmed_term(db_session, d4_app, project, leader.user, "质检流程", "重复定义")
    assert excinfo.value.code == "term_exists"


def test_term_merge_does_not_rewrite_linked_subject(db_session, d4_app, d4_client, d4_settings) -> None:
    leader, project = _member_leader(db_session, d4_client, d4_settings, "客户V")
    subject = ProjectResearchSubject(
        project_id=project.id, parent_subject_id=None, subject_type="department",
        subject_key=f"dept-{uuid4().hex[:8]}", name="排程瓶颈",
    )
    db_session.add(subject)
    db_session.commit()
    source_id = _confirmed_term(db_session, d4_app, project, leader.user, "排程瓶颈", "现状")
    target_id = _confirmed_term(db_session, d4_app, project, leader.user, "生产排程", "目标概念")
    from fde_api.ontology import service as onto

    with d4_app.app_context():
        from fde_api.extensions import db

        with db.session() as session, session.begin():
            onto.merge_terms(session, source_id=source_id, target_id=target_id, actor=leader.user)
    db_session.expire_all()
    linked = db_session.get(ProjectResearchSubject, subject.id)
    assert linked.term_id == source_id, "合并不改写历史链接行（读路径名字域兜底）"
    merged_term = db_session.get(OntologyTerm, source_id)
    assert merged_term.status == "merged" and merged_term.canonical_term_id == target_id


def test_subject_without_term_stays_null_and_readable(db_session, d4_client, d4_settings) -> None:
    leader, project = _member_leader(db_session, d4_client, d4_settings, "客户W")
    subject = ProjectResearchSubject(
        project_id=project.id, parent_subject_id=None, subject_type="department",
        subject_key=f"dept-{uuid4().hex[:8]}", name="从未成为术语的主体",
    )
    db_session.add(subject)
    db_session.commit()
    db_session.expire_all()
    assert db_session.get(ProjectResearchSubject, subject.id).term_id is None
    # 读路径零变化：调研对象列表照常返回（名字匹配合同不受影响）
    listing = leader.get(f"/api/v1/projects/{project.id}/research/subjects")
    assert listing.status_code == 200
