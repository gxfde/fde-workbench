"""Local tool-calling loop used when no DSH runtime is deployed.

The MCP gateway already implements every workbench tool server-side; this
loop makes those tools reachable to a directly-called provider without
weakening the capability gate. No provider is contacted in these tests.
"""
from __future__ import annotations

import json
from unittest.mock import Mock

import pytest

from fde_api.auth.models import User
from fde_api.control.ai_tool_loop import (
    MAX_TOOL_RESULT_CHARS,
    READ_ONLY_TOOLS,
    _truncate,
    direct_tool_completion,
    tool_definitions,
)
from fde_api.control.dsh_runtime import DSHRuntimeError


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


class FakeSession:
    """Replays a queued list of responses, recording every request body."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if not self.responses:
            raise AssertionError("provider called more times than the test prepared")
        return self.responses.pop(0)


def tool_call_response(name, arguments, call_id="call-1"):
    return FakeResponse(200, {
        "choices": [{
            "message": {
                "content": "我来查一下。",
                "tool_calls": [{
                    "id": call_id,
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
                }],
            },
            "finish_reason": "tool_calls",
        }],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    })


def final_response(text="查询完成。"):
    return FakeResponse(200, {
        "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 20, "completion_tokens": 8},
    })


def provider_model(**overrides):
    model = {
        "id": "pref-1",
        "provider": "minimax",
        "base_url": "https://api.minimaxi.com/v1",
        "model": "MiniMax-M3.1-Flash",
        "api_key": "sk-cp-test",
        "supports_tools": True,
    }
    model.update(overrides)
    return model


@pytest.fixture
def ai_user(app, db_session):
    user = User(
        username=f"tool-loop-{id(db_session)}",
        display_name="tool-loop",
        password_hash="unused",
        role="admin",
        is_active=True,
        must_change_password=False,
    )
    db_session.add(user)
    db_session.commit()
    return user


# --- tool_definitions ------------------------------------------------------


def test_tool_definitions_expose_only_read_only_tools():
    names = {item["function"]["name"] for item in tool_definitions(
        ["project.read", "file.search", "system.health", "workbench.write"])}

    assert "project_list" in names
    assert "file_search" in names
    assert "quote_list" in names
    # Write-side tools must never be offered to a direct provider call.
    assert "api_execute" not in names
    assert "file_send_wechat" not in names
    assert "lcsc_search" not in names
    assert names <= READ_ONLY_TOOLS


def test_tool_definitions_respect_capability_gate():
    names = {item["function"]["name"] for item in tool_definitions([])}
    # project_list / file_search need project.read / file.search.
    assert "project_list" not in names
    assert "file_search" not in names
    # system_status needs system.health — also withheld.
    assert "system_status" not in names
    # These require no capability at all.
    assert "ontology_read" in names
    assert "api_catalog" in names


def test_tool_definitions_use_openai_function_schema():
    definitions = tool_definitions(["project.read"])
    project_list = next(d for d in definitions if d["function"]["name"] == "project_list")
    assert project_list["type"] == "function"
    parameters = project_list["function"]["parameters"]
    assert parameters["type"] == "object"
    assert "query" in parameters["properties"]
    assert project_list["function"]["description"]


def test_truncate_marks_oversized_tool_results():
    payload = {"blob": "x" * (MAX_TOOL_RESULT_CHARS + 100)}
    text = _truncate(payload)
    assert len(text) <= MAX_TOOL_RESULT_CHARS + 40
    assert "已截断" in text
    small = _truncate({"a": 1})
    assert json.loads(small) == {"a": 1}
    assert "已截断" not in small


# --- direct_tool_completion -----------------------------------------------


def test_tool_loop_executes_tool_and_feeds_result_back(app, db_session, ai_user, monkeypatch):
    """The model asks for a tool; the tool runs in-process; the answer is final."""
    from fde_api.control import ai_tool_loop

    calls = []

    def fake_call_tool(session, *, user, claims, allowed, name, arguments):
        calls.append((name, arguments, user.id))
        return {"items": [{"id": "p1", "name": "示例项目", "enterprise_code": "s3·demo"}]}

    monkeypatch.setattr(ai_tool_loop, "call_tool", fake_call_tool)
    session = FakeSession([tool_call_response("project_list", {"query": "示例"}), final_response("你有 1 个项目：示例项目。")])

    text, usage, trace = direct_tool_completion(
        model=provider_model(),
        prompt="我有哪些项目？",
        user=ai_user,
        project_id=None,
        execution_id="exec-1",
        session=session,
    )

    assert text == "你有 1 个项目：示例项目。"
    assert calls == [("project_list", {"query": "示例"}, ai_user.id)]
    assert trace == [{"tool": "project_list", "ok": True}]
    assert usage["complete"] is True
    assert len(usage["calls"]) == 2
    # The second provider call must carry the tool result back.
    second_body = session.calls[1][1]["json"]
    tool_messages = [m for m in second_body["messages"] if m.get("role") == "tool"]
    assert len(tool_messages) == 1
    assert "示例项目" in tool_messages[0]["content"]
    assert tool_messages[0]["tool_call_id"] == "call-1"


def test_tool_loop_sends_tools_array_to_the_provider(app, db_session, ai_user):
    session = FakeSession([final_response("直接回答。")])

    text, usage, trace = direct_tool_completion(
        model=provider_model(), prompt="你好", user=ai_user, project_id=None,
        execution_id="exec-1", session=session)

    assert text == "直接回答。"
    body = session.calls[0][1]["json"]
    assert "tools" in body
    assert body["tool_choice"] == "auto"
    names = {item["function"]["name"] for item in body["tools"]}
    assert "project_list" in names
    assert trace == []


def test_tool_loop_reports_refused_tool_as_data_not_crash(app, db_session, ai_user, monkeypatch):
    from fde_api.control import ai_tool_loop
    from fde_api.control.service import ControlServiceError

    def refusing_call_tool(session, *, user, claims, allowed, name, arguments):
        raise ControlServiceError("forbidden", "本次执行没有此工具的权限。", 403)

    monkeypatch.setattr(ai_tool_loop, "call_tool", refusing_call_tool)
    session = FakeSession([tool_call_response("project_read", {"project_id": "p1"}), final_response("我没有权限查看该项目。")])

    text, usage, trace = direct_tool_completion(
        model=provider_model(), prompt="读项目", user=ai_user, project_id=None,
        execution_id="exec-1", session=session)

    assert "没有权限" in text
    assert trace == [{"tool": "project_read", "ok": False}]
    second_body = session.calls[1][1]["json"]
    tool_message = [m for m in second_body["messages"] if m.get("role") == "tool"][0]
    assert "forbidden" in tool_message["content"]


def test_tool_loop_survives_a_crashing_tool(app, db_session, ai_user, monkeypatch):
    from fde_api.control import ai_tool_loop

    def exploding_call_tool(session, *, user, claims, allowed, name, arguments):
        raise RuntimeError("tool blew up")

    monkeypatch.setattr(ai_tool_loop, "call_tool", exploding_call_tool)
    session = FakeSession([tool_call_response("project_list", {}), final_response("工具出错了。")])

    text, usage, trace = direct_tool_completion(
        model=provider_model(), prompt="列项目", user=ai_user, project_id=None,
        execution_id="exec-1", session=session)

    assert "工具出错了" in text
    assert trace == [{"tool": "project_list", "ok": False}]


def test_crashing_tool_rolls_back_the_shared_db_session(app, db_session, ai_user, monkeypatch):
    """A tool that dies on a broken DB connection must not leave the loop's
    session idle-in-transaction: that state held row locks (observed 2026-10-30
    as a 13-minute users-table lock that queued every login behind it) until
    the pool eventually cycled the connection. The loop must roll back the
    session right away so the next provider round starts clean.
    """
    from fde_api.control import ai_tool_loop
    from sqlalchemy.exc import OperationalError

    def db_error_call_tool(session, *, user, claims, allowed, name, arguments):
        raise OperationalError("SELECT 1", {}, Exception("server closed the connection unexpectedly"))

    monkeypatch.setattr(ai_tool_loop, "call_tool", db_error_call_tool)

    rollbacks: list[bool] = []

    class RecordingSession:
        """Stands in for `db.session()`: it is the object handed to _run_tools
        and records every rollback() plus whether it happened while the session
        was still open (the production guarantee — the lock-releasing rollback
        must fire inside the `with`, not on the exit path)."""

        def __enter__(self):
            self.open = True
            return self

        def __exit__(self, exc_type, exc, tb):
            self.open = False
            return False

        def rollback(self):
            rollbacks.append(self.open)

    monkeypatch.setattr(ai_tool_loop, "db",
                       type("SpyDB", (), {"session": staticmethod(lambda: RecordingSession())}))
    provider = FakeSession([tool_call_response("file_read", {"project_id": "p1", "file_id": "f1"}),
                           final_response("工具暂时不可用。")])

    text, usage, trace = direct_tool_completion(
        model=provider_model(), prompt="读文件", user=ai_user, project_id=None,
        execution_id="exec-1", session=provider)

    # Two rollbacks, both while the session is still open: one from the crash
    # handler inside _run_tools, one from the main loop's per-round cleanup
    # that closes the transaction before the next (possibly minutes-long)
    # provider call — a successful tool round must not idle-in-transaction
    # either.
    assert rollbacks == [True, True]
    assert trace == [{"tool": "file_read", "ok": False}]
    tool_message = [m for m in provider.calls[1][1]["json"]["messages"] if m.get("role") == "tool"][0]
    assert "工具执行失败" in tool_message["content"]
    assert text == "工具暂时不可用。"


def test_tool_loop_stops_after_max_rounds(app, db_session, ai_user, monkeypatch):
    """A model that keeps calling tools must not loop forever."""
    from fde_api.control import ai_tool_loop

    monkeypatch.setattr(ai_tool_loop, "call_tool",
                        lambda session, **kwargs: {"items": []})
    responses = [tool_call_response("project_list", {}, call_id=f"call-{i}")
                 for i in range(10)]
    session = FakeSession(responses)

    text, usage, trace = direct_tool_completion(
        model=provider_model(), prompt="列项目", user=ai_user, project_id=None,
        execution_id="exec-1", session=session)

    # Bounded: MAX_TOOL_ROUNDS tool rounds, plus the forced final answer call.
    assert len(session.calls) <= ai_tool_loop.MAX_TOOL_ROUNDS + 2
    assert len(trace) <= ai_tool_loop.MAX_TOOL_ROUNDS


def test_tool_loop_forces_a_final_answer_when_the_round_budget_runs_out(app, db_session, ai_user, monkeypatch):
    """The model must not answer with "let me look that up" — that is not an answer.

    When the round budget is spent the loop withdraws the tools and asks once
    more, so the reply contains the conclusion rather than the next step.
    """
    from fde_api.control import ai_tool_loop

    monkeypatch.setattr(ai_tool_loop, "call_tool",
                        lambda session, **kwargs: {"items": []})
    # Every tool round answers with a mid-thought sentence instead of a result.
    responses = [tool_call_response("project_list", {}, call_id=f"call-{i}")
                 for i in range(ai_tool_loop.MAX_TOOL_ROUNDS + 1)]
    # The extra call is the forced final answer.
    responses.append(final_response("最终结论：共有 3 个项目。"))
    session = FakeSession(responses)

    text, usage, trace = direct_tool_completion(
        model=provider_model(), prompt="列项目", user=ai_user, project_id=None,
        execution_id="exec-1", session=session)

    assert text == "最终结论：共有 3 个项目。"
    # The forced call must not offer tools any more.
    final_body = session.calls[-1][1]["json"]
    assert "tools" not in final_body
    assert "tool_choice" not in final_body
    assert final_body["messages"][-1]["role"] == "user"
    assert "直接给出最终答案" in final_body["messages"][-1]["content"]


def test_tool_loop_keeps_the_mid_thought_answer_when_the_final_call_fails(app, db_session, ai_user, monkeypatch):
    """If the forced final call fails we must still return something usable."""
    from fde_api.control import ai_tool_loop

    monkeypatch.setattr(ai_tool_loop, "call_tool",
                        lambda session, **kwargs: {"items": []})
    responses = [tool_call_response("project_list", {}, call_id=f"call-{i}")
                 for i in range(ai_tool_loop.MAX_TOOL_ROUNDS + 1)]
    responses.append(FakeResponse(500, {"error": "boom"}))
    session = FakeSession(responses)

    text, usage, trace = direct_tool_completion(
        model=provider_model(), prompt="列项目", user=ai_user, project_id=None,
        execution_id="exec-1", session=session)

    assert text == "我来查一下。"



def test_tool_loop_raises_on_rate_limit(app, db_session, ai_user):
    session = FakeSession([FakeResponse(429, {"error": "rate"})])

    with pytest.raises(DSHRuntimeError) as caught:
        direct_tool_completion(
            model=provider_model(), prompt="你好", user=ai_user, project_id=None,
            execution_id="exec-1", session=session)

    assert caught.value.code == "ai_rate_limited"
    assert caught.value.retryable is True


def test_tool_loop_requires_a_configured_model(app, db_session, ai_user):
    session = FakeSession([])

    with pytest.raises(DSHRuntimeError) as caught:
        direct_tool_completion(
            model=provider_model(api_key=""), prompt="你好", user=ai_user,
            project_id=None, execution_id="exec-1", session=session)

    assert caught.value.code == "ai_model_not_configured"
    assert session.calls == []


def test_tool_loop_passes_project_scope_into_the_claims(app, db_session, ai_user, monkeypatch):
    """Project scoping must reach the tool call, not just the provider."""
    from fde_api.control import ai_tool_loop

    seen = {}

    def capture_call_tool(session, *, user, claims, allowed, name, arguments):
        seen["claims"] = claims
        return {"items": []}

    monkeypatch.setattr(ai_tool_loop, "call_tool", capture_call_tool)
    session = FakeSession([tool_call_response("project_read", {"project_id": "p9"}), final_response("好的。")])

    direct_tool_completion(
        model=provider_model(), prompt="读项目", user=ai_user, project_id="p9",
        execution_id="exec-42", session=session)

    assert seen["claims"]["project_id"] == "p9"
    assert seen["claims"]["execution_id"] == "exec-42"
    assert seen["claims"]["sub"] == ai_user.id


def test_quote_tool_reads_the_quote_ledger(app, db_session, ai_user, monkeypatch):
    """The quote tool must surface the quote card, not the raw model row."""
    from fde_api.control import ai_tool_loop

    calls = []

    def fake_call_tool(session, *, user, claims, allowed, name, arguments):
        calls.append((name, arguments, user.id))
        return {"quotes": [{"quote_key": "Q-001", "tier": "standard", "status": "draft"}], "events": []}

    monkeypatch.setattr(ai_tool_loop, "call_tool", fake_call_tool)
    session = FakeSession([tool_call_response("quote_list", {"project_id": "p1"}), final_response("报价如下。")])

    text, usage, trace = direct_tool_completion(
        model=provider_model(), prompt="这个项目报价多少？", user=ai_user,
        project_id=None, execution_id="exec-1", session=session)

    assert calls == [("quote_list", {"project_id": "p1"}, ai_user.id)]
    assert trace == [{"tool": "quote_list", "ok": True}]
    second_body = session.calls[1][1]["json"]
    tool_message = [m for m in second_body["messages"] if m.get("role") == "tool"][0]
    assert "Q-001" in tool_message["content"]


def test_quote_tool_is_registered_and_readable(app, db_session, ai_user):
    """quote_list must exist in the tool catalogue with the project.read gate."""
    from fde_api.control.mcp_gateway import TOOLS

    assert "quote_list" in TOOLS
    description, capability, properties, effect, risk = TOOLS["quote_list"]
    assert capability == "project.read"
    assert "project_id" in properties
    assert description
    # T-R2：结构化元数据——报价卡读取 = 纯只读零风险
    assert effect == "read" and risk == 0
