"""V31-P1：推理模型直连腿输出预算与诚实截断报错（实测定案版）。

背景（somwyn 试点 Step 2 实录 + 2026-11-09 实弹定案）：MiniMax-M3.1-Flash 的
``reasoning_content`` 与 ``content`` **共享** max_tokens，且供应商 completion
**硬顶 16,384 tokens**。全文 10K 字符纪要一次成抽时，模型把 16,383/16,384
tokens 全花在思考上、正文零产出（``finish_reason=length``）。

修复＝①**不给推理模型加预算**（实弹证伪「×2 预留」：32,768 预算下思考同步
变长，同一篇纪要 >900s 未返回——加预算只会更慢更易触顶）；②截断诚实报错
``ai_output_truncated``（含处置指引、不可重试）；③截断证据写进 usage
（``truncated`` 标记 / ``finish_reason``）；④截断判定不依赖供应商措辞——
输出 token 触达请求预算即视为截断（模型自然收尾时必小于预算）。
"""
from __future__ import annotations

import pytest

from fde_api.control.ai_server_client import (
    direct_provider_completion,
    effective_max_tokens,
    is_reasoning_model,
)
from fde_api.control.dsh_runtime import DSHRuntimeError


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, response=None):
        self.response = response
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


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


# --- is_reasoning_model ------------------------------------------------------


@pytest.mark.parametrize("model_name,expected", [
    ("MiniMax-M3.1-Flash", True),      # somwyn 试点实败模型
    ("MiniMax-M2.5", True),
    ("deepseek-reasoner", True),
    ("DeepSeek-R1", True),
    ("QwQ-32B", True),
    ("o1", True),
    ("o4-mini", True),
    ("gpt-o1", True),
    ("vendor-abc-thinking", True),
    ("deepseek-v4", False),
    ("deepseek-chat", False),
    ("kimi-k3", False),
    ("gpt-4o", False),                 # 词中 o 无边界，不命中
    ("o13", False),                    # o13 ≠ o1
    ("", False),
])
def test_reasoning_model_detection_builtin(model_name: str, expected: bool) -> None:
    assert is_reasoning_model(model_name) is expected


def test_reasoning_model_detection_extra_pattern_and_bad_regex() -> None:
    # 部署扩展正则作为额外分支并入
    assert is_reasoning_model("custom-think-7", extra_pattern=r"think-\d+") is True
    assert is_reasoning_model("deepseek-v4", extra_pattern=r"think-\d+") is False
    # 坏正则：忽略扩展、内置仍生效，绝不抛错打断调用
    assert is_reasoning_model("deepseek-v4", extra_pattern="(") is False
    assert is_reasoning_model("MiniMax-M3.1-Flash", extra_pattern="(") is True


# --- effective_max_tokens：推理模型**不加码** --------------------------------


@pytest.mark.parametrize("model_name,requested", [
    ("MiniMax-M3.1-Flash", 16384),
    ("deepseek-reasoner", 1024),
    ("deepseek-v4", 16384),
    ("deepseek-v4", 0),
])
def test_effective_max_tokens_never_inflates(model_name: str, requested: int) -> None:
    """实测证伪「×2 预留」：思考长度随授予预算增长，加码只更慢更易触顶。"""
    assert effective_max_tokens(model_name, requested) == requested


def test_direct_completion_keeps_budget_for_reasoning_model() -> None:
    session = FakeSession(FakeResponse(200, {"choices": [{"message": {"content": "ok"}}]}))

    direct_provider_completion(model=provider_model(), prompt="抽取", max_tokens=16384, session=session)

    assert session.calls[0][1]["json"]["max_tokens"] == 16384


def test_direct_completion_keeps_budget_for_non_reasoning_model() -> None:
    session = FakeSession(FakeResponse(200, {"choices": [{"message": {"content": "ok"}}]}))

    direct_provider_completion(
        model=provider_model(model="deepseek-v4"), prompt="抽取", max_tokens=1024, session=session)

    assert session.calls[0][1]["json"]["max_tokens"] == 1024


# --- direct_provider_completion：诚实截断 -----------------------------------


def truncated_payload(content, finish_reason="length", reasoning_tokens=16383,
                      completion_tokens=16384):
    usage = {"prompt_tokens": 5635, "completion_tokens": completion_tokens}
    if reasoning_tokens is not None:
        usage["completion_tokens_details"] = {"reasoning_tokens": reasoning_tokens}
    choice = {"finish_reason": finish_reason}
    if content is not None:
        choice["message"] = {"content": content}
    else:
        choice["message"] = {}
    return {"choices": [choice], "usage": usage}


