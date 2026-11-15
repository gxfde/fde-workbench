"""模拟域 L-B 模型评估的 AI 记账主体（billing_actor_policy 机制化）。

学习闭环 2.0 L6 条款④的政策是「模拟域跑批以**平台服务账号**记账」——候选卡
``provenance.billing_actor_policy`` 写死 ``service_account`` 只是**声明**（政策
常量），本模块把它落成**机制真身**：

- 配置键 ``simulation_ai_actor_username`` 指向一个既有 ``users`` 行（与诊断域
  ``diagnostics_ai_actor_username`` 键隔离，防跨域串账——蔡工 2026-11-15
  拍板①）。
- **留空＝机制关（opt-in，拍板②）**：``resolve_simulation_ai_actor`` 返回
  None，调用方回落既有行为（请求腿记调用者／无主背景腿 fail-open），对存量
  模拟零回归。
- 配置了但账号不存在/已停用 ⇒ **fail-closed**（``ScenarioServiceError``
  ``simulation_ai_unavailable`` 503，仿诊断域 ``resolve_ai_actor`` 先例），
  不静默降级。

调用方（``simulation/evaluator.py`` 的 include_model 分支）在真模型评估前
解析；非 None 时把该账号 id 注入两个 ContextVar（``ai_actor_override`` 覆盖
直连腿的 ``current_actor_id`` 读，既有 ``ai_actor_id`` 覆盖 DSH 腿的
``structured_completion`` 读），使预算闸与 ``ai_call_audits`` 归因落到服务
账号头上。
"""
from __future__ import annotations

from typing import Any

from flask import current_app
from sqlalchemy import select

from fde_api.auth.models import User
from fde_api.simulation.service import ScenarioServiceError

__all__ = ["resolve_simulation_ai_actor"]


def resolve_simulation_ai_actor(session: Any) -> str | None:
    """解析模拟域 AI 记账服务账号。

    返回服务账号的 ``User.id``（str）；配置键留空时返回 **None**（机制关，
    调用方维持现状）。配置了但账号不存在/已停用 ⇒ 抛 503
    ``simulation_ai_unavailable``（fail-closed，不静默降级）。

    归一化口径与诊断域先例逐字一致（NFKC＋去空白＋小写）。
    """
    from unicodedata import normalize

    settings = current_app.config["SETTINGS"]
    raw = str(getattr(settings, "simulation_ai_actor_username", "") or "").strip()
    if not raw:
        return None
    username = normalize("NFKC", raw).strip().lower()
    user = session.scalar(select(User).where(User.username == username))
    if user is None or not user.is_active:
        raise ScenarioServiceError(
            "simulation_ai_unavailable",
            "模拟模型评估服务暂不可用，请稍后再试。",
            503,
        )
    return str(user.id)
