"""AI 原生化 N3a（G-05）：quality 用例 AI 起草（试点首发位 D-4，任务书 §15 序 1）。

验收面（任务书 N3a DoD 逐条 + G-05 消解判据复测动作）：
- ①AI 起草入口走 ``execute_ai_prompt`` 单一入口（本测试面：模块级打桩——
  打桩即证明调用面只有一个名字；预算门/审计/降级在单一入口体内，钉见
  test_prompt_entrypoint_gate J-1 白名单 QUALITY_TESTCASE_DRAFT_SYSTEM_PROMPT）；
- ②契约失败**整批零写入**（fail-closed 家族一致——失败路径 TestPlan/TestCase
  零行；成功=DB 写入是全管线最后一步）；
- ③草稿态不可被下游消费（draft 计划 execute 409 not_executable；经人工审核
  draft→approved 闸后才可执行——变异：摘掉 execute 的 approved 闸本钉转红）；
- ④两段式审核戳仍在位（review 事件 test_plan_reviewed；AI 只出 draft，
  不自动批准、不跳需求覆盖闸、不动 production 硬闸）；
- ⑤溯源（N2）：test_plan_ai_drafted 事件带 prompt_version＋model。
明确不做（任务书边界）：不自动批准 / 不跳覆盖闸 / 不动 production 硬闸。
"""
from __future__ import annotations

import json

from test_agents_d4_harness import ApiClient, api_client, issue_access_token, make_user
from test_agents_d4_harness import d4_app, d4_client, d4_settings  # noqa: F401  (pytest fixture)
from test_delivery_plans import _seed_requirements
from test_discovery_extraction import _DICT_NAME, _new_project

from fde_api.quality import draft as quality_draft
from fde_api.quality.models import TestPlan
from fde_api.quality.models import TestCase as QualityCase
from fde_api.workbench.models import OperationEvent, ProjectMember


def _leader_project(db_session, d4_client, d4_settings, tag: str):
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _new_project(db_session, leader.user, tag)
    return leader, project


def _ai_case(requirement_key: str, *, title: str = "AI 起草用例", expected: str = "AI 预期结果",
             acceptance_mode: str = "test", steps: list[str] | None = None) -> dict:
    return {
        "requirement_key": requirement_key,
        "title": title,
        "steps": steps if steps is not None else ["打开被测页面", "执行操作"],
        "expected": expected,
        "risk_level": 2,
        "acceptance_mode": acceptance_mode,
    }


def _patch_ai(outputs: list, calls: list):
    """把 quality.draft.execute_ai_prompt 换成固定输出序列（diagnostics 同法）。

    序列项：dict=合法 payload（json.dumps 进 text）；str=原样文本（畸形 JSON）；
    Exception=上抛。**最后一项对后续重试粘性复用**（同 discovery「重放同一输出」
    语义——重试不会烧到序列外的下一项），每次调用记 kwargs（目的/版本/执行键钉证）。
    """
    state = {"i": 0}

    def _fake_execute(**kwargs):
        calls.append(kwargs)
        index = min(state["i"], len(outputs) - 1)
        state["i"] += 1
        item = outputs[index]
        if isinstance(item, Exception):
            raise item
        if isinstance(item, dict):
            item = json.dumps(item, ensure_ascii=False)
        return {"text": item, "model": {"provider": "test", "name": "test-model"}, "provider_usage": {}}

    original = quality_draft.execute_ai_prompt
    quality_draft.execute_ai_prompt = _fake_execute
    return original


def _unpatch_ai(original) -> None:
    quality_draft.execute_ai_prompt = original


def _ai_generate(db_session, leader, project, outputs: list, payload: dict | None = None):
    calls: list = []
    original = _patch_ai(outputs, calls)
    try:
        response = leader.post(
            f"/api/v1/projects/{project.id}/test-plans/generate-ai", json=payload or {}
        )
    finally:
        _unpatch_ai(original)
    return response, calls


