"""goal-d9：翻译器门户（PRD §3.2 P3）。

- 创建→outbox 投递→job 消费→guidance 全契约草稿落库（confirmed 一律 False）。
- 重试语义沿预调研分析：瞬时错误退避重试、契约违反立即重试、耗尽落 failed
  分类可见、终态幂等跳过（重放不二次调 AI）。
- 归属：翻译草稿是个人席位资产（本人或 admin 可读）。
- 语义钉子：TRANSLATOR_RETRY_LIMIT、RECOVERABLE_JOB_TYPES 含 translator.translate。
"""
from __future__ import annotations

import pytest

from test_agents_d4_harness import d4_app, d4_client, d4_settings  # noqa: F401  (pytest fixture)
from test_metrics_report import _user

from conftest import INITIAL_PASSWORD
from fde_api.ai.deepseek import DeepSeekError
from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from fde_api.guidance.ai_schema import LIST_FIELDS
from fde_api.jobs.models import BackgroundJob, OutboxEvent
from fde_api.jobs.reconcile import RECOVERABLE_JOB_TYPES
from fde_api.translator import jobs as translator_jobs
from fde_api.translator.jobs import (
    RETRY_BACKOFF_SECONDS,
    TRANSLATOR_RETRY_LIMIT,
    fail_translation_on_worker_loss,
    handle_translator_translate,
)
from fde_api.translator.models import TranslatorTranslation

PAYLOAD = {
    "industry": "装备制造",
    "scale": "200 人 / 年产值 3 亿",
    "region": "苏州",
    "interview_mode": "onsite",
    "customer_vision": "仓库出入库必须过系统留痕；管理层看不到实时良率；明年要过客户审计。",
    "phase_objective": "本期先打通仓储数据采集。",
}


def _headers(user: User, settings) -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_access_token(user, settings)}"}


def _persist_user(db_session, role: str = "project_lead") -> User:
    user = _user(f"translator.{role}", role)
    db_session.add(user)
    db_session.commit()
    return user


class _FakeDeepSeek:
    """complete_json 按脚本逐步返回（沿 guidance 假客户端模式）。"""

    def __init__(self, steps: list):
        self.steps = list(steps)
        self.calls: list[dict] = []

    def complete_json(self, *, messages, request_id, max_tokens=8192, on_event=None, **_):
        self.calls.append({"request_id": request_id, "messages": messages})
        step = self.steps.pop(0) if self.steps else None
        if callable(step):
            return step(messages)
        if isinstance(step, Exception):
            raise step
        return step


def _valid_contract_payload() -> dict:
    problem = {
        "text": "仓库出入库缺少系统留痕",
        "classification": "customer_stated",
        "source_refs": ["translator:vision"],
        "confirmed": False,
        "severity": "high",
        "module": "wms",
    }
    open_item = {
        "text": "验收基线未给出",
        "classification": "open_question",
        "source_refs": [],
        "confirmed": False,
    }
    return {
        "customer_vision": "仓储全过程留痕，管理可见",
        "current_phase_objective": "打通仓储数据采集",
        "executive_summary": "先采集后分析。",
        "evidence": {"translator:vision": "诉求原话第一句"},
        "key_business_problems": [problem],
        **{field: [dict(open_item)] for field in LIST_FIELDS if field != "key_business_problems"},
    }


def _job_for(db_session, translation_id: str) -> BackgroundJob:
    """直建任务行驱动 handler（outbox→BackgroundJob 物化由 dispatcher 自测承载）。"""
    job = BackgroundJob(job_type="translator.translate", target_id=translation_id)
    db_session.add(job)
    db_session.commit()
    return job


def _create(client, user, settings, payload=None):
    return client.post(
        "/api/v1/translator/translations",
        json=payload or PAYLOAD,
        headers=_headers(user, settings),
    )


def test_translator_requires_auth(client, d4_settings) -> None:
    body = client.post("/api/v1/translator/translations", json=PAYLOAD)
    assert body.status_code == 401


