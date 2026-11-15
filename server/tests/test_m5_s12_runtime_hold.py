"""V3.3 M5 遗留④：S-12 运行时激活拦截（混合形态，TDD）。

契约依据 = Fde-Ontology ``docs/v3.3/m5/08-s12-form-factor-decision.md``
（P1 2026-11-16「全部批准」拍板：混合形态）+ challenger 备忘
``docs/v3.3/m5/07-s12-two-step-best-case-memo.md`` §1.1/§3：
- A 写值三闸不动（``set_gate_dependency`` 既有行为零回归）；
- 新增**求值时点**运行时拦截：熔断窗口内，门禁生效依赖档若为「该门禁
  历史最严档以来的净放松值」，不按放松档执行——按收紧锚档继续求值
  （required/strong 档本体不可用即 409 挂起＝「宁可挂起，不带病降级」
  在时间维度上的运行时化），并在 ``checks["s12_runtime_hold"]`` 显式
  标注（随回执 ``ontology_checks_json`` 固化）；
- 收紧锚 = ``operation_events`` 回放的历史最严档（**零 DDL**——Gate 行
  只存建档人与当前值，事件流即历史）；无任何事件（ORM 直写/建档前历史
  缺失）→ 不虚构更严档，拦截不触发；
- 全局 strong/weak 直映档不经门禁行值通道，不在本拦截域（环境闸治理面）。

顺带补齐 D5 半接线：回执 ``breaker_state`` 列此前只读未写——
``freeze_gate_receipt`` 从 ``checks["breaker_state"]`` 取值落列（观测值列，
不进两级哈希口径）。

纯单元组（``baseline_level_from_events`` / ``s12_runtime_hold_target``）
本地可跑（无 DB fixture）；E2E 组依赖 CI MySQL（conftest ``FDE_TEST_DATABASE_URL``），
无该环境变量时自动跳过。
"""

from __future__ import annotations

import os
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

requires_db = pytest.mark.skipif(
    not os.environ.get("FDE_TEST_DATABASE_URL", "").strip(),
    reason="E2E 需要 CI MySQL（conftest FDE_TEST_DATABASE_URL 供应）",
)

# ---------------------------------------------------------------- 纯单元：收紧锚回放


def test_unit_baseline_none_without_events_or_level() -> None:
    """无事件且当前值缺省 → 无收紧锚（拦截不触发，不虚构更严档）。"""
    assert baseline_level_from_events([], None) is None
    single: list[dict[str, Any]] = [{"to_level": "optional"}]
    assert baseline_level_from_events(single, None) == "optional"


def test_unit_baseline_current_level_alone_is_anchor() -> None:
    """无事件但有当前值 → 当前值即锚（建档即最严档的门禁永不触发）。"""
    assert baseline_level_from_events([], "required") == "required"
    assert baseline_level_from_events([], "optional") == "optional"


def test_unit_baseline_downgrade_reveals_strictest_anchor() -> None:
    """required 建档 → downgrade optional：回放得历史最严档 required。"""
    events: list[dict[str, Any]] = [
        {"action": "establish", "from_level": None, "to_level": "required"},
        {"action": "downgrade", "from_level": "required", "to_level": "optional"},
    ]
    assert baseline_level_from_events(events, "optional") == "required"


def test_unit_baseline_ignores_garbage_payloads() -> None:
    """事件 payload 混入垃圾 to_level → 忽略（只认严格序三档枚举）。"""
    events: list[dict[str, Any]] = [
        {"to_level": "bogus"},
        {"to_level": ""},
        {"unrelated": True},
        {"to_level": "none"},
    ]
    assert baseline_level_from_events(events, "none") == "none"
    # 垃圾之外存在 required → 仍取最严
    events.append({"to_level": "required"})
    assert baseline_level_from_events(events, "none") == "required"


def test_unit_baseline_order_independent() -> None:
    """回放取 max 严格度——与事件顺序无关（免疫同秒时序不确定）。"""
    forward: list[dict[str, Any]] = [
        {"to_level": "required"},
        {"to_level": "optional"},
        {"to_level": "none"},
    ]
    backward = list(reversed(forward))
    assert baseline_level_from_events(forward, "none") == "required"
    assert baseline_level_from_events(backward, "none") == "required"


# ---------------------------------------------------------------- 纯单元：拦截判定


def test_unit_hold_inactive_when_breaker_closed() -> None:
    """熔断窗口关闭 → 下调生效如常（拦截零触发）。"""
    assert s12_runtime_hold_target("optional", "required", False) is None


def test_unit_hold_inactive_without_anchor() -> None:
    """无收紧锚（事件缺失）→ 不拦。"""
    assert s12_runtime_hold_target("optional", None, True) is None


def test_unit_hold_out_of_row_level_domain() -> None:
    """全局 strong/weak 直映档不经行值通道 → 不在拦截域（环境闸治理面）。"""
    assert s12_runtime_hold_target("weak", "required", True) is None
    assert s12_runtime_hold_target("strong", "required", True) is None


def test_unit_hold_fires_on_relaxed_dependency() -> None:
    """净放松档 + 熔断窗口 → 回退收紧锚档执行。"""
    assert s12_runtime_hold_target("optional", "required", True) == "required"
    assert s12_runtime_hold_target("none", "required", True) == "required"
    assert s12_runtime_hold_target("none", "optional", True) == "optional"


def test_unit_hold_inactive_at_or_above_anchor() -> None:
    """当前档不松于锚（平档/更严）→ 不拦。"""
    assert s12_runtime_hold_target("optional", "optional", True) is None
    assert s12_runtime_hold_target("required", "optional", True) is None


