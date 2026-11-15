"""V3.3 M5 遗留④：S-12 运行时激活拦截（混合形态，TDD）。

契约依据 = Fde-Ontology ``docs/v3.3/m5/08-s12-form-factor-decision.md``
（P1 2026-11-16「全部批准」拍板：混合形态；bmad-code-review 四层评审
整改轮）+ challenger 备忘 ``docs/v3.3/m5/07-s12-two-step-best-case-memo.md``
§1.1/§3：
- A 写值三闸不动（``set_gate_dependency`` 既有行为零回归）；
- 新增**求值时点**运行时拦截：熔断窗口内，门禁生效依赖档若为**基线档**
  （建档 establish 事件回放）以来的净放松值，不按放松档执行——按基线档
  继续求值（required 档本体不可用即 409 挂起＝「宁可挂起，不带病降级」
  在时间维度上的运行时化），``checks["effective_dependency"]`` 改写为执
  行档、``checks["s12_runtime_hold"]`` 显式标注、``checks["breaker_state"]``
  细值全路径留痕（随回执固化）；
- 基线档 = 最早 establish 事件的 to_level（决策单 ③「基线以来净放松」的
  精确化：经三闸合法下调回落到建档档不视为净放松；收紧不改基线）；事件
  流无 establish（ORM 直写/建档早于事件通道）→ 不虚构基线，拦截不触发；
- 全局 strong/weak 直映档不经门禁行值通道，不在本拦截域（环境闸治理面）。

顺带补齐 D5 半接线：回执 ``breaker_state`` 列此前只读未写——
``freeze_gate_receipt`` 从 ``checks["breaker_state"]`` 取值落列（观测值列，
不进两级哈希口径；enabled 全路径均带值，disabled 早退档诚实 NULL）。

纯单元组（``baseline_level_from_events`` / ``s12_runtime_hold_target``）
本地可跑：``pytest tests/test_m5_s12_runtime_hold.py --noconftest -k unit``
（``--noconftest`` 沿仓内 sqlite 自含先例——conftest 的 autouse 链要求测试
库，纯单元无此依赖）；E2E 组与其余 DB 回归测试同口径直接随套件跑
（conftest 硬性保证测试库存在，无 skipif——bmad-code-review verification-gap
整改项：跳过门对齐套件自身的解析链）。
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select

from fde_api.projects.gate_ontology import (
    GateOntologyError,
    baseline_level_from_events,
    set_gate_dependency,
    s12_runtime_hold_target,
)
from fde_api.workbench.models import OperationEvent

# ---------------------------------------------------------------- 纯单元：基线档回放


def test_unit_baseline_none_without_events() -> None:
    """无事件流（ORM 直写/建档早于事件通道）→ 无基线 → 拦截不触发。"""
    assert baseline_level_from_events([]) is None


def test_unit_baseline_is_establish_level() -> None:
    """基线档 = establish 事件的 to_level（建档时点承诺档）。"""
    events: list[dict[str, Any]] = [
        {"action": "establish", "from_level": None, "to_level": "required"},
        {"action": "downgrade", "from_level": "required", "to_level": "optional"},
    ]
    assert baseline_level_from_events(events) == "required"


def test_unit_baseline_tighten_does_not_move_anchor() -> None:
    """收紧不改基线：optional 建档 → tighten required → 合法下调回 optional
    → 基线仍 optional（净放松 = 0，拦截不触发——决策单 ③ 语义精确化钉）。"""
    events: list[dict[str, Any]] = [
        {"action": "establish", "from_level": None, "to_level": "optional"},
        {"action": "tighten", "from_level": "optional", "to_level": "required"},
        {"action": "downgrade", "from_level": "required", "to_level": "optional"},
    ]
    assert baseline_level_from_events(events) == "optional"


def test_unit_baseline_ignores_garbage_payloads() -> None:
    """事件 payload 混入垃圾/非 dict 形状 → 跳过（只认 establish + 三档枚举）。"""
    events: list[dict[str, Any]] = [
        {"to_level": "bogus"},
        {"action": "establish", "to_level": ""},
        {"unrelated": True},
    ]
    assert baseline_level_from_events(events) is None
    events.append({"action": "establish", "to_level": "none"})
    assert baseline_level_from_events(events) == "none"


def test_unit_baseline_takes_first_establish() -> None:
    """取输入序首个 establish（调用方保证 occurred_at asc；单门禁 establish
    至多一次——重复 establish 仅防御性取先）。"""
    events: list[dict[str, Any]] = [
        {"action": "establish", "to_level": "optional"},
        {"action": "establish", "to_level": "required"},
    ]
    assert baseline_level_from_events(events) == "optional"


# ---------------------------------------------------------------- 纯单元：拦截判定


def test_unit_hold_inactive_when_breaker_closed() -> None:
    """熔断窗口关闭 → 下调生效如常（拦截零触发）。"""
    assert s12_runtime_hold_target("optional", "required", False) is None


def test_unit_hold_inactive_without_anchor() -> None:
    """无基线档（事件缺失）→ 不拦。"""
    assert s12_runtime_hold_target("optional", None, True) is None


def test_unit_hold_out_of_row_level_domain() -> None:
    """全局 strong/weak 直映档不经行值通道 → 不在拦截域（环境闸治理面）。"""
    assert s12_runtime_hold_target("weak", "required", True) is None
    assert s12_runtime_hold_target("strong", "required", True) is None


def test_unit_hold_fires_on_relaxed_dependency() -> None:
    """净放松档 + 熔断窗口 → 回退基线档执行。"""
    assert s12_runtime_hold_target("optional", "required", True) == "required"
    assert s12_runtime_hold_target("none", "required", True) == "required"
    assert s12_runtime_hold_target("none", "optional", True) == "optional"


def test_unit_hold_inactive_at_or_above_anchor() -> None:
    """当前档不松于基线（平档/更严）→ 不拦。"""
    assert s12_runtime_hold_target("optional", "optional", True) is None
    assert s12_runtime_hold_target("required", "optional", True) is None


# ---------------------------------------------------------------- E2E（随套件跑，conftest 供测试库）

from test_m5_wp2_gate_governance import (  # noqa: E402  (pytest fixture 供给方，沿仓内先例)
    _decide,
    _settings_with,
    _submit_gate_evidence,
    db_gate,
    latest_receipt,
    m5_env,
)


def _hold_env(m5_env: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """per_gate + enabled + mock 接管 client 工厂（熔断态经 mock.breaker_state 摆布）。"""
    env = m5_env
    _settings_with(env, ontology_gate_dependency="per_gate", ontology_enabled=True)
    mock = env["mock"]
    monkeypatch.setattr(
        "fde_api.projects.gate_ontology.client_from_settings", lambda: mock
    )
    return env


def _establish_then_downgrade(env: dict[str, Any], db_session: Any, gate: Any) -> None:
    """admin 建档 required → leader（Owner 异人）下调 optional（非熔断窗，合法落值）。"""
    set_gate_dependency(
        db_session,
        actor=env["admin"].user,
        project_id=env["project"]["id"],
        gate=gate,
        new_level="required",
    )
    set_gate_dependency(
        db_session,
        actor=env["leader"].user,
        project_id=env["project"]["id"],
        gate=gate,
        new_level="optional",
    )


def test_e2e_hold_suspends_relaxed_dependency_on_decision(
    m5_env, db_session, monkeypatch
) -> None:
    """核心缺口闭环：下调值落库后熔断才打开 → 拍板按基线档 required 挂起 409。

    A 版行为（修复前）= optional 档 degraded 200 放行——S-12「宁可挂起，
    不带病降级」在生效存续期无拦截语义（备忘 §1.1）。对照组同条件仅熔断
    窗差异：窗口关闭时 optional 放行 200 degraded（下调合法生效）。
    """
    env = _hold_env(m5_env, monkeypatch)
    mock = env["mock"]
    gate_hold = db_gate(env, "G5", db_session)
    gate_ctrl = db_gate(env, "G6", db_session)
    _establish_then_downgrade(env, db_session, gate_hold)
    _establish_then_downgrade(env, db_session, gate_ctrl)

    # 对照组：熔断窗口关闭（mock 缺省 closed）→ optional 放行（degraded）
    mock.inject_fault("unavailable")
    _submit_gate_evidence(env, "G6")
    resp = _decide(env, "G6", {"result": "pass"})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    rec_ctrl = latest_receipt(env)
    assert rec_ctrl.ontology_degradation == "degraded"
    assert rec_ctrl.breaker_state == "closed"
    assert "s12_runtime_hold" not in rec_ctrl.ontology_checks_json

    # 实验组：熔断窗口打开 → 按基线档 required 求值 → 本体不可用 → 409 挂起
    mock.breaker_state = "open"
    _submit_gate_evidence(env, "G5")
    resp = _decide(env, "G5", {"result": "pass"})
    assert resp.status_code == 409, resp.get_data(as_text=True)
    assert resp.json["error"]["code"] == "gate_ontology_unavailable"


def test_e2e_hold_annotation_frozen_into_receipt(m5_env, db_session, monkeypatch) -> None:
    """回退档求值放行路径：执行档改写 + 标注 + breaker_state 随回执固化。"""
    env = _hold_env(m5_env, monkeypatch)
    gate = db_gate(env, "G5", db_session)
    _establish_then_downgrade(env, db_session, gate)

    env["mock"].breaker_state = "open"  # summary 正常（无 fault）：required 可用 → online
    _submit_gate_evidence(env, "G5")
    resp = _decide(env, "G5", {"result": "pass"})
    assert resp.status_code == 200, resp.get_data(as_text=True)

    rec = latest_receipt(env)
    assert rec.ontology_degradation == "online"
    checks = rec.ontology_checks_json
    assert checks["effective_dependency"] == "required"  # 执行档（非放松档）
    hold = checks["s12_runtime_hold"]
    assert hold["held"] is True
    assert hold["relaxed_level"] == "optional"
    assert hold["enforced_level"] == "required"
    assert hold["breaker_state"] == "open"
    assert rec.breaker_state == "open"


def test_e2e_no_hold_without_event_history(m5_env, db_session, monkeypatch) -> None:
    """ORM 直写档位（无事件流）→ 不虚构基线：熔断窗内 optional 照常放行。

    同时钉死既有 S-16 用例形态（``test_s16_dependency_tiers`` 直写
    ``gate.ontology_dependency``）零回归——拦截只认 set_gate_dependency
    通道留痕的历史；degraded 放行路径同样带 breaker_state 细值。
    """
    env = _hold_env(m5_env, monkeypatch)
    gate = db_gate(env, "G5", db_session)
    gate.ontology_dependency = "optional"
    db_session.commit()

    env["mock"].breaker_state = "open"
    env["mock"].inject_fault("unavailable")
    _submit_gate_evidence(env, "G5")
    resp = _decide(env, "G5", {"result": "pass"})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    rec = latest_receipt(env)
    assert rec.ontology_degradation == "degraded"
    assert rec.breaker_state == "open"  # degraded 路径同样留痕（非 NULL）
    assert "s12_runtime_hold" not in rec.ontology_checks_json


def test_e2e_global_direct_tier_not_held(m5_env, db_session, monkeypatch) -> None:
    """全局 weak 直映档 → 行值净放松不在拦截域（环境闸治理面非 S-12 门禁域）。"""
    env = _hold_env(m5_env, monkeypatch)
    _settings_with(env, ontology_gate_dependency="weak", ontology_enabled=True)
    gate = db_gate(env, "G5", db_session)
    _establish_then_downgrade(env, db_session, gate)
    # 继续下调至 none（同 leader，熔断窗 mock 缺省 closed → 合法）
    set_gate_dependency(
        db_session,
        actor=env["leader"].user,
        project_id=env["project"]["id"],
        gate=gate,
        new_level="none",
    )

    env["mock"].breaker_state = "open"
    env["mock"].inject_fault("unavailable")
    _submit_gate_evidence(env, "G5")
    resp = _decide(env, "G5", {"result": "pass"})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    rec = latest_receipt(env)
    assert rec.ontology_degradation == "degraded"
    assert "s12_runtime_hold" not in rec.ontology_checks_json


def test_e2e_write_gate_regression_breaker_blocks_downgrade(
    m5_env, db_session
) -> None:
    """A 写值闸零回归：熔断窗口内下调仍 409 circuit_open_no_downgrade。"""
    env = m5_env
    gate = db_gate(env, "G5", db_session)
    set_gate_dependency(
        db_session,
        actor=env["admin"].user,
        project_id=env["project"]["id"],
        gate=gate,
        new_level="required",
    )
    with pytest.raises(GateOntologyError) as circuit:
        set_gate_dependency(
            db_session,
            actor=env["leader"].user,
            project_id=env["project"]["id"],
            gate=gate,
            new_level="optional",
            breaker_open=True,
        )
    assert circuit.value.code == "circuit_open_no_downgrade"
    assert gate.ontology_dependency == "required"  # 零落值


def test_e2e_hold_events_scoped_to_gate(m5_env, db_session) -> None:
    """事件回放按 gate.id 隔离：gate1 的下调历史不污染 gate2 的基线档。"""
    env = m5_env
    gate1 = db_gate(env, "G5", db_session)
    set_gate_dependency(
        db_session,
        actor=env["admin"].user,
        project_id=env["project"]["id"],
        gate=gate1,
        new_level="required",
    )
    set_gate_dependency(
        db_session,
        actor=env["leader"].user,
        project_id=env["project"]["id"],
        gate=gate1,
        new_level="optional",
    )
    # gate2 无任何事件：无基线 → None；gate1 基线 = establish 档 required
    events1 = list(
        db_session.scalars(
            select(OperationEvent).where(OperationEvent.target_id == gate1.id)
        )
    )
    assert baseline_level_from_events([e.changes for e in events1]) == "required"
    assert baseline_level_from_events([]) is None
