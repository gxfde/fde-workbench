"""AF1-WP4（N1）：工具调用载荷持久化——工程台「工具历史/Diff/校验错误」数据面。

AgentToolCall 此前仅有 tool_name/decision/capability/reason/duration_ms
（docs/ai-fde/13 §3 N1）：dry_validate 候选与 violations 不落库，工程台不可
回查；直连循环 trace 仅内存（挂账「直连循环持久审计留痕」）。本批两腿：

- MCP/host 面（有 AgentRun）：ToolCallRecord 带请求/响应载荷，``_finalize``
  落三新列（64KB 截断 + ``payload_truncated`` 标记）；
- 直连循环：trace 项带载荷摘要（arguments/result/decision），automation
  output 留痕随之携带。

既有工具判定语义零变化：载荷为附加留痕，denied/allowed 判定照旧（载荷
提取失败＝None 留痕，不改变判定结果）。
"""
from __future__ import annotations

import json
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from fde_api.agents.adapter import AgentRunContext, AgentRunResult, ToolCallRecord, ZcodeAdapter
from fde_api.agents.models import AgentRegistry, AgentRun, AgentToolCall
from fde_api.agents.service import _finalize
from fde_api.auth.models import User
from fde_api.control.ai_tool_loop import MAX_AUDIT_PAYLOAD_BYTES, direct_tool_completion
from test_agents_d4_harness import make_user
from test_document_drafts_api import _persist_project

PAYLOAD_LIMIT = MAX_AUDIT_PAYLOAD_BYTES


def _oversize_json() -> str:
    return json.dumps({"blob": "x" * (PAYLOAD_LIMIT * 2)}, ensure_ascii=False)


# --- adapter 面：宿主回执事件 → ToolCallRecord 载荷 ------------------------


def _ctx(*, allowed=("ontology_dry_validate",)) -> AgentRunContext:
    return AgentRunContext(
        run_id=f"run-{uuid4().hex[:8]}",
        project_code="af1wp4",
        capability="agent.ontology.propose",
        workspace_host="/tmp/ws",
        allowed_tools=frozenset(allowed),
    )


def test_judge_tool_call_extracts_payloads() -> None:
    """回执事件带 arguments/output → 载荷进 record；判定不变（allowed）。"""
    record = ZcodeAdapter()._judge_tool_call(
        _ctx(),
        {"tool": "ontology_dry_validate", "duration_ms": 12,
         "arguments": {"proposed_json": [{"entity_key": "equipment"}]},
         "output": {"verdict": "pass", "violations": []}},
    )
    assert record.decision == "allowed"
    assert record.request_json is not None and "equipment" in record.request_json
    assert record.response_json is not None and "pass" in record.response_json
    assert record.payload_truncated is False


def test_judge_tool_call_denied_still_records_payload() -> None:
    """denied 腿载荷照旧留痕（越权反查要连载荷一起可回查）。"""
    record = ZcodeAdapter()._judge_tool_call(
        _ctx(allowed=()),
        {"tool": "api_execute", "arguments": {"cmd": "rm -rf"}, "output": None},
    )
    assert record.decision == "denied"
    assert record.reason == "not_in_allowlist"
    assert record.request_json is not None and "rm -rf" in record.request_json
    assert record.response_json is None


def test_judge_tool_call_truncates_and_survives_unserializable() -> None:
    """超限截断＋payload_truncated 标记；不可序列化载荷＝None 不炸判定。"""
    record = ZcodeAdapter()._judge_tool_call(
        _ctx(),
        {"tool": "ontology_dry_validate", "arguments": {"blob": _oversize_json()},
         "output": {"set": {1, 2}}},
    )
    assert record.payload_truncated is True
    assert record.request_json is not None
    assert len(record.request_json.encode("utf-8")) <= PAYLOAD_LIMIT + 64
    # output 含不可序列化集合 → best-effort 失败即 None，判定不受影响
    assert record.response_json is None or isinstance(record.response_json, str)


# --- 直连循环面：trace 载荷摘要 --------------------------------------------


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


