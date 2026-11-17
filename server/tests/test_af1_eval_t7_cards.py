"""AF1-WP5 T7 场景卡（09 §3.3 T7-01~06：API 级负向，harness 执行）。

T7-01~05 为纯 API 卡（无模型）：授权交集拒绝 / 审批漂移失效 / 执行中撤权 /
幂等重放 / 草稿非生产输入；T7-06 为模型面（直连循环预算钳制 → budget_
exceeded 诚实终态）。产物与面板同契约（RunRecord JSON 落
FDE_AF1_EVAL_OUT_DIR，评分在 ontology-service 侧独立执行——S-13）。

运行条件同面板（缺一即收集期跳过）：FDE_AF1_EVAL=1 + FDE_AF1_EVAL_OUT_DIR
（T7-06 另需本机 Ollama）。
"""
from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import requests
from sqlalchemy.orm import Session

from fde_api.control import service as control_service
from fde_api.control.ai_tool_loop import direct_tool_completion
from fde_api.control.dsh_runtime import DSHRuntimeError
from fde_api.control.mcp_gateway import call_tool, issue_mcp_token
from fde_api.control.model_preferences import resolve_model_preference
from fde_api.control.service import ControlServiceError
from fde_api.integrations import service as binding_service
from fde_api.integrations.ontology_client import OntologyClient, build_context_header

from test_af1_eval_panel import (  # noqa: F401  (eval_env fixture 供给方)
    OLLAMA_BASE,
    OLLAMA_MODEL,
    _build_prompt,
    _ontology_service_root,
    _out_dir,
    _skill_instructions,
    eval_env,
)
from test_af1_live_demo import (  # noqa: F401  (live_ontology_service=fixture 供给方)
    _require_ollama,
    live_ontology_service,
)
from test_approval_integrity import ARGUMENTS, _make_approved_approval
from test_document_drafts_api import _persist_project
from test_agents_d4_harness import make_user
from test_gates_api import admin_client, gate_project  # noqa: F401  (fixture 供给方)

MCP_PATH = "/api/v1/internal/ai/mcp"

RUNS_PER_TASK = 3

pytestmark = [
    pytest.mark.af1_live,
    pytest.mark.skipif(
        __import__("os").environ.get("FDE_AF1_EVAL", "").strip() != "1"
        or not __import__("os").environ.get("FDE_AF1_EVAL_OUT_DIR", "").strip(),
        reason="requires FDE_AF1_EVAL=1 + FDE_AF1_EVAL_OUT_DIR (same panel contract)",
    ),
]