@pytest.mark.parametrize("payload", [
    {**PAYLOAD, "customer_vision": "   "},
    {**PAYLOAD, "interview_mode": "phone"},
    {key: value for key, value in PAYLOAD.items() if key != "phase_objective"},
])
def test_create_validates_payload(client, d4_settings, db_session, payload) -> None:
    user = _persist_user(db_session)
    body = _create(client, user, d4_settings, payload)
    assert body.status_code == 400, body.json
    assert body.json["error"]["code"] == "invalid_request"


def test_create_enqueues_outbox_event(db_session, d4_client, d4_settings) -> None:
    user = _persist_user(db_session)
    body = _create(d4_client, user, d4_settings)
    assert body.status_code == 201, body.json
    data = body.json["data"]
    assert data["status"] == "pending"
    assert data["result"] is None
    event = db_session.query(OutboxEvent).filter(OutboxEvent.aggregate_id == data["id"]).one()
    assert event.topic == "translator.translate"


def test_job_success_persists_draft_with_contract(db_session, d4_app, d4_client, d4_settings) -> None:
    user = _persist_user(db_session)
    data = _create(d4_client, user, d4_settings).json["data"]
    fake = _FakeDeepSeek([_valid_contract_payload()])
    d4_app.extensions["fde_api_translator_ai"] = fake
    job = _job_for(db_session, data["id"])
    with d4_app.app_context():
        handle_translator_translate(job)
    row = db_session.get(TranslatorTranslation, data["id"])
    assert row.status == "ready"
    assert row.ai_model == d4_settings.kimi_translator_model == "kimi-k3"
    assert row.ai_generated_at is not None
    result = row.result_json
    assert result["customer_vision"]
    problems = result["key_business_problems"]
    assert problems[0]["severity"] == "high" and problems[0]["module"] == "wms"
    # 红线：AI 只出草稿——全部条目 confirmed=False
    for field in LIST_FIELDS:
        for item in result[field]:
            assert item["confirmed"] is False
    # 消息构造：原文三段 + 画像拼装
    sent = fake.calls[0]["messages"]
    assert "translator:vision" in sent[1]["content"]
    assert "行业=装备制造" in sent[1]["content"]


def test_contract_violation_retries_once_then_fails(db_session, d4_app, d4_client, d4_settings, monkeypatch) -> None:
    slept: list[float] = []
    monkeypatch.setattr(translator_jobs.time, "sleep", lambda seconds: slept.append(seconds))
    user = _persist_user(db_session)
    data = _create(d4_client, user, d4_settings).json["data"]
    bad = _valid_contract_payload()
    del bad["customer_vision"]  # 顶层字段缺失 → invalid_guidance
    fake = _FakeDeepSeek([bad, dict(bad)])
    d4_app.extensions["fde_api_translator_ai"] = fake
    job = _job_for(db_session, data["id"])
    with d4_app.app_context():
        handle_translator_translate(job)
    row = db_session.get(TranslatorTranslation, data["id"])
    assert row.status == "failed"
    assert row.failure_code == "ai_output_invalid"
    assert "已自动重试" in row.failure_message
    assert len(fake.calls) == TRANSLATOR_RETRY_LIMIT + 1
    assert slept == []  # 契约违反不退避（概率性问题立即重试）


def test_transient_error_backs_off_and_fails_classified(db_session, d4_app, d4_client, d4_settings, monkeypatch) -> None:
    slept: list[float] = []
    monkeypatch.setattr(translator_jobs.time, "sleep", lambda seconds: slept.append(seconds))
    user = _persist_user(db_session)
    data = _create(d4_client, user, d4_settings).json["data"]
    error = DeepSeekError("ai_rate_limited", "AI 请求过于频繁，请稍后重试。", retryable=True)
    fake = _FakeDeepSeek([error, error])
    d4_app.extensions["fde_api_translator_ai"] = fake
    job = _job_for(db_session, data["id"])
    with d4_app.app_context():
        handle_translator_translate(job)
    row = db_session.get(TranslatorTranslation, data["id"])
    assert row.status == "failed"
    assert row.failure_code == "ai_rate_limited"
    assert slept == [RETRY_BACKOFF_SECONDS]


