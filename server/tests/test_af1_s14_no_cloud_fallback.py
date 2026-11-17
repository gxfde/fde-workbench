"""S14-AF1 负向钉（AF1-WP5 批1）：自托管端点运行中失败 → fail-closed 不回退云端。

安全红线（任务书 §15）：客户敏感数据不默认发公共模型；AF0 定参=自托管默认档
（``test_ai_selfhosted_default`` 钉的是**解析序**——自托管先于云槽）。本钉补
**运行中**语义：端点连不通时直连循环抛 ``ai_unavailable`` 冒泡收场，全程仅
命中自托管 base_url 一次——不存在「失败后补调公共云」的隐藏回落腿。
"""
from __future__ import annotations

from typing import Any

import pytest
import requests

from fde_api.control.ai_tool_loop import direct_tool_completion
from fde_api.control.dsh_runtime import DSHRuntimeError
from test_agents_d4_harness import make_user

SELFHOSTED_BASE = "http://127.0.0.1:11434/v1"


class _FailingSession:
    """post 恒 ConnectionError 的替身——记录每次调用 URL 供回落审计。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def post(self, url: str, **kwargs: Any) -> Any:
        self.calls.append(url)
        raise requests.ConnectionError("self-hosted endpoint down")


def test_selfhosted_failure_raises_and_never_falls_back_to_cloud(
    db_session, app
) -> None:
    leader = make_user(db_session, "project_lead")
    model = {
        "id": "system-selfhosted",
        "base_url": SELFHOSTED_BASE,
        "model": "qwen3:14b",
        "api_key": "ollama",
    }
    failing = _FailingSession()

    with app.app_context():
        with pytest.raises(DSHRuntimeError) as unavailable:
            direct_tool_completion(
                model=model,
                prompt="ping",
                user=leader,
                project_id=None,
                execution_id="af1-s14-1",
                session=failing,  # type: ignore[arg-type]
                max_tool_rounds=1,
            )

    assert unavailable.value.code == "ai_unavailable"
    # fail-closed 核心：只有自托管端点一次调用——零云端补调（URL 全程回环）
    assert len(failing.calls) == 1, failing.calls
    assert all(call.startswith(SELFHOSTED_BASE) for call in failing.calls), failing.calls
