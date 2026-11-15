"""Degraded direct-provider path for AI Server calls when no DSH runtime exists.

The DSH runtime (agnes-harness) is an optional external deployment. When it is
absent, AI Server calls must still reach the provider the user configured in
model preferences — the alternative is a feature that can never work in a
single-machine install. These tests never contact a real provider.
"""
from __future__ import annotations

import json
from unittest.mock import Mock

import pytest

from fde_api.auth.models import User
from fde_api.control.ai_server_client import (
    DEGRADABLE_DSH_CODES,
    direct_provider_completion,
    execute_ai_prompt,
)
from fde_api.control.dsh_runtime import DSHRuntimeError


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        return self.response


def ok_payload(text="你好，我是 FDE 助手。", model="MiniMax-M3.1-Flash"):
    return {
        "choices": [{"message": {"content": text}}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
    }


def provider_model(**overrides):
    model = {
        "id": "pref-1",
        "provider": "openai-compatible",
        "base_url": "https://api.minimaxi.com/v1",
        "model": "MiniMax-M3.1-Flash",
        "api_key": "sk-cp-test",
        "supports_tools": True,
    }
    model.update(overrides)
    return model


# --- direct_provider_completion -------------------------------------------


def test_direct_completion_calls_openai_compatible_endpoint_with_expected_body():
    session = FakeSession(FakeResponse(200, ok_payload()))

    text, usage = direct_provider_completion(
        model=provider_model(),
        prompt="你好",
        system_prompt="你是 FDE 交付助手。",
        max_tokens=1024,
        session=session,
    )

    url, kwargs = session.calls[0]
    assert url == "https://api.minimaxi.com/v1/chat/completions"
    assert kwargs["headers"]["Authorization"] == "Bearer sk-cp-test"
    assert kwargs["headers"]["Content-Type"] == "application/json"
    body = kwargs["json"]
    assert body["model"] == "MiniMax-M3.1-Flash"
    # V31-P1b：预算不加码（×2 预留被实弹证伪——加码只让推理模型思考更久更易触顶）
    assert body["max_tokens"] == 1024
    assert [message["role"] for message in body["messages"]] == ["system", "user"]
    assert body["messages"][1]["content"] == "你好"
    # A chat answer is not a JSON task: no response_format, no reasoning flags.
    assert "response_format" not in body
    assert "reasoning_effort" not in body
    assert text == "你好，我是 FDE 助手。"
    assert usage["complete"] is True
    assert usage["calls"][0]["input_tokens"] == 12
    assert usage["calls"][0]["output_tokens"] == 8
    assert usage["calls"][0]["model"] == "MiniMax-M3.1-Flash"


def test_direct_completion_without_system_prompt_sends_user_message_only():
    session = FakeSession(FakeResponse(200, ok_payload()))

    direct_provider_completion(model=provider_model(), prompt="只有用户消息", session=session)

    body = session.calls[0][1]["json"]
    assert [message["role"] for message in body["messages"]] == ["user"]


@pytest.mark.parametrize("status_code,code,retryable", [
    (429, "ai_rate_limited", True),
    (401, "ai_authentication_failed", False),
    (403, "ai_authentication_failed", False),
    (500, "ai_unavailable", True),
])
def test_direct_completion_maps_http_failures_to_actionable_codes(status_code, code, retryable):
    session = FakeSession(FakeResponse(status_code, {"error": "nope"}))

    with pytest.raises(DSHRuntimeError) as caught:
        direct_provider_completion(model=provider_model(), prompt="你好", session=session)

    assert caught.value.code == code
    assert caught.value.retryable is retryable


def test_direct_completion_rejects_incomplete_model_descriptor():
    session = FakeSession(FakeResponse(200, ok_payload()))

    for broken in (provider_model(base_url=""), provider_model(model=""), provider_model(api_key="")):
        with pytest.raises(DSHRuntimeError) as caught:
            direct_provider_completion(model=broken, prompt="你好", session=session)
        assert caught.value.code == "ai_model_not_configured"
        assert caught.value.retryable is False
    assert session.calls == []


def test_direct_completion_rejects_unparsable_or_empty_payloads():
    for payload in ({}, {"choices": []}, {"choices": [{"message": {"content": "   "}}]}):
        session = FakeSession(FakeResponse(200, payload))
        with pytest.raises(DSHRuntimeError) as caught:
            direct_provider_completion(model=provider_model(), prompt="你好", session=session)
        assert caught.value.code == "ai_output_invalid"


# --- execute_ai_prompt degradation ---------------------------------------


@pytest.fixture
def ai_user(app, db_session):
    user = User(
        username=f"fallback-test-{id(db_session)}",
        display_name="fallback",
        password_hash="unused",
        role="admin",
        is_active=True,
        must_change_password=False,
    )
    db_session.add(user)
    db_session.commit()
    return user


def _disable_dsh(app, monkeypatch):
    from fde_api.control.dsh_runtime import dsh_runtime

    with app.app_context():
        dsh_runtime.current.primary.enabled = False


def test_execute_prompt_degrades_to_provider_when_dsh_is_not_enabled(app, db_session, ai_user, monkeypatch):
    session = FakeSession(FakeResponse(200, ok_payload("已直连回答。")))
    monkeypatch.setattr("fde_api.control.ai_server_client.requests.Session", lambda: session)
    issue_token = Mock(side_effect=AssertionError("MCP token must not be issued without DSH"))
    monkeypatch.setattr("fde_api.control.ai_server_client.issue_mcp_token", issue_token)
    _disable_dsh(app, monkeypatch)

    with app.app_context():
        result = execute_ai_prompt(
            user_id=ai_user.id,
            prompt="你好",
            model_override=provider_model(),
            return_metadata=True,
            purpose="unit_test"
        )

    assert result["text"] == "已直连回答。"
    assert result["degraded"] is True
    assert result["degraded_reason"] == "dsh_not_enabled"
    # The degraded path now runs the local tool loop, so tools ARE available.
    assert result["tools_available"] is True
    assert result["model"]["name"] == "MiniMax-M3.1-Flash"
    assert session.calls[0][0] == "https://api.minimaxi.com/v1/chat/completions"
    issue_token.assert_not_called()


def test_execute_prompt_degrades_on_unreachable_dsh_runtime(app, db_session, ai_user, monkeypatch):
    from fde_api.control.dsh_runtime import dsh_runtime

    session = FakeSession(FakeResponse(200, ok_payload("降级后回答。")))
    monkeypatch.setattr("fde_api.control.ai_server_client.requests.Session", lambda: session)

    class BrokenRuntime:
        enabled = True

        def _request(self, *args, **kwargs):
            raise DSHRuntimeError("dsh_unavailable", "暂时无法连接 DSH 服务。", retryable=True)

    with app.app_context():
        monkeypatch.setattr(dsh_runtime.current, "primary", BrokenRuntime())
        result = execute_ai_prompt(
            user_id=ai_user.id,
            prompt="你好",
            model_override=provider_model(),
            return_metadata=True,
            purpose="unit_test"
        )

    assert result["text"] == "降级后回答。"
    assert result["degraded"] is True
    assert result["degraded_reason"] == "dsh_unavailable"


def test_execute_prompt_does_not_degrade_on_execution_conflict(app, db_session, ai_user, monkeypatch):
    from fde_api.control.dsh_runtime import dsh_runtime

    class ConflictingRuntime:
        enabled = True

        def _request(self, *args, **kwargs):
            raise DSHRuntimeError("dsh_execution_conflict", "DSH 任务状态冲突。", retryable=False)

    with app.app_context():
        monkeypatch.setattr(dsh_runtime.current, "primary", ConflictingRuntime())
        with pytest.raises(DSHRuntimeError) as caught:
            execute_ai_prompt(
                user_id=ai_user.id,
                prompt="你好",
                model_override=provider_model(),
                return_metadata=True,
                purpose="unit_test"
            )

    assert caught.value.code == "dsh_execution_conflict"


def test_degradable_codes_exclude_conflict_and_include_unavailable_runtime():
    assert "dsh_not_enabled" in DEGRADABLE_DSH_CODES
    assert "dsh_unavailable" in DEGRADABLE_DSH_CODES
    assert "dsh_execution_conflict" not in DEGRADABLE_DSH_CODES


def test_execute_prompt_degraded_result_is_json_serialisable_for_storage(app, db_session, ai_user, monkeypatch):
    session = FakeSession(FakeResponse(200, ok_payload("可序列化。")))
    monkeypatch.setattr("fde_api.control.ai_server_client.requests.Session", lambda: session)
    _disable_dsh(app, monkeypatch)

    with app.app_context():
        result = execute_ai_prompt(
            user_id=ai_user.id,
            prompt="你好",
            model_override=provider_model(),
            return_metadata=True,
            purpose="unit_test"
        )

    assert json.loads(json.dumps(result))["degraded"] is True


# --- system default provider labelling ------------------------------------


@pytest.mark.parametrize("base_url,expected", [
    ("https://api.minimaxi.com/v1", "minimax"),
    ("https://api.minimax.io/v1", "minimax"),
    ("https://api.deepseek.com", "deepseek"),
    ("https://api.deepseek.com/v1", "deepseek"),
    ("https://llm.internal.corp/v1", "openai-compatible"),
])
def test_system_default_reports_the_real_provider_for_its_endpoint(base_url, expected):
    """The slot is named deepseek_*, but the endpoint may be any vendor.

    Reporting "deepseek" for a MiniMax endpoint mislabels the usage panel and
    wrongly unlocks the DeepSeek-only depth-thinking switch.
    """
    from fde_api.control.model_preferences import _provider_for_base_url

    assert _provider_for_base_url(base_url) == expected


def test_system_default_resolve_labels_minimax_endpoint_as_minimax(app, db_session, ai_user, monkeypatch):
    from fde_api.control.model_preferences import resolve_model_preference
    from fde_api.extensions import db

    with app.app_context():
        # 系统默认分支要求已配置 API Key；不能依赖 runner 机器上的 .env
        monkeypatch.setattr(app.config["SETTINGS"], "deepseek_api_key", "ci-synthetic-key")
        monkeypatch.setattr(app.config["SETTINGS"], "deepseek_base_url", "https://api.minimaxi.com/v1")
        monkeypatch.setattr(app.config["SETTINGS"], "deepseek_industry_template_model", "MiniMax-M3.1-Flash")
        with db.session() as session:
            resolved = resolve_model_preference(session, ai_user.id)
        assert resolved["provider"] == "minimax"
        assert resolved["base_url"] == "https://api.minimaxi.com/v1"
        assert resolved["model"] == "MiniMax-M3.1-Flash"


def test_minimax_provider_is_rejected_by_the_depth_thinking_gate(app, db_session, ai_user, monkeypatch):
    """Depth thinking is a DeepSeek-only feature; MiniMax must not claim it."""
    from fde_api.control.service import ControlServiceError

    session = FakeSession(FakeResponse(200, ok_payload()))
    monkeypatch.setattr("fde_api.control.ai_server_client.requests.Session", lambda: session)
    _disable_dsh(app, monkeypatch)

    minimax = provider_model(provider="minimax")
    with app.app_context():
        with pytest.raises(ControlServiceError) as caught:
            execute_ai_prompt(
                user_id=ai_user.id,
                prompt="你好",
                model_override=minimax,
                deep_thinking=True,
                return_metadata=True,
                purpose="unit_test"
            )

    assert caught.value.code == "thinking_unsupported"
    assert session.calls == []


# --- structured_completion failure taxonomy -------------------------------
#
# structured_completion 是 DSH 路径的结构化输出入口：它的失败必须落在
# DSHRuntimeError 分类里。裸异常逃出去时，调用方（kimi/deepseek 客户端）
# 只转 DSHRuntimeError，其余一律当「未预期错误」——重试语义与失败分类都失效。


def test_structured_completion_reports_non_json_as_retryable_output_invalid(app, db_session, ai_user, monkeypatch):
    from fde_api.control.ai_server_client import structured_completion

    monkeypatch.setattr(
        "fde_api.control.ai_server_client.execute_ai_prompt",
        lambda **_kwargs: "这不是 JSON，只是一段散文。",
    )

    with app.app_context():
        with pytest.raises(DSHRuntimeError) as caught:
            structured_completion(
                messages=[{"role": "user", "content": "x"}],
                model="MiniMax-M3.1-Flash",
                base_url="https://api.minimaxi.com/v1",
                api_key="test-key",
                max_tokens=1024,
            )

    assert caught.value.code == "ai_output_invalid"
    assert caught.value.retryable is True


def test_structured_completion_maps_control_errors_to_non_retryable(app, db_session, ai_user, monkeypatch):
    from fde_api.control.ai_server_client import structured_completion
    from fde_api.control.service import ControlServiceError

    def boom(**_kwargs):
        raise ControlServiceError("model_not_configured", "请先在 AI 与扩展的模型管理中配置模型。", 409)

    monkeypatch.setattr("fde_api.control.ai_server_client.execute_ai_prompt", boom)

    with app.app_context():
        with pytest.raises(DSHRuntimeError) as caught:
            structured_completion(
                messages=[{"role": "user", "content": "x"}],
                model="MiniMax-M3.1-Flash",
                base_url="https://api.minimaxi.com/v1",
                api_key="test-key",
                max_tokens=1024,
            )

    # 模型未配置是确定性配置问题：重试也不会好。
    assert caught.value.code == "model_not_configured"
    assert caught.value.retryable is False


def test_execute_ai_prompt_degraded_forwards_capabilities(app, db_session, ai_user, monkeypatch):
    """execute_ai_prompt 走直连降级腿时必须把调用方 capabilities 原样收窄传给 direct_tool_completion。"""
    monkeypatch.setattr(
        "fde_api.control.ai_server_client.resolve_model_preference",
        lambda *_args, **_kwargs: provider_model(),
    )
    captured: dict[str, object] = {}

    def fake_direct_tool_completion(**kwargs):
        captured["capabilities"] = kwargs.get("capabilities")
        return "降级结果", {"complete": True, "calls": []}, []

    monkeypatch.setattr(
        "fde_api.control.ai_tool_loop.direct_tool_completion",
        fake_direct_tool_completion,
    )

    with app.app_context():
        app.config["SETTINGS"].dsh_enabled = False
        automation_runtime = __import__("fde_api.control.dsh_runtime", fromlist=["dsh_runtime"]).dsh_runtime
        monkeypatch.setattr(automation_runtime.current.primary, "enabled", False)
        result = execute_ai_prompt(
            user_id=ai_user.id,
            prompt="只读摘要",
            capabilities=["project.read"],
            purpose="dsh_runtime_execute",
        )

    assert result == "降级结果"
    assert captured["capabilities"] == ["project.read"]
