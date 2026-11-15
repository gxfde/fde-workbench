"""AI 原生化 N3b 本体轮（G-04）：交付方案条目 AI 起草（任务书 §15 序 3）。

验收面（任务书 N3b DoD 逐条 + G-04 消解判据复测动作）：
- ①AI 起草入口走 ``execute_ai_prompt`` 单一入口（模块级打桩——打桩即证明
  调用面只有一个名字；J-1 白名单 DELIVERY_PLAN_DRAFT_SYSTEM_PROMPT 钉见
  test_prompt_entrypoint_gate 与本文件 test_j1_and_catalog_surface）；
- ②契约失败**整批零写入**（fail-closed 家族一致——失败路径 DeliveryPlan/
  DeliveryPlanItem 零行；成功=DB 写入是全管线最后一步）；
- ③**仅经 approved 闸发布**（G-04 判据）：AI 产物恒 draft，发布语义由既有
  review（draft→approved＋审核戳）→publish 闸机械承载——AI 不自动批准；
- ④版本化不覆盖历史（新版本=新行）；
- ⑤**确定性缺省腿零回归**：generate（确定性拼装）零改动，AI 草稿与确定性
  草稿并列共存（并列双来源）；
- ⑥溯源（N2）：delivery_plan_ai_drafted 事件带 prompt_version＋model。
输入侧纪律：requirement_key/fact_id 闭集=项目在册值，AI 越界即整批拒绝。
"""
from __future__ import annotations

import json

from test_agents_d4_harness import ApiClient, api_client, issue_access_token, make_user
from test_agents_d4_harness import d4_app, d4_client, d4_settings  # noqa: F401  (pytest fixture)
from test_delivery_plans import _generate, _leader_project, _seed_requirements
from test_discovery_extraction import _DICT_NAME, _new_project

from fde_api.plans import draft_ai as plan_draft
from fde_api.plans.models import DeliveryPlan, DeliveryPlanItem
from fde_api.workbench.models import OperationEvent, ProjectMember


def _ai_item(
    requirement_keys: list[str] | None = None,
    *,
    item_type: str = "requirement",
    title: str = "AI 起草条目",
    detail: str = "AI 起草详情：按验收标准实施。",
    priority: str = "medium",
    fact_ids: list[str] | None = None,
) -> dict:
    item: dict = {"item_type": item_type, "title": title}
    if detail is not None:
        item["detail"] = detail
    if priority is not None:
        item["priority"] = priority
    if requirement_keys is not None:
        item["requirement_keys"] = requirement_keys
    if fact_ids is not None:
        item["fact_ids"] = fact_ids
    return item


