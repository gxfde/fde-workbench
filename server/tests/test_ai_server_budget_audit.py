"""CR-006 统一预算门 + 统一记账腿回归钉（拍板：统一入账 + 统一闸）。

此前缺口（goal-c c2/c8 两轮 E0 取证）：``dsh_enabled=true`` 时
``execute_ai_prompt``——skill 节点/聊天/结构化调用的 DSH 主路径——对
``ai_monthly_token_budget`` 恒放行且零记账（skill 花费不入任何账本）；
kimi 全路径零预算零审计。本组用例钉：

- DSH 主路径：超限拦截（零 DSH 请求 + ``budget_blocked`` 审计）；成功按
  ``provider_usage`` 精确入账并计入预算；失败入账但不计入预算。
- 降级直连腿：``used_fallback=True`` 入账（token 来自 OpenAI 兼容 usage 块）。
- kimi 本地腿：入口预算门（拦在上传前）+ 成功/失败记账（流式无 usage，
  token 记 None——账本记元数据，不发明数字）。
"""
from __future__ import annotations

import io

import pytest
from sqlalchemy import select

from fde_api.ai.auditing import tokens_used_this_month
from fde_api.ai.kimi import KimiError, KimiFileClient
from fde_api.auth.models import User
from fde_api.control.ai_server_client import execute_ai_prompt
from fde_api.control.dsh_runtime import DSHRuntimeError, dsh_runtime
from fde_api.extensions import db
from fde_api.workbench.models import AICallAudit


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text="", stream_lines=None):
        self.status_code = status_code
        self.headers = {}
        self.text = text
        self._payload = payload if payload is not None else {}
        self._stream_lines = stream_lines or []

    def json(self):
        return self._payload

    def iter_lines(self, decode_unicode=False):
        return iter(self._stream_lines)


class ProviderFakeSession:
    """直连降级腿的 requests.Session 替身。"""

    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append(("post", url))
        return self.response


class KimiFakeSession:
    """kimi 三端点替身（upload/content/completion 路由，同 test_kimi_client）。"""

    def __init__(self, *, upload=None, content=None, completion=None):
        self.upload = upload
        self.content = content
        self.completion = completion
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append(("post", url))
        return self.upload if url.endswith("/files") else self.completion

    def get(self, url, **kwargs):
        self.calls.append(("get", url))
        return self.content

    def delete(self, url, **kwargs):
        self.calls.append(("delete", url))
        return FakeResponse(payload={"deleted": True})


class RecordingRuntime:
    """假 DSH 运行时：记录 /v1/executions 请求，返回既定 payload。"""

    enabled = True

    def __init__(self, payload=None):
        self.payload = payload if payload is not None else dsh_ok_payload()
        self.executions: list[tuple[str, str, dict]] = []

    def _request(self, method, path, **kwargs):
        self.executions.append((method, path, kwargs))
        return FakeResponse(200, self.payload)

    def _json_object(self, response):
        return response.json()

    def _service_error(self, status_code):  # pragma: no cover - 用例不走 4xx
        raise AssertionError("unexpected DSH service error")


class DisabledRuntime:
    enabled = False


def dsh_ok_payload(text="结构化结果。", input_tokens=30, output_tokens=20):
    return {
        "status": "succeeded",
        "output": {"text": text},
        "provider_usage": {"complete": True, "calls": [{
            "model": "MiniMax-M3.1-Flash",
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
        }]},
    }


def direct_ok_payload(text="已直连回答。"):
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