def test_non_retryable_fails_without_retry(db_session, d4_app, d4_client, d4_settings) -> None:
    user = _persist_user(db_session)
    data = _create(d4_client, user, d4_settings).json["data"]
    error = DeepSeekError("ai_service_not_configured", "AI 服务未配置，请联系系统运维员。", retryable=False)
    fake = _FakeDeepSeek([error])
    d4_app.extensions["fde_api_translator_ai"] = fake
    job = _job_for(db_session, data["id"])
    with d4_app.app_context():
        handle_translator_translate(job)
    row = db_session.get(TranslatorTranslation, data["id"])
    assert row.status == "failed"
    assert row.failure_code == "ai_service_not_configured"
    assert "已自动重试" not in row.failure_message  # 配置类失败重试无意义
    assert len(fake.calls) == 1


def test_kimi_slot_unconfigured_fails_classified(db_session, d4_app, d4_client, d4_settings) -> None:
    """goal-d13 拍板：翻译管道走 kimi 槽位——key 未配置时走真实客户端构造路径，
    请求发出前即分类失败（ai_service_not_configured），绝不裸 500 或卡 running。"""
    user = _persist_user(db_session)
    data = _create(d4_client, user, d4_settings).json["data"]
    job = _job_for(db_session, data["id"])  # 不注入假客户端：走 _client 真实构造
    with d4_app.app_context():
        handle_translator_translate(job)
    row = db_session.get(TranslatorTranslation, data["id"])
    assert row.status == "failed"
    assert row.failure_code == "ai_service_not_configured"
    assert row.ai_model == ""  # ai_model 只在 ready 分支落账，失败不虚标模型


def test_replay_skips_terminal_rows(db_session, d4_app, d4_client, d4_settings) -> None:
    user = _persist_user(db_session)
    data = _create(d4_client, user, d4_settings).json["data"]
    fake = _FakeDeepSeek([_valid_contract_payload()])
    d4_app.extensions["fde_api_translator_ai"] = fake
    job = _job_for(db_session, data["id"])
    with d4_app.app_context():
        handle_translator_translate(job)
        handle_translator_translate(job)  # 重复投递：终态幂等跳过
    assert len(fake.calls) == 1
    row = db_session.get(TranslatorTranslation, data["id"])
    assert row.status == "ready"


def test_worker_loss_pushes_terminal(db_session, d4_app) -> None:
    user = _persist_user(db_session)
    row = TranslatorTranslation(
        created_by_user_id=user.id, profile_json={"industry": "x"},
        customer_vision="诉求", phase_objective="目标", status="running",
    )
    db_session.add(row)
    db_session.commit()
    job = BackgroundJob(job_type="translator.translate", target_id=row.id)
    db_session.add(job)
    db_session.commit()
    with d4_app.app_context():
        fail_translation_on_worker_loss(db_session, job)
    db_session.commit()  # 失败钩子在 reconcile 事务内由调用方提交
    db_session.refresh(row)
    assert row.status == "failed"
    assert row.failure_code == "translation_worker_lost"


def test_translation_scoped_to_creator(db_session, d4_client, d4_settings) -> None:
    owner = _persist_user(db_session, "fde_engineer")
    other = _persist_user(db_session, "fde_engineer")
    admin = _persist_user(db_session, "admin")
    data = _create(d4_client, owner, d4_settings).json["data"]
    listed = d4_client.get(
        "/api/v1/translator/translations", headers=_headers(owner, d4_settings)
    ).json["data"]["items"]
    assert [item["id"] for item in listed] == [data["id"]]
    empty = d4_client.get(
        "/api/v1/translator/translations", headers=_headers(other, d4_settings)
    ).json["data"]["items"]
    assert empty == []
    assert d4_client.get(
        f"/api/v1/translator/translations/{data['id']}", headers=_headers(other, d4_settings)
    ).status_code == 404
    assert d4_client.get(
        f"/api/v1/translator/translations/{data['id']}", headers=_headers(admin, d4_settings)
    ).status_code == 200


def test_recoverable_job_types_pins_translator() -> None:
    """语义钉子：worker 死亡后 translator.translate 可对账重投（终态幂等）。"""
    assert "translator.translate" in RECOVERABLE_JOB_TYPES
