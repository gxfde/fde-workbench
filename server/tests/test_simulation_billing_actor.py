"""billing_actor_policy 机制化（L6 条款④）：模拟域 L-B 模型评估的 AI 记账主体。

候选卡 ``provenance.billing_actor_policy`` 写死 ``service_account`` 只是**政策
声明**；本组测试钉住**机制真身**（走真实 ``DeepSeekClient``＋假 HTTP 会话
注入 ``fde_api_simulation_deepseek`` 扩展点，预算闸／审计／契约校验全走生产
代码路径，不触网）：

- **开关关**（``simulation_ai_actor_username`` 未配置）：真模型评估（server
  腿）回落既有行为——记账记**调用者**（请求上下文），对存量模拟零回归
  （蔡工 2026-11-15 拍板②：opt-in，非硬闸）；
- **开关开**：预算闸与 ``ai_call_audits`` 归因落到配置的**服务账号**头上
  （直连腿读 ``ai_actor_override``、DSH 腿读 ``ai_actor_id``——双 ContextVar
  由 evaluator 在 include_model 分支 set/reset 配对注入）；
- **账号不存在 / 已停用**：fail-closed 503 ``simulation_ai_unavailable``
  （仿诊断域 ``resolve_ai_actor`` 先例），不静默降级；
- **无泄漏**：set/reset 配对复位——评估完成后覆盖不得泄漏给后续请求腿
  （translator/jobs.py token 复位先例）。
"""
from __future__ import annotations

import json as _json
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, func, select

from conftest import INITIAL_PASSWORD
from fde_api.ai.auditing import ai_actor_override
from fde_api.ai.deepseek import DeepSeekClient
from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from fde_api.extensions import db
from fde_api.simulation import run_service
from fde_api.simulation.evaluator import evaluate_run
from fde_api.simulation.models import (
    SimulationActor,
    SimulationEvaluation,
    SimulationRun,
    SimulationScenario,
    SimulationTrace,
)
from fde_api.workbench.models import AICallAudit

__all__ = []


# ---------------------------------------------------------------------------
# 基建（先例：test_simulation_evaluation.py / test_simulation_real_wiring.py）
# ---------------------------------------------------------------------------

# 契约合格输出（evaluation_schema.parse_model_evaluation 全绿形状）
_VALID_EVAL_CONTENT = _json.dumps(
    {
        "criteria": [
            {
                "key": "M-01",
                "dimension": "D1",
                "title": "是否点到了关键问题",
                "score": 0.8,
                "verdict": "pass",
                "evidence_refs": [
                    {"kind": "artifact", "text": "维修记录是纸质的，没有结构化字段"}
                ],
                "reason": "命中知识采集前置",
            }
        ],
        "summary": "命中根因",
    },
    ensure_ascii=False,
)