def test_direct_completion_empty_content_length_raises_truncated() -> None:
    session = FakeSession(FakeResponse(200, truncated_payload(content=None)))

    with pytest.raises(DSHRuntimeError) as caught:
        direct_provider_completion(model=provider_model(), prompt="抽取", session=session)

    assert caught.value.code == "ai_output_truncated"
    assert caught.value.retryable is False  # 同输入重放同败：不给无意义的自动重试
    assert "16383" in caught.value.public_message
    assert "分段" in caught.value.public_message


def test_direct_completion_empty_content_stop_stays_invalid() -> None:
    """未触顶、正文空 → 仍是「未返回有效结果」，不是截断（不误诊）。"""
    session = FakeSession(FakeResponse(200, truncated_payload(
        content="", finish_reason="stop", reasoning_tokens=None, completion_tokens=12)))

    with pytest.raises(DSHRuntimeError) as caught:
        direct_provider_completion(model=provider_model(), prompt="抽取", session=session)

    assert caught.value.code == "ai_output_invalid"
    assert caught.value.retryable is True


def test_direct_completion_budget_exhaustion_flags_truncation_without_finish_reason() -> None:
    """供应商不说 length、但输出 token 触达请求预算 → 同样判定截断。"""
    session = FakeSession(FakeResponse(200, truncated_payload(
        content=None, finish_reason="stop", reasoning_tokens=None, completion_tokens=16384)))

    with pytest.raises(DSHRuntimeError) as caught:
        direct_provider_completion(model=provider_model(), prompt="抽取", max_tokens=16384, session=session)

    assert caught.value.code == "ai_output_truncated"


def test_direct_completion_truncated_nonempty_content_annotates_usage() -> None:
    # 正文非空但截断：返回内容（对话场景可用），usage 带截断证据供
    # 结构化消费方（discovery）诊断与审计回查。
    session = FakeSession(FakeResponse(200, truncated_payload(content='{"facts": [{"sub')))

    text, usage = direct_provider_completion(model=provider_model(), prompt="抽取", session=session)

    assert text == '{"facts": [{"sub'
    call = usage["calls"][0]
    assert call["truncated"] is True
    assert call["finish_reason"] == "length"
    assert call["reasoning_tokens"] == 16383
    # 记账汇总不受附加键影响
    assert call["input_tokens"] == 5635 and call["output_tokens"] == 16384


def test_direct_completion_truncated_without_reasoning_detail_still_flags() -> None:
    # 供应商不报 reasoning 明细：截断证据仍在，reasoning_tokens 不发明
    session = FakeSession(FakeResponse(200, truncated_payload(content=None, reasoning_tokens=None)))

    with pytest.raises(DSHRuntimeError) as caught:
        direct_provider_completion(model=provider_model(), prompt="抽取", session=session)

    assert caught.value.code == "ai_output_truncated"
    assert "16383" not in caught.value.public_message


def test_direct_completion_budget_not_exhausted_keeps_usage_clean() -> None:
    """未触顶的正常回答不带截断标记（不误伤常规路径）。"""
    session = FakeSession(FakeResponse(200, {
        "choices": [{"finish_reason": "stop", "message": {"content": '{"facts": []}'}}],
        "usage": {"prompt_tokens": 1422, "completion_tokens": 15834},
    }))

    text, usage = direct_provider_completion(model=provider_model(), prompt="抽取", session=session)

    assert text == '{"facts": []}'
    assert "truncated" not in usage["calls"][0]


# --- 部署扩展正则接线（app 上下文） -----------------------------------------


def test_settings_extra_pattern_does_not_change_budget(app, monkeypatch) -> None:
    """扩展正则只影响「是否推理模型」的诊断措辞，**不影响预算**（不加码）。"""
    monkeypatch.setattr(app.config["SETTINGS"], "ai_reasoning_model_pattern", r"think-\d+")
    session = FakeSession(FakeResponse(200, {"choices": [{"message": {"content": "ok"}}]}))

    with app.app_context():
        # custom-think-7：内置特征不命中（'-thinking' 才命中），扩展正则命中
        direct_provider_completion(
            model=provider_model(model="custom-think-7"), prompt="抽取", max_tokens=1000, session=session)
        assert session.calls[0][1]["json"]["max_tokens"] == 1000

        session2 = FakeSession(FakeResponse(200, {"choices": [{"message": {"content": "ok"}}]}))
        direct_provider_completion(
            model=provider_model(model="deepseek-v4"), prompt="抽取", max_tokens=1000, session=session2)
        assert session2.calls[0][1]["json"]["max_tokens"] == 1000