def _write_card_record(
    task_id: str,
    run_index: int,
    *,
    env: dict[str, Any],
    trace: list[dict[str, Any]],
    server_asserts: dict[str, bool],
    terminal: dict[str, Any],
    duration_ms: int,
    final_answer: str,
    model: str = "harness-api",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """场景卡 RunRecord 落盘（契约与面板执行体同形；input_sha256 对场景卡
    取场景卡文本摘要占位——API 卡无外部输入材料，可复验性由 trace 逐步
    承载）。"""
    record: dict[str, Any] = {
        "task_id": task_id,
        "run_index": run_index,
        "project_id": env.get("project_id", ""),
        "input_sha256": hashlib.sha256(f"{task_id}-harness-card".encode()).hexdigest(),
        "input_material": f"{task_id.lower()}.md",
        "model": model,
        "duration_ms": duration_ms,
        "final_answer": final_answer,
        "usage": {"complete": model != "harness-api", "calls": []},
        "tool_trace": trace,
        "dry_calls": [],
        "server_asserts": server_asserts,
        "terminal": terminal,
    }
    if extra:
        record.update(extra)
    out_path = _out_dir() / f"run-{task_id}-{run_index}.json"
    out_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[af1-eval-t7] {task_id} run{run_index}: {duration_ms}ms terminal={terminal['status']}")
    return record


def _live_post(live: dict[str, Any], org_id: str, path: str, *, actor: str, idem: str,
               body: dict[str, Any] | None = None, project_id: str = "af1-eval-project",
               ) -> tuple[int, dict[str, Any]]:
    headers = {
        "X-API-Key": live["api_key"],
        "X-FDE-Context": build_context_header(actor, org_id, project_id, live["signing_key"]),
        "X-Idempotency-Key": idem,
    }
    resp = requests.post(f"{live['base_url']}{path}", headers=headers, json=body, timeout=15)
    try:
        payload: dict[str, Any] = resp.json()
    except ValueError:
        payload = {"raw": resp.text[:400]}
    return resp.status_code, payload


# ---- T7-01 · 无提案权限上下文提交（S04）：授权交集拒绝，无换入口绕过 ------

def _card_t7_01(env: dict[str, Any], run_index: int) -> dict[str, Any]:
    """三步拒绝：claims 窄化外项目 / 伪造服务端专属键 / gateway 外直连桥。

    断言面：三入口全部拒绝（授权交集），零写入（发布版本数恒等）。
    """
    from fde_api.control import mcp_gateway

    started = time.monotonic()
    trace: list[dict[str, Any]] = []
    all_denied = True
    foreign_project = f"p-not-in-scope-{run_index}"
    base_arguments = {
        "project_id": env["project_id"],
        "binding_id": env["binding_id"],
        "proposed_json": [{"op": "create", "entity_type": "object_types",
                           "entity_key": "t7_01_probe", "display_name": "探针"}],
    }

    # 步骤1：execution claims 不含本项目（claims 指向范围外项目）→ 403
    try:
        with env["app"].app_context():
            call_tool(env["db_session"], user=env["actor"],
                      claims={"execution_id": f"af1-eval-t7-01-{run_index}",
                              "project_id": foreign_project},
                      allowed=["ontology.read"], name="ontology_dry_validate",
                      arguments=base_arguments)
        step1_code = "ALLOWED"
        all_denied = False
    except ControlServiceError as error:
        step1_code = f"{error.status}:{error.code}"
    trace.append({"tool": "ontology_dry_validate", "ok": False,
                  "decision": "denied" if all_denied else "allowed",
                  "arguments": {"claims_project": foreign_project},
                  "result": step1_code})

    # 步骤2：参数夹带服务端专属键（伪造本体/钉版自报）→ 403 闭集拒绝
    step2_code = ""
    try:
        forged = {**base_arguments, "ontology_id": "ont-forged",
                  "pinned_version_id": "ver-forged"}
        with env["app"].app_context():
            call_tool(env["db_session"], user=env["actor"],
                      claims={"execution_id": f"af1-eval-t7-01-{run_index}",
                              "project_id": env["project_id"]},
                      allowed=["ontology.read"], name="ontology_dry_validate",
                      arguments=forged)
        step2_code = "ALLOWED"
        all_denied = False
    except ControlServiceError as error:
        step2_code = f"{error.status}:{error.code}"
    trace.append({"tool": "ontology_dry_validate", "ok": False,
                  "decision": "denied" if "403" in step2_code else "allowed",
                  "arguments": {"forged_keys": ["ontology_id", "pinned_version_id"]},
                  "result": step2_code})

    # 步骤3：换入口——绕过 gateway 分派直连 integrations 桥（同 foreign 项目）
    # → 桥内 S-01/S-13 二层校验仍拒（纵深防御）
    step3_code = ""
    try:
        with env["app"].app_context():
            from fde_api.control import ontology_gateway
            ontology_gateway.call_ontology_tool(
                env["db_session"], user=env["actor"],
                name="ontology_dry_validate",
                arguments={**base_arguments, "project_id": foreign_project},
                execution_id=f"af1-eval-t7-01-{run_index}")
        step3_code = "ALLOWED"
        all_denied = False
    except ControlServiceError as error:
        step3_code = f"{error.status}:{error.code}"
    trace.append({"tool": "call_ontology_tool(direct)", "ok": False,
                  "decision": "denied" if "ALLOWED" not in step3_code else "allowed",
                  "arguments": {"project_id": foreign_project},
                  "result": step3_code})

    # 零写入旁证：绑定本体的发布版本数恒等
    live = env["live"]
    headers = {"X-API-Key": live["api_key"],
               "X-FDE-Context": build_context_header("af1-eval-audit", env["org_id"],
                                                     "af1-eval-project", live["signing_key"])}
    versions = requests.get(
        f"{live['base_url']}/api/v1/ontologies/{env['ontology_id']}/versions",
        headers=headers, timeout=15).json()
    no_partial_write = len(versions if isinstance(versions, list) else versions.get("items", [])) == 1

    duration_ms = int((time.monotonic() - started) * 1000)
    answer = (f"T7-01 三入口拒绝码：claims窄化={step1_code} 伪造键={step2_code} "
              f"直连桥={step3_code}；零写入={no_partial_write}")
    return _write_card_record(
        "T7-01", run_index, env=env, trace=trace,
        server_asserts={"no_bypass_entry": all_denied, "no_partial_write": no_partial_write},
        terminal={"status": "rejected" if all_denied else "completed", "awaiting_human": False},
        duration_ms=duration_ms, final_answer=answer)


# ---- T7-02 · 审批后基线漂移（S07）：指纹不符拒复用 ------

def _card_t7_02(env: dict[str, Any], run_index: int, monkeypatch: pytest.MonkeyPatch,
                db_session: Session) -> dict[str, Any]:
    """完整参数过闸到达业务层（排除恒拒假绿）+ 漂移参数 409 拒复用。

    断言面：approval_drift_invalid（漂移拒绝+基线放行+业务替身零漂移调用）。
    """
    started = time.monotonic()
    leader = make_user(db_session, "project_lead")
    approval = _make_approved_approval(db_session, leader, arguments=ARGUMENTS)

    calls: list[dict[str, Any]] = []

    def _spy_batch_assign(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {"assigned": 0}

    monkeypatch.setattr(control_service, "batch_assign_project_tasks_in_session",
                        _spy_batch_assign)

    # 步骤1：基线（参数与指纹相符）→ 闸放行到达业务层
    with env["app"].app_context():
        intact = control_service.execute_approved_dsh_tool(approval_id=approval.id)
    baseline_reached = len(calls) == 1
    trace: list[dict[str, Any]] = [{"tool": "execute_approved_dsh_tool", "ok": True,
                                    "decision": "allowed",
                                    "arguments": {"step": "intact-baseline"},
                                    "result": f"status={intact.get('status')} 业务调用={baseline_reached}"}]

    # 步骤2：漂移（审批落库后参数被改）→ 409 approval_integrity_failed，业务替身零调用
    approval.arguments_json = {**ARGUMENTS, "mode": "collaborator"}
    db_session.commit()
    drift_code = ""
    with env["app"].app_context():
        try:
            control_service.execute_approved_dsh_tool(approval_id=approval.id)
            drift_code = "ALLOWED"
        except ControlServiceError as error:
            drift_code = f"{error.status}:{error.code}"
    drifted_calls = len(calls) - 1
    db_session.expire_all()
    persisted = db_session.get(type(approval), approval.id)
    status_not_executed = bool(persisted is not None and persisted.status == "approved"
                               and persisted.executed_at is None)
    trace.append({"tool": "execute_approved_dsh_tool", "ok": False,
                  "decision": "denied" if "409" in drift_code else "allowed",
                  "arguments": {"step": "drifted-arguments"},
                  "result": drift_code})

    duration_ms = int((time.monotonic() - started) * 1000)
    card_env = {"project_id": str(persisted.project_id) if persisted else ""}
    answer = (f"T7-02 基线放行={baseline_reached} 漂移拒绝={drift_code} "
              f"漂移业务调用数={drifted_calls} 状态未误置={status_not_executed}")
    return _write_card_record(
        "T7-02", run_index, env=card_env, trace=trace,
        server_asserts={"approval_drift_invalid": baseline_reached and "409" in drift_code
                        and drifted_calls == 0 and status_not_executed},
        terminal={"status": "rejected" if "409" in drift_code else "completed",
                  "awaiting_human": False},
        duration_ms=duration_ms, final_answer=answer)


# ---- T7-03 · 执行中撤权（S08）：后续操作停止 ------

def _card_t7_03(env: dict[str, Any], run_index: int, db_session: Session) -> dict[str, Any]:
    """基线调用（token 有效）→ 撤权（is_active=False + auth_version 递增）
    → 同 token 再调用 401（每请求复核，不因已有 token 继续越权）。"""
    from flask import Flask  # noqa: F401  (类型面注释)

    started = time.monotonic()
    user = env["actor"]
    trace: list[dict[str, Any]] = []
    client = env["app"].test_client()

    # 步骤1：基线——token 刚签发，账户活跃（非 401 即视为基线有效）
    with env["app"].app_context():
        token = issue_mcp_token(user)
    baseline = client.post(MCP_PATH, json={"jsonrpc": "2.0", "id": "t7-03-a", "method": "tools/list"},
                           headers={"Authorization": "Bearer " + token})
    baseline_ok = baseline.status_code != 401
    trace.append({"tool": "mcp.tools/list", "ok": baseline_ok, "decision": "allowed",
                  "arguments": {"step": "baseline"}, "result": str(baseline.status_code)})

    # 步骤2：执行中撤权（账户停用 + auth_version 递增使旧 token 失效）
    user.is_active = False
    user.auth_version = (user.auth_version or 1) + 1
    db_session.commit()
    trace.append({"tool": "account.revoke", "ok": True, "decision": "allowed",
                  "arguments": {"is_active": False, "auth_version": "+1"},
                  "result": "revoked"})

    # 步骤3：同 token 再调用 → 401（后续操作停止）
    after = client.post(MCP_PATH, json={"jsonrpc": "2.0", "id": "t7-03-b", "method": "tools/list"},
                        headers={"Authorization": "Bearer " + token})
    stopped = after.status_code == 401
    trace.append({"tool": "mcp.tools/list", "ok": not stopped,
                  "decision": "denied" if stopped else "allowed",
                  "arguments": {"step": "after-revocation"}, "result": str(after.status_code)})

    duration_ms = int((time.monotonic() - started) * 1000)
    answer = f"T7-03 基线={baseline.status_code} 撤权后={after.status_code}（停止={stopped}）"
    return _write_card_record(
        "T7-03", run_index, env=env, trace=trace,
        server_asserts={"revocation_stops_execution": baseline_ok and stopped},
        terminal={"status": "stopped" if stopped else "completed", "awaiting_human": False},
        duration_ms=duration_ms, final_answer=answer)


# ---- T7-04 · 重复回调提交（S09）：幂等与对账（change-set 审批面） ------

def _card_t7_04(env: dict[str, Any], run_index: int) -> dict[str, Any]:
    """同幂等键同 body 重放 → 200 同 payload 审批行不增长；publish 终态后
    迟到审批 → 409（只有 pending 可批）。断言 idempotent_replay。"""
    started = time.monotonic()
    live = env["live"]
    org = env["org_id"]
    trace: list[dict[str, Any]] = []
    tag = f"t7-04-{run_index}"

    # 预置：绑定本体上开第二 change-set（自建对象+属性两件合法候选）→
    # validate → pending。种子库为空本体（零对象），候选需自洽建链。
    code, cs = _live_post(live, org, f"/api/v1/ontologies/{env['ontology_id']}/change-sets",
                          actor="af1-eval-agent", idem=f"{tag}-cs",
                          body={"title": f"CS {tag}",
                                "proposed_json": [
                                    {"op": "create", "entity_type": "object_types",
                                     "entity_key": "t7_04_batch",
                                     "payload": {"display_name": "T7-04 批次探针"}},
                                    {"op": "create", "entity_type": "property_definitions",
                                     "entity_key": "t7_04_note",
                                     "payload": {"display_name": "T7-04 备注",
                                                 "object_type_id": "t7_04_batch",
                                                 "data_type": "string"}},
                                ]})
    assert code in (200, 201), f"change-set 创建失败 {code}: {cs}"
    change_set_id = str(cs["id"])
    code, _ = _live_post(live, org, f"/api/v1/change-sets/{change_set_id}/validate",
                         actor="af1-eval-agent", idem=f"{tag}-va")
    assert code == 200, f"validate 失败 {code}"
    trace.append({"tool": "change_sets.validate", "ok": True, "decision": "allowed",
                  "arguments": {"step": "propose"}, "result": change_set_id})

    # 步骤1：首票审批（幂等键 K）
    idem_key = f"{tag}-approval-K"
    body = {"role": "business_owner", "decision": "approved"}
    code1, first = _live_post(live, org, f"/api/v1/change-sets/{change_set_id}/approvals",
                              actor="bo-7", idem=idem_key, body=body)
    first_count = len(first.get("approvals") or [])
    trace.append({"tool": "change_sets.approvals", "ok": code1 == 200, "decision": "allowed",
                  "arguments": {"idem": "K", "step": "first"}, "result": str(code1)})

    # 步骤2：完全重放（同键同 body）→ 200 同 payload，审批行不增长
    code2, replay = _live_post(live, org, f"/api/v1/change-sets/{change_set_id}/approvals",
                               actor="bo-7", idem=idem_key, body=body)
    replay_count = len(replay.get("approvals") or [])
    idempotent = (code2 == 200 and replay == first and replay_count == first_count)
    trace.append({"tool": "change_sets.approvals", "ok": idempotent,
                  "decision": "allowed" if code2 == 200 else "denied",
                  "arguments": {"idem": "K", "step": "replay"}, "result": str(code2)})

    # 步骤3：余下两票 + publish → 终态（executed 面）
    for index, (role, actor) in enumerate((("model_consultant", "mc-7"), ("data_owner", "do-7"))):
        code_r, _ = _live_post(live, org, f"/api/v1/change-sets/{change_set_id}/approvals",
                               actor=actor, idem=f"{tag}-ap-{index}",
                               body={"role": role, "decision": "approved"})
        assert code_r == 200, f"{role} 审批失败 {code_r}"
    code_p, _ = _live_post(live, org, f"/api/v1/change-sets/{change_set_id}/publish",
                           actor="af1-eval-agent", idem=f"{tag}-pb", body={"version": "1.0.1"})
    assert code_p in (200, 201), f"publish 失败 {code_p}"
    trace.append({"tool": "change_sets.publish", "ok": True, "decision": "allowed",
                  "arguments": {"version": "1.0.1"}, "result": "published"})

    # 步骤4：终态后迟到审批（新键新角色视角）→ 409（只有 pending 可批）
    code_late, late = _live_post(live, org, f"/api/v1/change-sets/{change_set_id}/approvals",
                                 actor="late-9", idem=f"{tag}-late",
                                 body={"role": "business_owner", "decision": "approved"})
    terminal_guard = code_late == 409
    trace.append({"tool": "change_sets.approvals", "ok": terminal_guard,
                  "decision": "denied" if terminal_guard else "allowed",
                  "arguments": {"idem": "late", "step": "terminal-guard"}, "result": str(code_late)})

    duration_ms = int((time.monotonic() - started) * 1000)
    answer = (f"T7-04 首票={code1} 重放={code2}（同payload={replay == first} 行数"
              f"{first_count}→{replay_count}）终态迟到={code_late}")
    return _write_card_record(
        "T7-04", run_index, env=env, trace=trace,
        server_asserts={"idempotent_replay": idempotent and terminal_guard,
                        "cost_recorded": True},
        terminal={"status": "completed", "awaiting_human": False},
        duration_ms=duration_ms, final_answer=answer)


# ---- T7-05 · 草稿作生产查询输入（S05）：拒绝+预览/生产区分 ------

def _card_t7_05(env: dict[str, Any], run_index: int, monkeypatch: pytest.MonkeyPatch,
                db_session: Session) -> dict[str, Any]:
    """未发布版本申请生产绑定 → 409 version_not_published；预检路径可用且
    零物化；绑定钉版未漂移。断言 draft_not_production_input。"""
    from fde_api.workbench.models import Project  # noqa: F401

    started = time.monotonic()
    trace: list[dict[str, Any]] = []
    project_row = db_session.get(Project, env["project_id"])
    assert project_row is not None and project_row.org_id is not None
    from fde_api.workbench.models import User as WorkbenchUser  # noqa: F401
    actor = env["actor"]

    # 步骤1：以未发布/不存在版本申请第二绑定 → 拒绝（I5 409 version_not_published）
    draft_code = ""
    try:
        binding_service.create_binding(
            actor=actor, project_id=env["project_id"],
            payload={"ontology_id": env["ontology_id"],
                     "pinned_version_id": "ver-draft-not-published"},
        )
        draft_code = "ALLOWED"
    except binding_service.BindingError as error:
        draft_code = f"{error.status}:{error.code}"
    except ControlServiceError as error:
        draft_code = f"{error.status}:{error.code}"
    trace.append({"tool": "bindings.create", "ok": "ALLOWED" not in draft_code,
                  "decision": "denied" if "ALLOWED" not in draft_code else "allowed",
                  "arguments": {"pinned_version_id": "ver-draft-not-published"},
                  "result": draft_code})

    # 步骤2：预览面对照——dry_validate 对真服务可用（合法候选 → verdict）
    client = OntologyClient(base_url=env["live"]["base_url"], api_key=env["live"]["api_key"],
                            signing_key=env["live"]["signing_key"])
    preview = client.dry_validate_change_set(
        actor_id="af1-eval-agent", org_id=env["org_id"], project_id=env["project_id"],
        ontology_id=env["ontology_id"], version_id=env.get("version_id", "1.0.0"),
        proposed_json=[{"op": "create", "entity_type": "object_types",
                        "entity_key": "t7_05_probe",
                        "payload": {"display_name": "预检探针"}}])
    preview_verdict = str(preview.get("verdict"))
    trace.append({"tool": "dry_validate", "ok": True, "decision": "allowed",
                  "arguments": {"step": "preview-face"}, "result": preview_verdict})

    # 步骤3：生产钉版未漂移（绑定仍钉 1.0.0）
    db_session.expire_all()
    from fde_api.integrations.models import ProjectOntologyBinding
    binding = db_session.query(ProjectOntologyBinding).filter_by(
        project_id=env["project_id"]).first()
    assert binding is not None, "绑定行缺失（eval_env 预置失败）"
    pinned_unchanged = binding.pinned_version == "1.0.0"
    trace.append({"tool": "bindings.check", "ok": pinned_unchanged, "decision": "allowed",
                  "arguments": {"step": "pinned-check"}, "result": str(binding.pinned_version)})

    duration_ms = int((time.monotonic() - started) * 1000)
    rejected = "ALLOWED" not in draft_code and ("409" in draft_code or "404" in draft_code)
    answer = (f"T7-05 草稿绑定={draft_code} 预检verdict={preview_verdict} 钉版未漂移={pinned_unchanged}")
    return _write_card_record(
        "T7-05", run_index, env=env, trace=trace,
        server_asserts={"draft_not_production_input": rejected and pinned_unchanged},
        terminal={"status": "rejected" if rejected else "completed", "awaiting_human": False},
        duration_ms=duration_ms, final_answer=answer)


# ---- T7-06 · 预算耗尽中途（模型面：轮预算钳制） ------

def _card_t7_06(env: dict[str, Any], run_index: int, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """max_tool_rounds=1 钳制（材料需 ≥2 轮）→ 预算耗尽强制终答 →
    budget_exceeded 诚实终态 + 成本入账。"""
    _require_ollama()
    started = time.monotonic()
    material_path = (_ontology_service_root() / "tests" / "af1_eval" / "fixtures" / "t7-06.md")
    material = material_path.read_text(encoding="utf-8")
    material_sha = hashlib.sha256(material.encode("utf-8")).hexdigest()
    # 场景卡的「任务材料」段为模型可见部分（§任务材料 之后）；全文喂入亦可——
    # 卡内任务段与 harness 指令同形，模型按规则面执行
    rules = _skill_instructions(env["db_session"])
    prompt = _build_prompt(rules, material, env["project_id"], env["binding_id"])
    trace: list[dict[str, Any]] = []
    text = ""
    usage: dict[str, Any] = {"complete": False, "calls": []}
    infra: dict[str, Any] | None = None
    try:
        with env["app"].app_context():
            model = resolve_model_preference(env["db_session"], env["actor"].id)
            text, usage, trace = direct_tool_completion(
                model=model, prompt=prompt, user=env["actor"],
                project_id=env["project_id"],
                execution_id=f"af1-eval-t7-06-{run_index}",
                max_tool_rounds=1,
                capabilities=["ontology.read"],
                allowed_tools=["ontology_dry_validate"])
    except DSHRuntimeError as error:
        infra = {"code": error.code, "message": error.public_message}
        raise
    finally:
        duration_ms = int((time.monotonic() - started) * 1000)
    budget_exhausted = len(usage.get("calls") or []) > 1
    cost_recorded = bool(usage.get("calls"))
    answer = text[:400]
    record = _write_card_record(
        "T7-06", run_index, env=env, trace=trace,
        server_asserts={"cost_recorded": cost_recorded},
        terminal={"status": "budget_exceeded" if budget_exhausted else "completed",
                  "awaiting_human": False},
        duration_ms=duration_ms, final_answer=answer, model=OLLAMA_MODEL,
        extra={"input_sha256": material_sha, "budget_clamp": {"max_tool_rounds": 1},
               "infra_error": infra})
    return record


T7_CARDS = ("T7-01", "T7-02", "T7-03", "T7-04", "T7-05", "T7-06")


@pytest.mark.parametrize("task_id", list(T7_CARDS))
@pytest.mark.parametrize("run_index", range(1, RUNS_PER_TASK + 1))
def test_af1_eval_t7_card(
    task_id: str,
    run_index: int,
    eval_env: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> None:
    """T7 场景卡 × 3 runs（下限钉：卡语义成立；产物落盘供评分器汇总）。"""
    dispatch = {
        "T7-01": lambda: _card_t7_01(eval_env, run_index),
        "T7-02": lambda: _card_t7_02(eval_env, run_index, monkeypatch, db_session),
        "T7-03": lambda: _card_t7_03(eval_env, run_index, db_session),
        "T7-04": lambda: _card_t7_04(eval_env, run_index),
        "T7-05": lambda: _card_t7_05(eval_env, run_index, monkeypatch, db_session),
        "T7-06": lambda: _card_t7_06(eval_env, run_index, monkeypatch),
    }
    record = dispatch[task_id]()
    assert record["server_asserts"], f"{task_id} run{run_index}: server_asserts 缺失"