def _patch_ai(outputs: list, calls: list):
    """把 plans.draft.execute_ai_prompt 换成固定输出序列（N3a 同法）。

    序列项：dict=合法 payload（json.dumps 进 text）；str=原样文本（畸形 JSON）；
    Exception=上抛。**最后一项对后续重试粘性复用**（重放同一输出语义），每次
    调用记 kwargs（purpose/版本/执行键钉证）。
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

    original = plan_draft.execute_ai_prompt
    plan_draft.execute_ai_prompt = _fake_execute
    return original


def _unpatch_ai(original) -> None:
    plan_draft.execute_ai_prompt = original


def _ai_generate(db_session, leader, project, outputs: list):
    calls: list = []
    original = _patch_ai(outputs, calls)
    try:
        response = leader.post(f"/api/v1/projects/{project.id}/delivery-plans/generate-ai")
    finally:
        _unpatch_ai(original)
    return response, calls


def _plan_rows(db_session, project_id) -> list[DeliveryPlan]:
    return db_session.query(DeliveryPlan).filter_by(project_id=project_id).all()


# ---------------------------------------------------------------------------
# 成功路径（产出恒 draft＋溯源留痕＋确定性缺省腿并存）


def test_ai_draft_happy_path_produces_draft_with_provenance(db_session, d4_client, d4_settings) -> None:
    leader, project = _leader_project(db_session, d4_client, d4_settings, "N3B-1")
    requirements = _seed_requirements(db_session, project, leader.user, 2)
    keys = sorted(r.requirement_key for r in requirements)
    outputs = [{"items": [
        _ai_item([keys[0]], title="需求一实施"),
        _ai_item([keys[1]], title="需求二实施"),
        _ai_item(item_type="objective", title="范围快照", detail="领域对象范围"),
    ]}]
    response, calls = _ai_generate(db_session, leader, project, outputs)
    assert response.status_code == 201, response.get_json()
    data = response.get_json()["data"]
    plan = data["plan"]
    assert plan["status"] == "draft", "AI 产物恒为 draft（发布语义由人工审核闸承载）"
    assert plan["version"] == 1
    assert data["prompt_version"] == plan_draft.PLAN_DRAFT_PROMPT_VERSION
    assert data["model"] == "test-model"
    items = plan["items"]
    assert len(items) == 3
    assert [item["sort_order"] for item in items] == [0, 1, 2], "条目保持模型给出顺序（确定性归一）"
    assert items[2]["item_type"] == "objective"

    # ⑥溯源（N2）：delivery_plan_ai_drafted 事件带 prompt_version＋model
    event = db_session.query(OperationEvent).filter_by(
        target_type="delivery_plan", target_id=plan["id"], event_type="delivery_plan_ai_drafted"
    ).one()
    assert event.changes["prompt_version"] == plan_draft.PLAN_DRAFT_PROMPT_VERSION
    assert event.changes["model"] == "test-model"
    assert event.changes["item_count"] == 3

    # ①单一入口钉证：打桩 kwargs 携 purpose/prompt_version/execution_id（审计归因三元）
    assert len(calls) == 1
    assert calls[0]["purpose"] == "delivery_plan_draft"
    assert calls[0]["prompt_version"] == plan_draft.PLAN_DRAFT_PROMPT_VERSION
    assert calls[0]["execution_id"].startswith("plan-draft:")
    assert calls[0]["use_tools"] is False

    # ⑤确定性缺省腿零回归：generate 照常工作，与 AI 草稿并列共存（双来源）
    deterministic = _generate(db_session, leader, project)
    assert deterministic["version"] == 2
    assert deterministic["status"] == "draft"
    db_session.expire_all()
    assert db_session.get(DeliveryPlan, plan["id"]).status == "draft", "AI 草稿行不受确定性腿影响"


def test_ai_draft_version_bumps_and_history_kept(db_session, d4_client, d4_settings) -> None:
    leader, project = _leader_project(db_session, d4_client, d4_settings, "N3B-2")
    requirements = _seed_requirements(db_session, project, leader.user, 1)
    key = requirements[0].requirement_key
    first, _ = _ai_generate(db_session, leader, project, [{"items": [_ai_item([key])]}])
    assert first.status_code == 201
    first_id = first.get_json()["data"]["plan"]["id"]

    second, _ = _ai_generate(db_session, leader, project, [{"items": [_ai_item([key])]}])
    assert second.status_code == 201
    second_id = second.get_json()["data"]["plan"]["id"]
    assert second.get_json()["data"]["plan"]["version"] == 2
    assert second_id != first_id
    db_session.expire_all()
    assert db_session.get(DeliveryPlan, first_id).status == "draft", "历史 draft 不被覆盖（版本化不覆盖历史）"
    assert db_session.query(DeliveryPlanItem).filter_by(plan_id=first_id).count() == 1


# ---------------------------------------------------------------------------
# 契约失败整批零写入（fail-closed 家族一致）


def test_ai_draft_contract_failure_zero_write(db_session, d4_client, d4_settings) -> None:
    leader, project = _leader_project(db_session, d4_client, d4_settings, "N3B-3")
    _seed_requirements(db_session, project, leader.user, 1)
    # 畸形 JSON（重试后仍畸形）→ 409 ai_draft_contract_failed，零写入
    response, calls = _ai_generate(db_session, leader, project, ["{not json", "{also-bad"])
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "ai_draft_contract_failed"
    assert len(calls) == 2, "契约失败自动重试一次（discovery/N3a 同裁）"
    assert len(_plan_rows(db_session, project.id)) == 0
    assert db_session.query(DeliveryPlanItem).filter_by(project_id=project.id).count() == 0

    # 越界需求键（虚构键）→ 整批拒绝
    response, _ = _ai_generate(db_session, leader, project, [{"items": [_ai_item(["R-foreign99"])]}])
    assert response.status_code == 409
    assert len(_plan_rows(db_session, project.id)) == 0, "越界键整批拒绝零写入"

    # requirement 条目不带 requirement_key → 整批拒绝
    response, _ = _ai_generate(db_session, leader, project, [{"items": [_ai_item(None, item_type="requirement")]}])
    assert response.status_code == 409


def test_ai_draft_invented_fact_id_rejected(db_session, d4_client, d4_settings) -> None:
    """fact_id 闭集：项目无事实时任何 fact_id 都是虚构 ⇒ 整批拒绝零写入。"""
    leader, project = _leader_project(db_session, d4_client, d4_settings, "N3B-4")
    requirements = _seed_requirements(db_session, project, leader.user, 1)
    key = requirements[0].requirement_key
    response, _ = _ai_generate(
        db_session, leader, project,
        [{"items": [_ai_item([key]), _ai_item(item_type="risk", title="风险", fact_ids=["fake-fact-id"])]}],
    )
    assert response.status_code == 409
    assert len(_plan_rows(db_session, project.id)) == 0


def test_ai_draft_coverage_preflight_rejects_missing_requirement(db_session, d4_client, d4_settings) -> None:
    """覆盖先验（第一道）：漏一条 accepted 需求 ⇒ 整批 409（确定性腿每条需求一
    条目——AI 腿同覆盖纪律；审核闸是第二道）。"""
    leader, project = _leader_project(db_session, d4_client, d4_settings, "N3B-5")
    requirements = _seed_requirements(db_session, project, leader.user, 2)
    covered = _ai_item([requirements[0].requirement_key])
    response, _ = _ai_generate(db_session, leader, project, [{"items": [covered]}])
    assert response.status_code == 409
    assert len(_plan_rows(db_session, project.id)) == 0


def test_ai_draft_without_inputs_409_before_ai_call(db_session, d4_client, d4_settings) -> None:
    """无已批准需求且无已接受事实 ⇒ 409 no_approved_inputs（**AI 调用前**即拒
    ——与确定性生成器同码，零烧费纪律）。"""
    leader, project = _leader_project(db_session, d4_client, d4_settings, "N3B-6")

    def _fail_if_called(**kwargs):
        raise AssertionError("无输入时不得发起 AI 调用（零烧费纪律）")

    original = plan_draft.execute_ai_prompt
    plan_draft.execute_ai_prompt = _fail_if_called
    try:
        response = leader.post(f"/api/v1/projects/{project.id}/delivery-plans/generate-ai")
    finally:
        plan_draft.execute_ai_prompt = original
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "no_approved_inputs"


# ---------------------------------------------------------------------------
# G-04 判据：仅经 approved 闸发布（版本化不覆盖历史）


def test_ai_draft_publish_gate_end_to_end(db_session, d4_client, d4_settings) -> None:
    """G-04 复测动作：AI 起草草稿 → 人工 approved → published，旧版本保留。"""
    leader, project = _leader_project(db_session, d4_client, d4_settings, "N3B-7")
    requirements = _seed_requirements(db_session, project, leader.user, 1)
    key = requirements[0].requirement_key
    first, _ = _ai_generate(db_session, leader, project, [{"items": [_ai_item([key])]}])
    assert first.status_code == 201
    plan_id = first.get_json()["data"]["plan"]["id"]
    first_version = first.get_json()["data"]["plan"]["version"]

    # draft 方案不可直接发布（仅 approved 可发布——既有闸零改动）
    denied = leader.post(f"/api/v1/delivery-plans/{plan_id}/publish")
    assert denied.status_code == 409
    assert denied.get_json()["error"]["code"] == "plan_not_approved"

    # 人工审核闸：draft→approved（审核戳由人工 review 动作打——AI 不代拍板）
    reviewed = leader.patch(f"/api/v1/delivery-plans/{plan_id}/review", json={"decision": "approved"})
    assert reviewed.status_code == 200, reviewed.get_json()
    assert reviewed.get_json()["data"]["status"] == "approved"
    review_events = db_session.query(OperationEvent).filter_by(
        target_type="delivery_plan", target_id=plan_id, event_type="delivery_plan_reviewed"
    ).count()
    assert review_events == 1

    # 发布：approved→published；发布后第一版内容保留（新行不覆盖历史）
    published = leader.post(f"/api/v1/delivery-plans/{plan_id}/publish")
    assert published.status_code == 200
    assert published.get_json()["data"]["status"] == "published"

    # 第二版（AI 再起草）⇒ 新行 version+1；v1 published 行原样保留
    second, _ = _ai_generate(db_session, leader, project, [{"items": [_ai_item([key])]}])
    assert second.status_code == 201
    assert second.get_json()["data"]["plan"]["version"] == first_version + 1
    db_session.expire_all()
    assert db_session.get(DeliveryPlan, plan_id).status == "published", "旧版本行不被覆盖"


# ---------------------------------------------------------------------------
# 输出端兜底脱敏 + 凭据 fail-closed（证据红线同族）


def test_ai_draft_redaction_and_credential_fail_closed(db_session, d4_client, d4_settings) -> None:
    leader, project = _leader_project(db_session, d4_client, d4_settings, "N3B-8")
    requirements = _seed_requirements(db_session, project, leader.user, 1)
    key = requirements[0].requirement_key

    # 词典命中（种子合成名，零真实资料）⇒ 替换＋复核事件（与 discovery 第③层同构）
    tainted = _ai_item([key], title=f"{_DICT_NAME}的部署实施", detail=f"与{_DICT_NAME}对齐验收")
    response, _ = _ai_generate(db_session, leader, project, [{"items": [tainted]}])
    assert response.status_code == 201, response.get_json()
    plan = response.get_json()["data"]["plan"]
    stored = db_session.get(DeliveryPlanItem, plan["items"][0]["id"])
    assert _DICT_NAME not in stored.title, "输出端兜底脱敏必须替换词典命中名"
    redaction_events = db_session.query(OperationEvent).filter_by(
        target_type="delivery_plan", target_id=plan["id"], event_type="delivery_plan_redaction_review"
    ).count()
    assert redaction_events == 1
    # 盲审追批零真名换代：事件账条目只存指纹（＋疑似哨兵），零真名原文。
    review_event = db_session.query(OperationEvent).filter_by(
        target_type="delivery_plan", target_id=plan["id"], event_type="delivery_plan_redaction_review"
    ).first()
    from fde_api.guidance.redaction import redaction_name_hash as _rnh

    assert any(e.get("name_hash") == _rnh(_DICT_NAME) for e in review_event.changes["entries"])
    assert all(not e.get("name") for e in review_event.changes["entries"]), "复核事件账零真名"

    # 凭据串命中 ⇒ 422 整批拒绝＋零写入（fail-closed：凭据不落库）
    cred_item = _ai_item([key], detail="部署时使用密钥: abcdefghijkl1234")
    denied, _ = _ai_generate(db_session, leader, project, [{"items": [cred_item]}])
    assert denied.status_code == 422
    assert denied.get_json()["error"]["code"] == "sensitive_credential_detected"
    assert len(_plan_rows(db_session, project.id)) == 1, "拒绝路径零新增写入"


# ---------------------------------------------------------------------------
# 权限与面隔离


def test_ai_draft_permissions_and_surface(db_session, d4_client, d4_settings) -> None:
    leader, project = _leader_project(db_session, d4_client, d4_settings, "N3B-9")
    _seed_requirements(db_session, project, leader.user, 1)

    # member（非管理）⇒ 403；未认证 ⇒ 401
    member_user = make_user(db_session, "fde_engineer")
    db_session.add(ProjectMember(project_id=project.id, user_id=member_user.id, role="member"))
    db_session.commit()
    member = ApiClient(d4_client, member_user,
                       {"Authorization": f"Bearer {issue_access_token(member_user, d4_settings)}"})
    assert member.post(f"/api/v1/projects/{project.id}/delivery-plans/generate-ai").status_code == 403
    assert d4_client.post(f"/api/v1/projects/{project.id}/delivery-plans/generate-ai").status_code == 401

    # 治理面红线钉：AI 起草路由不进 api_catalog（沿 quality/N3a 先例）；
    # N5（G-02）起 workflows.run_start（发起 run 确认类）例外收编——起草类仍禁。
    from fde_api.control.api_catalog import CATALOG

    assert not any(key.startswith("plans.") for key in CATALOG)
    assert not any(key.startswith("workflows.") and key != "workflows.run_start" for key in CATALOG)
