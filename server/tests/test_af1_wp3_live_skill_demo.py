"""AF1-WP3：Skill 驱动的「SOP/字典材料→候选生成→预检修正→pass」真模型实跑。

与 test_af1_wp2/af1_live 演示的差异：候选不由提示直接给定，而由真模型**依据
builtin Skill（ontology-candidate-engineering）的工程规则面**从合成 SOP+字段
字典材料生成（T1-01 最小切片：一对象+一属性），材料数据类型列是口语词 text
→首轮真服务 violations→按词表修正→verdict=pass。四分/溯源/防录放逐断言。

防录放口径（评审 verification-gap⑥）：entity_key 注 per-run 随机后缀**抗离线
重放**；不抗规则感知的在线仿冒——真实性剩余锚=usage 记账（本进程产生，无外部
凭证锚），口径如实钉于此注释。

治理「零物化」复查：演示全程模型仅触 dry_validate（白名单闭集），收尾对真服务
working-set 面只读 GET 复核实体行仍为空（评审 verification-gap③）。

运行条件与复现同 tests/test_af1_live_demo.py（af1_live marker +
FDE_AF1_LIVE_DEMO=1，CI 恒跳过；本机 Ollama qwen3:14b + ontology-service 源码树）。
"""
from __future__ import annotations

import os
import secrets
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy.orm import Session

from fde_api.control.ai_tool_loop import direct_tool_completion
from fde_api.control.builtin_skills import SKILLS
from fde_api.control.model_preferences import resolve_model_preference
from fde_api.integrations.models import ProjectOntologyBinding
from fde_api.integrations.ontology_client import OntologyClient, build_context_header
from fde_api.workbench.models import Project

from test_af1_live_demo import DEMO_ACTOR, OLLAMA_MODEL, _require_ollama
from test_af1_live_demo import live_ontology_service  # noqa: F401  (fixture 复用)
from test_gates_api import admin_client, gate_project  # noqa: F401  (fixture 供给方)

pytestmark = [
    pytest.mark.af1_live,
    pytest.mark.skipif(
        os.environ.get("FDE_AF1_LIVE_DEMO", "").strip() != "1",
        reason="requires FDE_AF1_LIVE_DEMO=1 (real Ollama + local ontology-service)",
    ),
]

SKILL_KEY = "ontology-candidate-engineering"


def _skill_instructions() -> str:
    for item in SKILLS:
        if item[0] == SKILL_KEY:
            return item[4]
    raise AssertionError(f"{SKILL_KEY}: builtin 清单缺失——WP3 Skill 未就位")


def _seeded_instructions(db_session: Session) -> str:
    """从种子落库后的 DB 行读回规则面（评审 F5：不绕开种子/分发链——demo 用
    的是 DB 里真实的 SkillVersion.instructions_text，管理员改文本即随之漂移）。"""
    from sqlalchemy import select

    from fde_api.control.builtin_skills import seed_public_skills
    from fde_api.control.models import SkillDefinition, SkillVersion

    seed_public_skills()
    row = db_session.scalar(select(SkillDefinition).where(
        SkillDefinition.namespace_key == "public", SkillDefinition.skill_key == SKILL_KEY))
    assert row is not None and row.status == "published", "WP3 Skill 未落种子"
    version = db_session.scalar(select(SkillVersion).where(
        SkillVersion.skill_id == row.id,
        SkillVersion.version_number == row.current_version_number))
    assert version is not None
    return version.instructions_text