class _FakeHttpResponse:
    """最小响应替身：status_code＋json()（DeepSeekClient 成功腿只读这两面）。"""

    status_code = 200

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class _FakeHttpSession:
    """假供应商端点：返回契约合格 JSON（含 usage，审计行有 token 数）。
    ``post`` 调用记到**实例**属性 ``calls``（供断言「真模型腿被消费过」）。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def post(self, url: str, **kwargs) -> _FakeHttpResponse:
        self.calls.append(url)
        return _FakeHttpResponse(
            {
                "choices": [{"message": {"content": _VALID_EVAL_CONTENT}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20},
            }
        )


def _injected_client() -> tuple[DeepSeekClient, _FakeHttpSession]:
    """注入点替身：**真实 DeepSeekClient**（预算闸/审计/契约全走生产代码）
    ＋假 HTTP 会话（不触网）。经 app.extensions 注入，model_evaluation
    的 ``_simulation_client()`` 原样消费。"""
    fake_http = _FakeHttpSession()
    client = DeepSeekClient(
        base_url="https://sim-eval.invalid",
        api_key="sim-fake-key",
        model="sim-eval-model",
        timeout_seconds=1,
        session=fake_http,
        sleep=lambda _delay: None,
    )
    return client, fake_http


def _scenario_payload(case_code: str = "CASE-BILL-001") -> dict:
    return {
        "name": "记账测试案例",
        "industry": "general_manufacturing",
        "variant": "normal",
        "split": "train",
        "content": {
            "case_code": case_code,
            "customer_profile": {
                "company_type": "测试用制造企业",
                "stakeholders": ["质量主管"],
                "maturity": "基础台账",
            },
            "visible": {
                "initial_brief": ["设备经常坏，找不到原因"],
                "known_systems": ["ERP"],
                "constraints": {"budget": "10 万"},
            },
            "hidden": {
                "facts": [
                    {
                        "fact_id": "B-F1",
                        "text": "维修记录是纸质的，没有结构化字段",
                        "category": "knowledge",
                        "disclosure_stage": "interview",
                        "probe_keywords": ["维修", "记录"],
                    }
                ]
            },
            "misleading_request": "上 AI 预测性维护",
            "seed_data": {"crm": {"leads": [{"company": "示例"}]}},
        },
        "reference": {
            "expected_outcomes": ["识别知识采集前置"],
            "acceptance_criteria": ["验收标准可度量"],
            "rubric": {
                "must_identify": ["知识采集前置"],
                "must_avoid": ["以模型精度为核心承诺"],
                "must_produce": ["知识采集方案"],
            },
        },
    }


def _make_client(db_session, settings, role: str = "fde_engineer") -> tuple[User, dict]:
    user = User(
        username=f"sim.bill.{role}.{uuid.uuid4().hex[:8]}",
        display_name="Simulation billing",
        role=role,
        password_hash=hash_password(INITIAL_PASSWORD),
        must_change_password=False,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    headers = {"Authorization": f"Bearer {issue_access_token(user, settings)}"}
    return user, headers


def _create_run(db_session, user: User, settings) -> str:
    """建场景＋mock 执行＋提交，返回 run_id（确定性腿完成态）。"""
    db_session.execute(
        delete(SimulationScenario).where(SimulationScenario.name == "记账测试案例")
    )
    scenario = SimulationScenario(
        scenario_key="CASE-BILL-001",
        name="记账测试案例",
        industry="general_manufacturing",
        variant="normal",
        split="train",
        status="active",
        tags=[],
        content_json=_scenario_payload()["content"],
        reference_json=_scenario_payload()["reference"],
        version=1,
    )
    db_session.add(scenario)
    db_session.flush()
    db_session.commit()
    result = run_service.create_run(
        actor=user,
        payload={
            "scenario_id": scenario.id,
            "adapter_mode": "mock",
            "execute": True,
            "config": {"max_rounds": 2},
        },
    )
    assert result["status"] == "completed", result.get("status")
    return result["id"]


def _call_evaluate(app, user: User, run_id: str, model_mode: str = "server") -> dict:
    """在应用上下文中跑评估（预算闸/审计走真实 request-context 语义）。"""
    with app.test_request_context():
        return evaluate_run(actor=user, run_id=run_id, model_mode=model_mode)


@pytest.fixture
def service_account(db_session) -> User:
    """平台服务账号（billing_actor_policy 的记账主体，org_id=None ⇒ 实例额度账）。"""
    user = User(
        username=f"svc.sim-{uuid.uuid4().hex[:8]}",
        display_name="模拟域 AI 记账服务账号",
        role="fde_engineer",
        password_hash=hash_password(INITIAL_PASSWORD),
        must_change_password=False,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def caller(client, db_session, settings) -> tuple[User, dict, str]:
    """调用者（fde_engineer ⇒ project_operator 档，满足 REQUIRED_LEVEL）。"""
    user, headers = _make_client(db_session, settings, role="fde_engineer")
    run_id = _create_run(db_session, user, settings)
    return user, headers, run_id


@pytest.fixture
def injected_client(app):
    deepseek_client, fake_http = _injected_client()
    app.extensions["fde_api_simulation_deepseek"] = deepseek_client
    try:
        yield fake_http
    finally:
        app.extensions.pop("fde_api_simulation_deepseek", None)


def _set_simulation_actor(app, username: str | None, **extra: object) -> None:
    """改 SETTINGS（diagnostics 先例 model_copy 同构；app 侧引用即生效）。"""
    app.config["SETTINGS"] = app.config["SETTINGS"].model_copy(
        update={"simulation_ai_actor_username": username or "", **extra}
    )


def _seed_audits(db_session, actor_user_id: str, *, input_tokens: int, output_tokens: int) -> None:
    """种一条本月已用量审计行（预算闸汇总口径：status succeeded＋当月）。"""
    db_session.add(
        AICallAudit(
            request_id=f"bill-test-{uuid.uuid4().hex[:8]}",
            actor_user_id=actor_user_id,
            purpose="simulation_evaluation",
            model="sim-test-model",
            used_fallback=False,
            duration_ms=10,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            status="succeeded",
            error_code=None,
            created_at=datetime.now(UTC).replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            ),
        )
    )
    db_session.commit()


def _audit_count(db_session, actor_user_id: str | None) -> int:
    """本月模拟评估审计行数（预算闸汇总含 succeeded＋budget_blocked）。"""
    condition = (
        AICallAudit.actor_user_id == actor_user_id
        if actor_user_id is not None
        else AICallAudit.actor_user_id.is_(None)
    )
    month_start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return int(
        db_session.scalar(
            select(func.count(AICallAudit.id)).where(
                condition,
                AICallAudit.purpose == "simulation_evaluation",
                AICallAudit.created_at >= month_start,
                AICallAudit.status.in_(("succeeded", "budget_blocked")),
            )
        )
        or 0
    )


@pytest.fixture(autouse=True)
def _clean_billing(db_session):
    yield
    db_session.rollback()
    db_session.execute(
        delete(AICallAudit).where(AICallAudit.request_id.like("bill-test-%"))
    )
    db_session.execute(delete(AICallAudit).where(AICallAudit.model == "sim-eval-model"))
    db_session.execute(delete(SimulationEvaluation))
    db_session.execute(delete(SimulationTrace))
    db_session.execute(delete(SimulationActor))
    db_session.execute(delete(SimulationRun))
    db_session.execute(delete(SimulationScenario).where(SimulationScenario.name == "记账测试案例"))
    db_session.execute(delete(User).where(User.username.like("sim.bill.%")))
    db_session.execute(delete(User).where(User.username.like("svc.sim-%")))
    db_session.commit()


# ---------------------------------------------------------------------------
# ① 开关关 ⇒ 回落调用者（零回归）
# ---------------------------------------------------------------------------


def test_switch_off_bills_caller_via_request_leg(
    app, client, db_session, caller, injected_client, settings
):
    """请求腿（POST /evaluate）：开关关 ⇒ 记账主体＝调用者（g.current_user）。"""
    user, headers, run_id = caller
    _set_simulation_actor(app, None)

    response = client.post(
        f"/api/v1/simulation/runs/{run_id}/evaluate",
        headers=headers,
        query_string={"model_mode": "server", "include_model": "true"},
    )
    assert response.status_code == 200, response.get_json()
    report = response.get_json()["data"]
    # model 行序列化形状无 status 字段——verdict 承载状态（成功=pass，0.8≥0.75）
    assert report["model"]["verdict"] == "pass"
    assert report["model"]["total_score"] == 0.8
    # 记账与审计归因都是调用者，服务账号零归因
    assert _audit_count(db_session, user.id) == 1
    assert ai_actor_override.get() is None


def test_switch_off_direct_call_bills_noone_not_service_account(
    app, db_session, caller, injected_client
):
    """直接调用腿（worker 语义，无 g.current_user）：开关关 ⇒ actor None
    （预算闸 fail-open 放行）——既非调用者、也非服务账号。"""
    user, _headers, run_id = caller
    _set_simulation_actor(app, None)

    report = _call_evaluate(app, user, run_id, model_mode="server")
    assert report["model"]["verdict"] == "pass"
    assert _audit_count(db_session, None) == 1
    assert _audit_count(db_session, user.id) == 0


# ---------------------------------------------------------------------------
# ② 开关开 ⇒ 预算闸与审计记服务账号
# ---------------------------------------------------------------------------


def test_switch_on_bills_service_account_with_budget_gate(
    app, client, db_session, caller, service_account, injected_client, settings
):
    """服务账号当月已用量 500 ≥ 预算 300 ⇒ 闸按**服务账号**判定拦下评估；
    回落调用者（审计 0）则 0<300 放行——本测以「拦截成功」证明闸主体已换。"""
    user, headers, run_id = caller
    _set_simulation_actor(
        app, service_account.username, ai_monthly_token_budget=300
    )
    _seed_audits(db_session, service_account.id, input_tokens=500, output_tokens=0)

    response = client.post(
        f"/api/v1/simulation/runs/{run_id}/evaluate",
        headers=headers,
        query_string={"model_mode": "server"},
    )
    assert response.status_code == 200, response.get_json()
    model = response.get_json()["data"]["model"]
    # 被预算闸拦 ⇒ 非 retryable DeepSeekError ⇒ 模型行 verdict=unavailable、零分数
    assert model["verdict"] == "unavailable"
    assert model["total_score"] == 0.0
    assert "ai_budget_exceeded" in model["note"]
    # 预算 blocked 行归服务账号（request_id 即供应商请求 id）
    row = db_session.scalar(
        select(AICallAudit)
        .where(
            AICallAudit.request_id == "simulation-evaluation",
            AICallAudit.status == "budget_blocked",
        )
        .order_by(AICallAudit.created_at.desc())
        .limit(1)
    )
    assert row is not None and row.actor_user_id == service_account.id
    # 调用者零归因（机制生效的判别力：回落调用者本应 0<300 放行出分数）
    assert _audit_count(db_session, user.id) == 0


def test_switch_on_audits_attributed_to_service_account(
    app, client, db_session, caller, service_account, injected_client, settings
):
    """开关开⇒审计行 actor_user_id＝服务账号；调用者零归因。"""
    user, headers, run_id = caller
    _set_simulation_actor(app, service_account.username)

    response = client.post(
        f"/api/v1/simulation/runs/{run_id}/evaluate",
        headers=headers,
        query_string={"model_mode": "server"},
    )
    assert response.status_code == 200, response.get_json()
    model = response.get_json()["data"]["model"]
    assert model["verdict"] == "pass"
    assert model["total_score"] == 0.8

    assert _audit_count(db_session, service_account.id) == 1
    assert _audit_count(db_session, user.id) == 0
    row = db_session.scalar(
        select(AICallAudit).where(
            AICallAudit.actor_user_id == service_account.id,
            AICallAudit.purpose == "simulation_evaluation",
            AICallAudit.status == "succeeded",
        )
    )
    assert row is not None
    # 用量真身来自假端点 usage（input 10 / output 20）
    assert (row.input_tokens, row.output_tokens) == (10, 20)
    # 真模型腿被消费过（假端点收到过一次 POST）
    assert len(injected_client.calls) == 1


# ---------------------------------------------------------------------------
# ③ fail-closed：账号不存在 / 已停用 ⇒ 503 simulation_ai_unavailable
# ---------------------------------------------------------------------------


def test_unknown_actor_fails_closed_503(app, client, db_session, caller, injected_client, settings):
    user, headers, run_id = caller
    _set_simulation_actor(app, f"svc.missing-{uuid.uuid4().hex[:8]}")

    response = client.post(
        f"/api/v1/simulation/runs/{run_id}/evaluate",
        headers=headers,
        query_string={"model_mode": "server"},
    )
    assert response.status_code == 503, response.get_json()
    body = response.get_json()
    assert body["error"]["code"] == "simulation_ai_unavailable"
    # fail-closed ⇒ 模型层未执行 ⇒ 零审计、零端点调用
    assert _audit_count(db_session, user.id) == 0
    assert injected_client.calls == []


def test_deactivated_actor_fails_closed_503(
    app, client, db_session, caller, service_account, injected_client, settings
):
    user, headers, run_id = caller
    service_account.is_active = False
    db_session.commit()
    _set_simulation_actor(app, service_account.username)

    response = client.post(
        f"/api/v1/simulation/runs/{run_id}/evaluate",
        headers=headers,
        query_string={"model_mode": "server"},
    )
    assert response.status_code == 503, response.get_json()
    assert response.get_json()["error"]["code"] == "simulation_ai_unavailable"
    assert _audit_count(db_session, service_account.id) == 0
    assert injected_client.calls == []


# ---------------------------------------------------------------------------
# ④ 无泄漏：set/reset 配对复位（同一 run 连评，开→关不串账）
# ---------------------------------------------------------------------------


def test_no_contextvar_leak_across_calls(
    app, db_session, caller, service_account, injected_client
):
    user, _headers, run_id = caller
    _set_simulation_actor(app, service_account.username)
    assert ai_actor_override.get() is None

    # 开 ⇒ 评估（记账服务账号）
    _call_evaluate(app, user, run_id, model_mode="server")
    assert ai_actor_override.get() is None, "评估后覆盖不得泄漏到后续调用"
    assert _audit_count(db_session, service_account.id) == 1

    # 关 ⇒ 同一 run 重评回落既有行为（actor None），证明前一次 set 已 reset
    _set_simulation_actor(app, None)
    _call_evaluate(app, user, run_id, model_mode="server")
    assert _audit_count(db_session, None) == 1
    assert _audit_count(db_session, service_account.id) == 1, "重评不得串到服务账号"