# ---------------------------------------------------------------------------
# 成功路径（产出恒 draft＋溯源留痕＋确定性序）


def test_ai_draft_happy_path_produces_draft_with_provenance(db_session, d4_client, d4_settings) -> None:
    leader, project = _leader_project(db_session, d4_client, d4_settings, "N3A-1")
    requirements = _seed_requirements(db_session, project, leader.user, 2)
    keys = sorted(r.requirement_key for r in requirements)
    # 模型返回序故意与需求字典序相反——归一化后 sort_order 须按 (requirement_key, 原下标) 重排
    outputs = [{"cases": [_ai_case(keys[1]), _ai_case(keys[0], acceptance_mode="manual")]}]
    response, calls = _ai_generate(db_session, leader, project, outputs)
    assert response.status_code == 201, response.get_json()
    data = response.get_json()["data"]
    plan = data["plan"]
    assert plan["status"] == "draft", "AI 产物恒为 draft（人工审核闸承载发布语义）"
    assert plan["version"] == 1
    assert data["prompt_version"] == quality_draft.DRAFT_PROMPT_VERSION
    assert data["model"] == "test-model"
    cases = plan["cases"]
    assert [case["requirement_key"] for case in cases] == keys, "sort_order=(requirement_key,原下标) 确定性重排"
    assert cases[0]["acceptance_mode"] == "manual" and cases[1]["acceptance_mode"] == "test"

    # ⑤溯源（N2）：test_plan_ai_drafted 事件带 prompt_version＋model
    event = db_session.query(OperationEvent).filter_by(
        target_type="test_plan", target_id=plan["id"], event_type="test_plan_ai_drafted"
    ).one()
    assert event.changes["prompt_version"] == quality_draft.DRAFT_PROMPT_VERSION
    assert event.changes["model"] == "test-model"
    assert event.changes["case_count"] == 2

    # ①单一入口钉证：打桩 kwargs 携 purpose/prompt_version/execution_id（审计归因三元）
    assert len(calls) == 1
    assert calls[0]["purpose"] == "quality_testcase_draft"
    assert calls[0]["prompt_version"] == quality_draft.DRAFT_PROMPT_VERSION
    assert calls[0]["execution_id"].startswith("quality-draft:")
    assert calls[0]["use_tools"] is False


def test_ai_draft_version_bumps_and_history_kept(db_session, d4_client, d4_settings) -> None:
    leader, project = _leader_project(db_session, d4_client, d4_settings, "N3A-2")
    requirements = _seed_requirements(db_session, project, leader.user, 1)
    first, _ = _ai_generate(db_session, leader, project, [{"cases": [_ai_case(requirements[0].requirement_key)]}])
    assert first.status_code == 201
    first_id = first.get_json()["data"]["plan"]["id"]

    second, _ = _ai_generate(db_session, leader, project, [{"cases": [_ai_case(requirements[0].requirement_key)]}])
    assert second.status_code == 201
    second_id = second.get_json()["data"]["plan"]["id"]
    assert second.get_json()["data"]["plan"]["version"] == 2
    assert second_id != first_id
    db_session.expire_all()
    assert db_session.get(TestPlan, first_id).status == "draft", "历史 draft 不被覆盖（版本化先例同尺）"
    assert db_session.query(QualityCase).filter_by(plan_id=first_id).count() == 1


# ---------------------------------------------------------------------------
# 契约失败整批零写入（fail-closed 家族一致）