def _tool_call_response(name, arguments) -> FakeResponse:
    return FakeResponse(200, {
        "choices": [{
            "message": {
                "content": "我来预检。",
                "tool_calls": [{
                    "id": "call-1", "type": "function",
                    "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
                }],
            },
            "finish_reason": "tool_calls",
        }],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    })


def _final_response(text="预检通过。") -> FakeResponse:
    return FakeResponse(200, {
        "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 20, "completion_tokens": 8},
    })


def _provider_model() -> dict:
    return {"id": "pref-1", "provider": "minimax", "base_url": "https://api.minimaxi.com/v1",
            "model": "MiniMax-M3.1-Flash", "api_key": "sk-cp-test", "supports_tools": True}


@pytest.fixture
def loop_user(app, db_session):
    user = User(username=f"wp4-loop-{id(db_session)}", display_name="wp4-loop",
                password_hash="unused", role="admin", is_active=True, must_change_password=False)
    db_session.add(user)
    db_session.commit()
    return user


def test_direct_loop_trace_carries_payloads(app, db_session, loop_user, monkeypatch):
    """直连循环 trace 项带 arguments/result/decision（挂账「直连循环持久审计
    留痕」的数据面前提：automation output 留痕随之携带载荷）。"""
    from fde_api.control import ai_tool_loop

    def fake_call_tool(session, *, user, claims, allowed, name, arguments):
        return {"verdict": "pass", "violations": []}

    monkeypatch.setattr(ai_tool_loop, "call_tool", fake_call_tool)
    session = FakeSession([
        _tool_call_response("ontology_dry_validate", {"proposed_json": []}),
        _final_response("预检通过。"),
    ])

    _text, _usage, trace = direct_tool_completion(
        model=_provider_model(), prompt="预检", user=loop_user, project_id=None,
        execution_id="wp4-1", session=session,
    )
    assert len(trace) == 1
    entry = trace[0]
    assert entry["tool"] == "ontology_dry_validate"
    assert entry["ok"] is True
    assert entry["decision"] == "allowed"
    assert entry["arguments"] == '{"proposed_json": []}'
    assert "pass" in entry["result"]


def test_direct_loop_trace_marks_refused_payload(app, db_session, loop_user, monkeypatch):
    """拒执腿（能力/闭集外）trace 照旧带载荷与 denied 决策——as data 不 crash。"""
    from fde_api.control import ai_tool_loop
    from fde_api.control.service import ControlServiceError

    def refusing(session, *, user, claims, allowed, name, arguments):
        raise ControlServiceError("forbidden", "本次执行没有此工具的权限。", 403)

    monkeypatch.setattr(ai_tool_loop, "call_tool", refusing)
    session = FakeSession([
        _tool_call_response("api_execute", {"cmd": "rm -rf /"}),
        _final_response("没有权限。"),
    ])

    _text, _usage, trace = direct_tool_completion(
        model=_provider_model(), prompt="执行", user=loop_user, project_id=None,
        execution_id="wp4-2", session=session,
    )
    entry = trace[0]
    assert entry["decision"] == "denied"
    assert entry["arguments"] == '{"cmd": "rm -rf /"}'
    assert "forbidden" in entry["result"]


# --- 落库面：_finalize 写三列 ---------------------------------------------


def _registry(db_session: Session) -> AgentRegistry:
    registry = AgentRegistry(
        kind="zcode", name=f"wp4-payload-{uuid4().hex[:6]}",
        enabled=True, capability_tier="project_operator", sandbox_profile="sandbox",
    )
    db_session.add(registry)
    db_session.flush()
    return registry


def _seed_run(db_session: Session, lead: User, project) -> AgentRun:
    registry = _registry(db_session)
    run = AgentRun(
        project_id=project.id, agent_id=registry.id,
        initiated_by_user_id=lead.id, capability_used="ontology.propose",
        status="running", context_ref=f"masked://runs/{uuid4().hex[:8]}",
        idempotency_key=f"ik-{uuid4().hex[:12]}",
    )
    db_session.add(run)
    db_session.commit()
    return run


def _result(*tool_calls: ToolCallRecord) -> AgentRunResult:
    return AgentRunResult(
        status="completed", exit_code=0, token_cost=42, duration_ms=1500,
        artifacts=(), tool_calls=tuple(tool_calls), degraded=False,
        degraded_reason=None, receipt_state="no_output",
    )


