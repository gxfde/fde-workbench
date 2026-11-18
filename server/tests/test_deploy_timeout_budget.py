# -*- coding: utf-8 -*-
"""部署面 gunicorn 超时预算静态钉（2026-11-18 实弹缺陷①的机械闸）。

背景（真机证据）：

- ``POST /simulation/runs/<id>/evaluate?include_model=true&model_mode=server``
  在活体稳定返回 **500**——api 容器日志
  ``[CRITICAL] WORKER TIMEOUT (pid:7)`` → ``Worker exiting`` →
  ``Worker was sent SIGKILL!``（gunicorn arbiter 超时即杀 worker）。
- 根因＝``server/Dockerfile`` 的 ``gunicorn --timeout 120``，而真模型评估层
  单次模型调用上界＝``deepseek_timeout_seconds``（配置面 ≤300s），
  且瞬时失败同消息重试一次 ⇒ **最坏 2×300=600s** ⇒ 120s 恒被击穿
  （真机实测 41–160s ⇒ 必 500）。
- 修法＝``--timeout`` 提到 660（2×上界 + 60s 余量）。

本钉把这条预算**机械化**：``--timeout`` 必须严格大于「AI 超时上界 × 2」
（下界取配置面 ``le``，现测而非承袭），防后续把 timeout 调回小值再复现同一
缺陷；同时钉住「配置面上界被抬高 ⇒ timeout 也必须跟着抬」这条联动。
"""
from __future__ import annotations

import re
from pathlib import Path

from fde_api.config import Settings

_DOCKERFILE = Path(__file__).resolve().parents[1] / "Dockerfile"
_TIMEOUT_FLAG = re.compile(r'"--timeout"\s*,\s*"(\d+)"')
# gunicorn 超时与应用侧余量之间的最小余量（连接/解析/审计/落库开销）
_MARGIN_SECONDS = 60


def _dockerfile_timeout_seconds() -> int:
    text = _DOCKERFILE.read_text(encoding="utf-8")
    matches = _TIMEOUT_FLAG.findall(text)
    assert matches, "Dockerfile CMD 未找到 gunicorn --timeout 参数"
    assert len(matches) == 1, f"--timeout 参数出现多次：{matches}"
    return int(matches[0])


def _ai_timeout_upper_bound() -> int:
    """现测配置面上界（pydantic Field 的 le 约束），不承袭历史数值。"""
    field = Settings.model_fields["deepseek_timeout_seconds"]
    upper = None
    for constraint in field.metadata:
        value = getattr(constraint, "le", None)
        if value is not None:
            upper = int(value)
    assert upper is not None, "deepseek_timeout_seconds 未声明 le 上界"
    return upper


def test_ai_timeout_upper_bound_is_present_and_sane():
    upper = _ai_timeout_upper_bound()
    assert upper >= 60, upper


def test_gunicorn_timeout_exceeds_double_ai_timeout_budget():
    """--timeout 必须 > 2×AI 超时上界（评估腿最坏 2 次模型调用）。"""
    timeout = _dockerfile_timeout_seconds()
    upper = _ai_timeout_upper_bound()
    assert timeout > 2 * upper, (
        f"gunicorn --timeout={timeout}s 不足以覆盖真模型评估腿最坏 "
        f"2×{upper}s（AI 超时上界）⇒ 必复现 WORKER TIMEOUT 500"
    )


def test_gunicorn_timeout_keeps_margin_above_double_budget():
    """预算之上还要留余量（连接/解析/审计/落库开销）。"""
    timeout = _dockerfile_timeout_seconds()
    upper = _ai_timeout_upper_bound()
    assert timeout >= 2 * upper + _MARGIN_SECONDS, (
        f"gunicorn --timeout={timeout}s 未留 {_MARGIN_SECONDS}s 余量"
    )


def test_dockerfile_documents_timeout_budget():
    """超时值旁必须留预算说明（防「只改数不留因」的无据漂移）。"""
    text = _DOCKERFILE.read_text(encoding="utf-8")
    assert "--timeout" in text
    assert "deepseek_timeout_seconds" in text
    assert "SIGKILL worker" in text
    assert "test_deploy_timeout_budget.py" in text