def test_ai_draft_contract_failure_zero_write(db_session, d4_client, d4_settings) -> None:
    leader, project = _leader_project(db_session, d4_client, d4_settings, "N3A-3")
    _seed_requirements(db_session, project, leader.user, 1)
    # 畸形 JSON（重试后仍畸形）→ 409 ai_draft_contract_failed，零写入
    response, calls = _ai_generate(db_session, leader, project, ["{not json", "{also-bad"])
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "ai_draft_contract_failed"
    assert len(calls) == 2, "契约失败自动重试一次（discovery 同裁）"
    assert db_session.query(TestPlan).filter_by(project_id=project.id).count() == 0
    assert db_session.query(QualityCase).filter_by(project_id=project.id).count() == 0

    # 越界需求键（虚构键）→ 整批拒绝
    from fde_api.discovery.models import Requirement

    foreign_key = "R-foreign99"
    key = db_session.query(Requirement.requirement_key).filter_by(
        project_id=project.id, status="accepted"
    ).scalar()
    bad_key = _ai_case(key, title="杂项用例")
    bad_key["requirement_key"] = foreign_key
    response, _ = _ai_generate(db_session, leader, project, [{"cases": [bad_key]}])
    assert response.status_code == 409
    assert db_session.query(TestPlan).filter_by(project_id=project.id).count() == 0, "越界键整批拒绝零写入"


def test_ai_draft_coverage_preflight_rejects_missing_requirement(db_session, d4_client, d4_settings) -> None:
    """覆盖先验（第一道）：漏一条 accepted 需求 ⇒ 整批 409（第二道=审核覆盖闸，
    test_quality_test_plans 已钉；本钉钉 AI 侧先验——审核前即挡）。"""
    leader, project = _leader_project(db_session, d4_client, d4_settings, "N3A-4")
    requirements = _seed_requirements(db_session, project, leader.user, 2)
    covered = _ai_case(requirements[0].requirement_key)
    response, _ = _ai_generate(db_session, leader, project, [{"cases": [covered]}])
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "ai_draft_contract_failed"
    assert db_session.query(TestPlan).filter_by(project_id=project.id).count() == 0


def test_ai_draft_without_requirements_409_before_ai_call(db_session, d4_client, d4_settings) -> None:
    """无已批准需求 ⇒ 409 no_approved_requirements（**AI 调用前**即拒——零 AI 烧费）。"""
    leader, project = _leader_project(db_session, d4_client, d4_settings, "N3A-5")

    def _fail_if_called(**kwargs):
        raise AssertionError("无需求时不得发起 AI 调用（零烧费纪律）")

    original = quality_draft.execute_ai_prompt
    quality_draft.execute_ai_prompt = _fail_if_called
    try:
        response = leader.post(f"/api/v1/projects/{project.id}/test-plans/generate-ai", json={})
    finally:
        quality_draft.execute_ai_prompt = original
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "no_approved_requirements"


# ---------------------------------------------------------------------------
# 草稿态不可被下游消费（DoD③；变异：摘 execute 的 approved 闸 ⇒ 本钉转红）


def test_ai_draft_not_consumable_before_human_review(db_session, d4_client, d4_settings) -> None:
    leader, project = _leader_project(db_session, d4_client, d4_settings, "N3A-6")
    requirements = _seed_requirements(db_session, project, leader.user, 1)
    _, _ = _ai_generate(
        db_session, leader, project,
        [{"cases": [_ai_case(requirements[0].requirement_key)]}],
    )
    plan = db_session.query(TestPlan).filter_by(project_id=project.id).one()
    case_id = db_session.query(QualityCase).filter_by(plan_id=plan.id).one().id

    # draft 计划执行 409（仅 approved 可登记执行——既有闸机械承载，AI 不绕过）
    execute_denied = leader.post(
        f"/api/v1/test-plans/{plan.id}/execute",
        json={"environment": "dev", "executions": [{"case_id": case_id, "result": "passed"}]},
    )
    assert execute_denied.status_code == 409
    assert execute_denied.get_json()["error"]["code"] == "not_executable"

    # 人工审核闸承载发布：draft→approved（两段式审核戳仍在位）
    reviewed = leader.patch(f"/api/v1/test-plans/{plan.id}/review", json={"decision": "approved"})
    assert reviewed.status_code == 200, reviewed.get_json()
    assert reviewed.get_json()["data"]["plan"]["status"] == "approved"
    review_events = db_session.query(OperationEvent).filter_by(
        target_type="test_plan", target_id=plan.id, event_type="test_plan_reviewed"
    ).count()
    assert review_events == 1, "AI 不代拍板：审核戳仍由人工 review 动作打"

    # 批准后执行放行
    execute_ok = leader.post(
        f"/api/v1/test-plans/{plan.id}/execute",
        json={"environment": "dev", "executions": [{"case_id": case_id, "result": "passed"}]},
    )
    assert execute_ok.status_code == 200, execute_ok.get_json()
    assert execute_ok.get_json()["data"]["count"] == 1