def test_finalize_persists_payload_columns(db_session, settings, tmp_path) -> None:
    """MCP/host 面：_finalize 把 ToolCallRecord 载荷写进三新列（append-only
    加列；既有列语义零变化）。"""
    lead = make_user(db_session, "project_lead")
    project = _persist_project(db_session, lead, code=f"W4{uuid4().hex[:4]}")
    run = _seed_run(db_session, lead, project)
    record = ToolCallRecord(
        tool_name="ontology_dry_validate", decision="allowed", capability="ontology.read",
        duration_ms=12, request_json='{"proposed_json": []}',
        response_json='{"verdict": "pass"}', payload_truncated=False,
    )

    _finalize(
        lambda: Session(db_session.bind), run_id=run.id, result=_result(record),
        known_refs=set(), workspace=tmp_path, solution_id=None,
    )
    db_session.expire_all()
    row = db_session.query(AgentToolCall).filter_by(run_id=run.id).one()
    assert row.request_json == '{"proposed_json": []}'
    assert row.response_json == '{"verdict": "pass"}'
    assert row.payload_truncated is False
    assert row.tool_name == "ontology_dry_validate"


def test_finalize_persists_truncated_marker(db_session, settings, tmp_path) -> None:
    """截断标记位落库：超限载荷存截断文本 + payload_truncated=True。"""
    lead = make_user(db_session, "project_lead")
    project = _persist_project(db_session, lead, code=f"W4{uuid4().hex[:4]}")
    run = _seed_run(db_session, lead, project)
    record = ToolCallRecord(
        tool_name="ontology_dry_validate", decision="allowed", capability="ontology.read",
        duration_ms=5, request_json=_oversize_json(),
        response_json=None, payload_truncated=True,
    )
    _finalize(
        lambda: Session(db_session.bind), run_id=run.id, result=_result(record),
        known_refs=set(), workspace=tmp_path, solution_id=None,
    )
    db_session.expire_all()
    row = db_session.query(AgentToolCall).filter_by(run_id=run.id).one()
    assert row.payload_truncated is True
    assert len(row.request_json.encode("utf-8")) <= PAYLOAD_LIMIT + 64


def test_finalize_persists_record_flag_without_fresh_cut(db_session, settings, tmp_path) -> None:
    """record 旗标孤立覆盖（评审 verification-gap #2）：adapter 截断过的载荷
    文本已在限内但旗标 True——落库侧 OR 链不得把旗标当冗余丢掉。"""
    lead = make_user(db_session, "project_lead")
    project = _persist_project(db_session, lead, code=f"W4{uuid4().hex[:4]}")
    run = _seed_run(db_session, lead, project)
    record = ToolCallRecord(
        tool_name="ontology_dry_validate", decision="allowed", capability="ontology.read",
        duration_ms=5,
        request_json='{"blob": "在限内的截断后文本"}',
        response_json=None,
        payload_truncated=True,
    )
    _finalize(
        lambda: Session(db_session.bind), run_id=run.id, result=_result(record),
        known_refs=set(), workspace=tmp_path, solution_id=None,
    )
    db_session.expire_all()
    row = db_session.query(AgentToolCall).filter_by(run_id=run.id).one()
    assert row.payload_truncated is True


def test_finalize_without_payload_keeps_nulls(db_session, settings, tmp_path) -> None:
    """存量路径（无载荷 record）三列保持 NULL——向后兼容零行为变化。"""
    lead = make_user(db_session, "project_lead")
    project = _persist_project(db_session, lead, code=f"W4{uuid4().hex[:4]}")
    run = _seed_run(db_session, lead, project)
    record = ToolCallRecord(
        tool_name="file_search", decision="allowed", capability="file.search", duration_ms=3,
    )
    _finalize(
        lambda: Session(db_session.bind), run_id=run.id, result=_result(record),
        known_refs=set(), workspace=tmp_path, solution_id=None,
    )
    db_session.expire_all()
    row = db_session.query(AgentToolCall).filter_by(run_id=run.id).one()
    assert row.request_json is None and row.response_json is None
    assert row.payload_truncated is False