def _make_user(db_session, name):
    user = User(
        username=name,
        display_name=name,
        role="admin",
        password_hash="unused",
        must_change_password=False,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return user


def _seed_usage(db_session, user_id, request_id, input_tokens=100, output_tokens=50):
    db_session.add(AICallAudit(
        request_id=request_id, actor_user_id=user_id, purpose="seed",
        model="seed-model", used_fallback=False, duration_ms=1,
        input_tokens=input_tokens, output_tokens=output_tokens,
        status="succeeded", error_code=None,
    ))
    db_session.commit()


def _kimi_client(session):
    return KimiFileClient(
        base_url="https://api.moonshot.example/v1", api_key="secret",
        model="kimi-k3", timeout_seconds=30, session=session,
    )


def _analyze(client, request_id):
    return client.analyze_docx_json(
        stream=io.BytesIO(b"docx-bytes"), filename="a.docx",
        request_id=request_id,
        build_messages=lambda content: [{"role": "user", "content": content}],
    )


# --- DSH 主路径：统一闸 -----------------------------------------------------


def test_dsh_budget_block_prevents_request_and_writes_blocked_audit(app, db_session, monkeypatch):
    user = _make_user(db_session, "cr6.block")
    _seed_usage(db_session, user.id, "cr6-seed", input_tokens=100, output_tokens=50)
    monkeypatch.setattr(app.config["SETTINGS"], "ai_monthly_token_budget", 150)
    runtime = RecordingRuntime()

    with app.app_context():
        monkeypatch.setattr(dsh_runtime.current, "primary", runtime)
        with pytest.raises(DSHRuntimeError) as caught:
            execute_ai_prompt(
                user_id=user.id, prompt="你好", execution_id="cr6-block-1",
                model_override=provider_model(), use_tools=False,
                purpose="unit_test"
            )

    assert caught.value.code == "ai_budget_exceeded"
    assert caught.value.retryable is False
    assert runtime.executions == []  # 拦截在发起前：零 DSH 请求
    blocked = db_session.scalar(select(AICallAudit).where(AICallAudit.request_id == "cr6-block-1"))
    assert blocked is not None
    assert blocked.status == "budget_blocked"
    assert blocked.error_code == "ai_budget_exceeded"
    assert blocked.actor_user_id == user.id


def test_dsh_success_writes_audit_with_provider_usage_and_counts_toward_budget(app, db_session, monkeypatch):
    user = _make_user(db_session, "cr6.success")
    monkeypatch.setattr(app.config["SETTINGS"], "ai_monthly_token_budget", 100)
    runtime = RecordingRuntime(dsh_ok_payload(input_tokens=30, output_tokens=20))

    with app.app_context():
        monkeypatch.setattr(dsh_runtime.current, "primary", runtime)
        result = execute_ai_prompt(
            user_id=user.id, prompt="你好", execution_id="cr6-ok-1",
            model_override=provider_model(), use_tools=False, return_metadata=True,
            purpose="unit_test"
        )
        db_session.commit()

    assert result["text"] == "结构化结果。"
    audit = db_session.scalar(select(AICallAudit).where(AICallAudit.request_id == "cr6-ok-1"))
    assert audit is not None
    assert audit.status == "succeeded"
    assert audit.used_fallback is False
    assert audit.input_tokens == 30
    assert audit.output_tokens == 20
    assert audit.actor_user_id == user.id
    # N2 仪表化（G-16）：purpose 入口必填 ⇒ 审计行必带用途标识
    assert audit.purpose == "unit_test"
    # 防泄漏：审计不落提示词明文
    blob = f"{audit.request_id}{audit.purpose or ''}{audit.model}{audit.error_code or ''}"
    assert "你好" not in blob
    # 统一账本生效：DSH 主路径消费计入平台月度预算
    with app.app_context():
        with db.session() as session:
            assert tokens_used_this_month(session, user.id) == 50


def test_dsh_failure_writes_failed_audit_and_does_not_count(app, db_session, monkeypatch):
    user = _make_user(db_session, "cr6.fail")
    monkeypatch.setattr(app.config["SETTINGS"], "ai_monthly_token_budget", 100)
    runtime = RecordingRuntime({"status": "failed", "output": {}})

    with app.app_context():
        monkeypatch.setattr(dsh_runtime.current, "primary", runtime)
        with pytest.raises(DSHRuntimeError) as caught:
            execute_ai_prompt(
                user_id=user.id, prompt="你好", execution_id="cr6-fail-1",
                model_override=provider_model(), use_tools=False,
                purpose="unit_test"
            )
        db_session.commit()

    assert caught.value.code == "ai_output_invalid"
    audit = db_session.scalar(select(AICallAudit).where(AICallAudit.request_id == "cr6-fail-1"))
    assert audit is not None
    assert audit.status == "failed"
    assert audit.error_code == "ai_output_invalid"
    with app.app_context():
        with db.session() as session:
            assert tokens_used_this_month(session, user.id) == 0  # 失败不计预算


# --- 降级直连腿：记账带 used_fallback ---------------------------------------


def test_degraded_direct_path_writes_fallback_audit(app, db_session, monkeypatch):
    user = _make_user(db_session, "cr6.degraded")
    session = ProviderFakeSession(FakeResponse(200, direct_ok_payload()))
    monkeypatch.setattr("fde_api.control.ai_server_client.requests.Session", lambda: session)

    with app.app_context():
        monkeypatch.setattr(dsh_runtime.current, "primary", DisabledRuntime())
        result = execute_ai_prompt(
            user_id=user.id, prompt="你好", execution_id="cr6-deg-1",
            model_override=provider_model(), use_tools=False, return_metadata=True,
            purpose="unit_test"
        )
        db_session.commit()

    assert result["degraded"] is True
    audit = db_session.scalar(select(AICallAudit).where(AICallAudit.request_id == "cr6-deg-1"))
    assert audit is not None
    assert audit.status == "succeeded"
    assert audit.used_fallback is True
    assert audit.input_tokens == 12
    assert audit.output_tokens == 8


# --- kimi 本地腿：入口预算门 + 记账 -----------------------------------------


def test_kimi_budget_gate_blocks_before_any_provider_call(app, db_session, monkeypatch):
    user = _make_user(db_session, "cr6.kimi")
    _seed_usage(db_session, user.id, "cr6-kimi-seed")
    monkeypatch.setattr(app.config["SETTINGS"], "ai_monthly_token_budget", 150)
    fake = KimiFakeSession(
        upload=FakeResponse(200, {"id": "f1", "status": "ready"}),
        content=FakeResponse(200, text="客户愿景全文"),
        completion=FakeResponse(200, stream_lines=["data: [DONE]"]),
    )

    with app.app_context():
        from flask import g

        g.current_user = user
        with pytest.raises(KimiError) as caught:
            _analyze(_kimi_client(fake), "cr6-kimi-block")

    assert caught.value.code == "ai_budget_exceeded"
    assert caught.value.retryable is False
    assert fake.calls == []  # 拦在文件上传之前：零供应商请求
    blocked = db_session.scalar(select(AICallAudit).where(AICallAudit.request_id == "cr6-kimi-block"))
    assert blocked is not None
    assert blocked.status == "budget_blocked"


def test_kimi_local_success_writes_audit_with_unknown_tokens(app, db_session):
    user = _make_user(db_session, "cr6.kimiok")
    fake = KimiFakeSession(
        upload=FakeResponse(200, {"id": "f1", "status": "ready"}),
        content=FakeResponse(200, text="客户愿景全文"),
        completion=FakeResponse(200, stream_lines=[
            'data: {"choices": [{"delta": {"content": "{\\"customer_vision\\": \\"愿景\\"}"}}]}',
            "data: [DONE]",
        ]),
    )

    with app.app_context():
        from flask import g

        g.current_user = user
        parsed = _analyze(_kimi_client(fake), "cr6-kimi-ok")
        db_session.commit()

    assert parsed == {"customer_vision": "愿景"}
    assert any(url.endswith("/chat/completions") for _, url in fake.calls)
    audit = db_session.scalar(select(AICallAudit).where(AICallAudit.request_id == "cr6-kimi-ok"))
    assert audit is not None
    assert audit.status == "succeeded"
    assert audit.purpose == "kimi_docx"
    assert audit.actor_user_id == user.id
    # 流式响应无 usage：token 不可测记 None，不发明数字
    assert audit.input_tokens is None
    assert audit.output_tokens is None


def test_kimi_local_failure_writes_failed_audit(app, db_session):
    user = _make_user(db_session, "cr6.kimifail")
    fake = KimiFakeSession(
        upload=FakeResponse(200, {"id": "f1", "status": "ready"}),
        content=FakeResponse(200, text="客户愿景全文"),
        completion=FakeResponse(200, stream_lines=["data: [DONE]"]),  # 空响应 → ai_empty_response
    )

    with app.app_context():
        from flask import g

        g.current_user = user
        with pytest.raises(KimiError) as caught:
            _analyze(_kimi_client(fake), "cr6-kimi-fail")
        db_session.commit()

    assert caught.value.code == "ai_empty_response"
    audit = db_session.scalar(select(AICallAudit).where(AICallAudit.request_id == "cr6-kimi-fail"))
    assert audit is not None
    assert audit.status == "failed"
    assert audit.error_code == "ai_empty_response"