# ---------------------------------------------------------------------------
# 输出端兜底脱敏 + 凭据 fail-closed（证据红线同族）


def test_ai_draft_redaction_and_credential_fail_closed(db_session, d4_client, d4_settings) -> None:
    leader, project = _leader_project(db_session, d4_client, d4_settings, "N3A-7")
    requirements = _seed_requirements(db_session, project, leader.user, 1)
    key = requirements[0].requirement_key

    # 词典命中（种子合成名，零真实资料）⇒ 替换＋复核事件（与 discovery 第③层同构）
    tainted = _ai_case(key, title=f"{_DICT_NAME}的登录流程", expected=f"与{_DICT_NAME}对账通过")
    response, _ = _ai_generate(db_session, leader, project, [{"cases": [tainted]}])
    assert response.status_code == 201, response.get_json()
    plan = response.get_json()["data"]["plan"]
    stored = db_session.get(QualityCase, plan["cases"][0]["id"])
    assert _DICT_NAME not in stored.title, "输出端兜底脱敏必须替换词典命中名"
    redaction_events = db_session.query(OperationEvent).filter_by(
        target_type="test_plan", target_id=plan["id"], event_type="quality.redaction_review"
    ).count()
    assert redaction_events == 1
    # 盲审追批零真名换代：事件账条目只存指纹（＋疑似哨兵），零真名原文。
    review_event = db_session.query(OperationEvent).filter_by(
        target_type="test_plan", target_id=plan["id"], event_type="quality.redaction_review"
    ).first()
    from fde_api.guidance.redaction import redaction_name_hash as _rnh

    assert any(e.get("name_hash") == _rnh(_DICT_NAME) for e in review_event.changes["entries"])
    assert all(not e.get("name") for e in review_event.changes["entries"]), "复核事件账零真名"

    # 凭据串命中 ⇒ 422 整批拒绝＋零写入（fail-closed：凭据不落库）
    cred_case = _ai_case(key, expected="登录后密钥: abcdefghijkl1234 生效")
    denied, _ = _ai_generate(db_session, leader, project, [{"cases": [cred_case]}])
    assert denied.status_code == 422
    assert denied.get_json()["error"]["code"] == "sensitive_credential_detected"
    assert db_session.query(QualityCase).filter_by(plan_id=plan["id"]).count() == 1, "拒绝路径零新增写入"


# ---------------------------------------------------------------------------
# 权限与面隔离


def test_ai_draft_permissions_and_surface(db_session, d4_client, d4_settings) -> None:
    leader, project = _leader_project(db_session, d4_client, d4_settings, "N3A-8")
    _seed_requirements(db_session, project, leader.user, 1)

    # member（非管理）⇒ 403；未认证 ⇒ 401
    member_user = make_user(db_session, "fde_engineer")
    db_session.add(ProjectMember(project_id=project.id, user_id=member_user.id, role="member"))
    db_session.commit()
    member = ApiClient(d4_client, member_user,
                       {"Authorization": f"Bearer {issue_access_token(member_user, d4_settings)}"})
    assert member.post(f"/api/v1/projects/{project.id}/test-plans/generate-ai", json={}).status_code == 403
    assert d4_client.post(f"/api/v1/projects/{project.id}/test-plans/generate-ai", json={}).status_code == 401

    # 治理面红线钉：AI 起草路由不进 api_catalog（沿既有 quality 面先例）
    from fde_api.control.api_catalog import CATALOG

    assert not any(key.startswith("quality.") for key in CATALOG)