def _seed_published_empty_version(live: dict[str, Any], org_id: str) -> tuple[str, str]:
    """T1-01 初始状态的最小可行形：空候选首发 1.0.0（工作集空、零实体行）。

    dry_validate 钉版必填（S-13/N-DV-3）——空本体无处钉版，故发布空 CS 取版本
    真身；服务实例为测试独占（单库单本体），不触 serialize_workspace 空快照
    哈希全局唯一碰撞面（WP2 ndv3 结论）。候选由模型从材料生成，不进种子。
    """
    def _post(path: str, *, actor: str, idem: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = {
            "X-API-Key": live["api_key"],
            "X-FDE-Context": build_context_header(actor, org_id, "af1-wp3-demo", live["signing_key"]),
            "X-Idempotency-Key": idem,
        }
        return requests_post_json(live, path, headers, body)

    ontology = _post("/api/v1/ontologies", actor=DEMO_ACTOR, idem="af1-wp3-onto",
                     body={"domain_key": "af1_wp3_demo", "title": "AF1 WP3 Skill Demo Ontology"})
    change_set = _post(f"/api/v1/ontologies/{ontology['id']}/change-sets", actor=DEMO_ACTOR,
                       idem="af1-wp3-cs", body={"title": "CS af1-wp3-empty", "proposed_json": []})
    _post(f"/api/v1/change-sets/{change_set['id']}/validate", actor=DEMO_ACTOR, idem="af1-wp3-va")
    for index, (role, actor) in enumerate(
        (("business_owner", "bo-1"), ("model_consultant", "mc-1"), ("data_owner", "do-1"))
    ):
        _post(f"/api/v1/change-sets/{change_set['id']}/approvals", actor=actor,
              idem=f"af1-wp3-ap-{index}", body={"role": role, "decision": "approved"})
    published = _post(f"/api/v1/change-sets/{change_set['id']}/publish", actor=DEMO_ACTOR,
                      idem="af1-wp3-pb", body={"version": "1.0.0"})
    return str(ontology["id"]), str(published["id"])


def requests_post_json(
    live: dict[str, Any], path: str, headers: dict[str, str], body: dict[str, Any] | None
) -> dict[str, Any]:
    import requests

    resp = requests.post(f"{live['base_url']}{path}", headers=headers, json=body, timeout=15)
    assert resp.status_code in (200, 201), f"{path}: {resp.status_code} {resp.text}"
    return resp.json()


def test_live_skill_driven_candidate_generation_demo(
    gate_project, live_ontology_service: dict[str, Any],
    db_session: Session, settings, app, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Skill 规则面驱动：材料→生成候选→violations→修正→pass，证据可溯源。"""
    _require_ollama()
    project, _gates_url, leader = gate_project
    project_row = db_session.get(Project, project["id"])
    assert project_row is not None and project_row.org_id is not None
    org_id = project_row.org_id

    ontology_id, version_id = _seed_published_empty_version(live_ontology_service, org_id)
    binding = ProjectOntologyBinding(
        org_id=org_id,
        project_id=project["id"],
        ontology_id=ontology_id,
        pinned_version_id=version_id,
        pinned_version="1.0.0",
        binding_role="primary",
        status="active",
        active_marker="active",
        bound_by_user_id=leader.user.id,
    )
    db_session.add(binding)
    db_session.commit()

    monkeypatch.setattr(settings, "ontology_enabled", True, raising=False)
    monkeypatch.setattr(settings, "ontology_base_url", live_ontology_service["base_url"], raising=False)
    monkeypatch.setattr(
        settings, "ontology_api_key", SecretStr(live_ontology_service["api_key"]), raising=False)
    monkeypatch.setattr(
        settings, "ontology_signing_key", SecretStr(live_ontology_service["signing_key"]), raising=False)
    from test_af1_live_demo import OLLAMA_BASE

    monkeypatch.setattr(settings, "ai_selfhosted_base_url", f"{OLLAMA_BASE}/v1", raising=False)
    monkeypatch.setattr(settings, "ai_selfhosted_model", OLLAMA_MODEL, raising=False)

    dry_calls: list[dict[str, Any]] = []
    original = OntologyClient.dry_validate_change_set

    def _spy(self: OntologyClient, **kwargs: Any) -> dict[str, Any]:
        response = original(self, **kwargs)
        dry_calls.append({"proposed_json": kwargs["proposed_json"], "response": response})
        return response

    monkeypatch.setattr(OntologyClient, "dry_validate_change_set", _spy)

    # 合成 SOP+字段字典（母案语义最小切片；entity_key 注 per-run 随机后缀防录放；
    # 单位行标注字典未提供→缺失纪律与 unresolved_questions 行为钉，评审 verification-gap②）
    serial_key = f"equipment_serial_no_{secrets.token_hex(4)}"
    sop_quote = "生产部按批次管理物料质量，设备台账记录每台设备的序列号与所属产线。"
    material = (
        "【客户 SOP 摘录（授权材料，可逐字引用）】\n"
        f"「{sop_quote}」——《设备管理 SOP》§2\n"
        "【字段字典（授权材料，类型列为客户原文）】\n"
        f"- 字段标识：{serial_key}\n"
        "- 显示名：设备序列号\n"
        "- 所属对象：equipment（设备台账）\n"
        "- 数据类型：text\n"
        "- 单位：（字典未提供，需人工确认）\n"
        "- 来源：《字段字典 v2》L12\n"
    )

    # 规则面从种子落库后的 DB 行读回（评审 F5：不绕开种子/分发链）
    system_rules = _seeded_instructions(db_session)
    # qwen3:14b thinking 在大 system_prompt+tools 下易烧尽预算返回空 content
    # （实测；WP1 演示无 system_prompt 即正常）——Skill 规则面并入 user prompt，
    # 消费语义不变（规则面同源注入，非假件）。
    prompt = (
        "【工程规则（本体候选工程 Skill，以下规则全部适用）】\n"
        f"{system_rules}\n"
        "【任务】\n"
        "依据以下授权材料为本体生成候选，并按上述规则完成预检修正循环：\n"
        f"{material}\n"
        "任务：生成两个候选——对象类型 equipment 与其属性 "
        f"{serial_key}（数据类型列按字典原文逐字填写，不得预先替换为词表词）。"
        "每个候选的 payload 必须携带 evidence_quote（逐字摘自上面材料）与 source_location，"
        "fact_or_inference 按材料明示标注；字典未给出的信息（如单位）按规则列入候选的 "
        "unresolved_questions 待人工确认，不得默认补值。"
        "生成后立即预检，violations 按明细修正后复检，直到 verdict=pass，"
        "然后用一两句话报告最终结果与修正内容，不要再调用工具。\n"
        f"上下文：project_id={project['id']} binding_id={binding.id}"
    )

    with app.app_context():
        actor = leader.user
        model = resolve_model_preference(db_session, actor.id)
        assert model["id"] == "system-selfhosted", model["id"]
        text, usage, trace = direct_tool_completion(
            model=model, prompt=prompt, user=actor, project_id=project["id"],
            execution_id="af1-wp3-demo-1",
            max_tool_rounds=6, capabilities=["ontology.read"],
            allowed_tools=["ontology_dry_validate"],
        )

    assert usage["complete"] is True
    assert usage["calls"] and usage["calls"][0]["model"] == OLLAMA_MODEL

    # 失败→修正闭环（材料口语词触发真服务违规）；断言附模型行为诊断。
    # 违规轮定位取「首个 violations 轮」（评审 F6：不钉死它必须是第一次调用）
    assert len(dry_calls) >= 2, (
        f"dry_validate 调用次数不足：{len(dry_calls)}；trace={trace}；"
        f"final_text={text[:400]!r}"
    )
    violation_rounds = [
        call for call in dry_calls if call["response"]["verdict"] == "violations"
    ]
    assert violation_rounds, f"全程无违规轮：{[c['response']['verdict'] for c in dry_calls]}"
    first_violation = violation_rounds[0]
    assert any(
        v["check"] == "data_type" for v in first_violation["response"]["violations"]
    ), first_violation["response"]["violations"]
    last = dry_calls[-1]
    assert last["response"]["verdict"] == "pass", last["response"]

    # 防录放：违规轮候选必须携带本 run 随机实体键（录放假件无从预知）
    violation_keys = [item["entity_key"] for item in first_violation["proposed_json"]]
    assert serial_key in violation_keys, violation_keys

    items_last = last["proposed_json"]
    # 生成自材料：按 entity_key 定位目标候选（评审 F3：不钉死集合等值——模型按
    # 材料溯源多建合规候选时记录而非误杀）
    prop_last = next(
        (i for i in items_last
         if i["entity_type"] == "property_definitions" and i["entity_key"] == serial_key),
        None,
    )
    assert prop_last is not None, f"修正后候选缺目标属性：{[i['entity_key'] for i in items_last]}"
    assert prop_last["payload"]["object_type_id"] == "equipment"
    assert prop_last["payload"]["data_type"] == "string"
    assert any(
        i["entity_type"] == "object_types" and i["entity_key"] == "equipment"
        for i in items_last
    ), [i["entity_key"] for i in items_last]
    extras = [i["entity_key"] for i in items_last
              if i["entity_key"] not in (serial_key, "equipment")]
    if extras:
        print(f"[af1-wp3-live] 模型超出指令的多余候选（材料可溯源即合规，仅记录）：{extras}")

    # 证据溯源钉（Skill 纪律）：evidence_quote 逐字来自材料、fact_or_inference 合法
    for item in items_last:
        if item["entity_key"] not in (serial_key, "equipment"):
            continue
        payload = item["payload"]
        quote = str(payload.get("evidence_quote") or "")
        assert quote and quote in material, (
            f"{item['entity_key']}: evidence_quote 不可溯源：{quote!r}"
        )
        assert payload.get("fact_or_inference") in ("fact", "inference"), payload

    # 缺失纪律行为钉（评审 verification-gap②）：字典未提供单位→unresolved_questions
    # 至少一处非空（缺失/不编造/决策单三纪律合一）
    unresolved_any = [
        item["entity_key"] for item in items_last
        if item["payload"].get("unresolved_questions")
    ]
    assert unresolved_any, "材料缺失项（单位）未按纪律列入 unresolved_questions"

    # trace 下界（400 拒收轮不误杀）+ 治理：工具白名单闭集（仅 dry_validate 面）
    trace_dry = [entry for entry in trace if entry["tool"] == "ontology_dry_validate"]
    assert len(trace_dry) >= len(dry_calls) >= 2
    assert text.strip()

    # 零物化复查（评审 verification-gap③）：全程只触 dry_validate——真服务
    # working-set 实体行仍为空（种子=空候选首发；只读 GET）
    check_headers = {
        "X-API-Key": live_ontology_service["api_key"],
        "X-FDE-Context": build_context_header(
            DEMO_ACTOR, org_id, "af1-wp3-demo", live_ontology_service["signing_key"]),
    }
    import requests as _requests

    ws_resp = _requests.get(
        f"{live_ontology_service['base_url']}/api/v1/ontologies/{ontology_id}/object-types",
        headers=check_headers, timeout=15,
    )
    assert ws_resp.status_code == 200, ws_resp.text
    ws_body = ws_resp.json()
    ws_items = ws_body.get("items", ws_body) if isinstance(ws_body, dict) else ws_body
    assert not ws_items, f"演示后 working-set 非空——零物化失守：{ws_items}"

    print("\n[af1-wp3-live] rounds(dry_validate) =", len(dry_calls))
    for index, call in enumerate(dry_calls, start=1):
        verdict = call["response"]["verdict"]
        checks = [v["check"] for v in call["response"].get("violations", [])]
        print(f"[af1-wp3-live] round {index}: verdict={verdict} checks={checks}")
    print("[af1-wp3-live] final answer:", text.strip()[:200])