# ---------------------------------------------------------------- E2E（CI MySQL）


def _hold_env(
    m5_env: dict[str, Any], db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Any]:
    """per_gate + enabled + mock 接管 client 工厂（熔断态可经 mock.breaker_state 摆布）。"""
    from test_m5_wp2_gate_governance import _settings_with

    env = m5_env
    _settings_with(env, ontology_gate_dependency="per_gate", ontology_enabled=True)
    mock = env["mock"]
    monkeypatch.setattr(
        "fde_api.projects.gate_ontology.client_from_settings", lambda: mock
    )
    return env


def _establish_then_downgrade(env: dict[str, Any], db_session: Any, gate: Any) -> None:
    """admin 建档 required → leader（Owner 异人）下调 optional（非熔断窗，合法落值）。"""
    from test_m5_wp2_gate_governance import db_gate

    gate = gate or db_gate(env, "G5", db_session)
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


@requires_db
def test_e2e_hold_suspends_relaxed_dependency_on_decision(
    m5_env, db_session, monkeypatch
) -> None:
    """核心缺口闭环：下调值落库后熔断才打开 → 拍板按收紧锚 required 挂起 409。

    A 版行为（修复前）= optional 档 degraded 200 放行——S-12「宁可挂起，
    不带病降级」在生效存续期无拦截语义（备忘 §1.1）。对照组同条件仅熔断
    窗差异：窗口关闭时 optional 放行 200 degraded（下调合法生效）。
    """
    from test_m5_wp2_gate_governance import (
        _decide,
        _submit_gate_evidence,
        db_gate,
        latest_receipt,
    )

    env = _hold_env(m5_env, db_session, monkeypatch)
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
    assert latest_receipt(env).ontology_degradation == "degraded"

    # 实验组：熔断窗口打开 → 按收紧锚 required 求值 → 本体不可用 → 409 挂起
    mock.breaker_state = "open"
    _submit_gate_evidence(env, "G5")
    resp = _decide(env, "G5", {"result": "pass"})
    assert resp.status_code == 409, resp.get_data(as_text=True)
    assert resp.json["error"]["code"] == "gate_ontology_unavailable"


@requires_db
def test_e2e_hold_annotation_frozen_into_receipt(m5_env, db_session, monkeypatch) -> None:
    """回退档求值放行路径：checks 标注 + breaker_state 随回执固化（D5 半接线补齐）。"""
    from test_m5_wp2_gate_governance import (
        _decide,
        _submit_gate_evidence,
        db_gate,
        latest_receipt,
    )

    env = _hold_env(m5_env, db_session, monkeypatch)
    gate = db_gate(env, "G5", db_session)
    _establish_then_downgrade(env, db_session, gate)

    env["mock"].breaker_state = "open"  # summary 正常（无 fault）：required 可用 → online
    _submit_gate_evidence(env, "G5")
    resp = _decide(env, "G5", {"result": "pass"})
    assert resp.status_code == 200, resp.get_data(as_text=True)

    rec = latest_receipt(env)
    assert rec.ontology_degradation == "online"
    hold = rec.ontology_checks_json["s12_runtime_hold"]
    assert hold["held"] is True
    assert hold["relaxed_level"] == "optional"
    assert hold["enforced_level"] == "required"
    assert hold["breaker_open"] is True
    assert rec.breaker_state == "open"


@requires_db
def test_e2e_no_hold_without_event_history(m5_env, db_session, monkeypatch) -> None:
    """ORM 直写档位（无事件流）→ 不虚构更严档：熔断窗内 optional 照常放行。

    同时钉死既有 S-16 用例形态（``test_s16_dependency_tiers`` 直写
    ``gate.ontology_dependency``）零回归——拦截只认 set_gate_dependency
    通道留痕的历史。
    """
    from test_m5_wp2_gate_governance import (
        _decide,
        _submit_gate_evidence,
        db_gate,
        latest_receipt,
    )

    env = _hold_env(m5_env, db_session, monkeypatch)
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
    assert "s12_runtime_hold" not in rec.ontology_checks_json


@requires_db
def test_e2e_global_direct_tier_not_held(m5_env, db_session, monkeypatch) -> None:
    """全局 weak 直映档 → 行值净放松不在拦截域（环境闸治理面非 S-12 门禁域）。"""
    from test_m5_wp2_gate_governance import (
        _decide,
        _settings_with,
        _submit_gate_evidence,
        db_gate,
        latest_receipt,
    )

    env = _hold_env(m5_env, db_session, monkeypatch)
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


@requires_db
def test_e2e_write_gate_regression_breaker_blocks_downgrade(
    m5_env, db_session
) -> None:
    """A 写值闸零回归：熔断窗口内下调仍 409 circuit_open_no_downgrade。"""
    from test_m5_wp2_gate_governance import db_gate

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


@requires_db
def test_e2e_hold_events_scoped_to_gate(m5_env, db_session) -> None:
    """事件回放按 gate.id 隔离：gate1 的下调历史不污染 gate2 的收紧锚。"""
    from test_m5_wp2_gate_governance import db_gate

    env = m5_env
    gate1 = db_gate(env, "G5", db_session)
    gate2 = db_gate(env, "G6", db_session)
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
    # gate2 无任何事件：锚 = 当前值（None）→ None；gate1 锚 = required
    events1 = list(
        db_session.scalars(
            select(OperationEvent).where(OperationEvent.target_id == gate1.id)
        )
    )
    assert baseline_level_from_events(
        [e.changes for e in events1], gate1.ontology_dependency
    ) == "required"
    assert baseline_level_from_events([], gate2.ontology_dependency) is None
