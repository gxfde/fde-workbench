"""E7 AI 调用审计与月度 token 预算回归钉。

- 每次供应商调用落一条 ai_call_audits（模型/耗时/token/结果状态），
  记录里没有任何密钥或消息内容
- 预算超限：明确报错且不发起供应商请求（同时落 budget_blocked 审计）
- 默认配置（预算 0）不限额，不锁死现有用户
"""
from decimal import Decimal
from unittest.mock import Mock

import pytest

from fde_api.ai.deepseek import DeepSeekClient, DeepSeekError
from fde_api.config import Settings
from fde_api.workbench.models import AICallAudit
from sqlalchemy import select
from conftest import INITIAL_PASSWORD


class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self.headers = {}
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, script):
        self._script = list(script)
        self.calls = 0

    def post(self, url, **kwargs):
        self.calls += 1
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _payload(content="{}"):
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
    }


def _make_user(db_session, name="audit.user"):
    from fde_api.auth.models import User
    from fde_api.auth.passwords import hash_password

    user = User(
        username=name,
        display_name=name,
        role="admin",
        password_hash=hash_password(INITIAL_PASSWORD),
        must_change_password=False,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return user


def test_successful_call_writes_audit_with_metadata_not_content(db_session, app):
    user = _make_user(db_session, "audit.success")
    session = _FakeSession([_FakeResponse(200, _payload())])
    ai_client = DeepSeekClient(
        base_url="https://ai.example.com/v1",
        api_key="sk-secret-value",
        model="primary-model",
        timeout_seconds=5,
        session=session,
        sleep=lambda _s: None,
    )
    with app.app_context():
        from flask import g

        g.current_user = user
        result = ai_client.complete_json(
            messages=[{"role": "user", "content": "机密上下文内容"}],
            request_id="audit-1",
            purpose="test",
        )
        assert result == {}
        db_session.commit()

        audit = db_session.scalar(
            select(AICallAudit).where(AICallAudit.request_id == "audit-1")
        )
        assert audit is not None
        assert audit.status == "succeeded"
        assert audit.model == "primary-model"
        assert audit.used_fallback is False
        assert audit.input_tokens == 100
        assert audit.output_tokens == 50
        assert audit.duration_ms >= 0
        assert audit.actor_user_id == user.id
        # 防泄漏断言覆盖全部字符串列：purpose/status 也在审计表里，实现若把
        # 消息上下文误写进任一字段都要被抓到（评审会跟进清单 P3-8）。
        blob = (
            f"{audit.request_id}{audit.purpose or ''}{audit.model}"
            f"{audit.status}{audit.error_code or ''}"
        )
        assert "sk-secret-value" not in blob
        assert "机密上下文内容" not in blob
        assert audit.purpose == "test"


def test_budget_exceeded_blocks_call_without_provider_request(db_session, app, monkeypatch):
    user = _make_user(db_session, "audit.budget")
    session = _FakeSession([_FakeResponse(200, _payload())])
    # app.config["SETTINGS"] 与 settings fixture 是同一实例，改实例字段即可
    monkeypatch.setattr(app.config["SETTINGS"], "ai_monthly_token_budget", 150)
    ai_client = DeepSeekClient(
        base_url="https://ai.example.com/v1",
        api_key="sk-test",
        model="primary-model",
        timeout_seconds=5,
        session=session,
        sleep=lambda _s: None,
    )
    with app.app_context():
        from flask import g

        g.current_user = user
        # 第一笔：100+50=150 token，恰好达到预算
        ai_client.complete_json(
            messages=[{"role": "user", "content": "x"}], request_id="budget-1",
            purpose="unit_test"
        )
        db_session.commit()
        assert session.calls == 1

        # 第二笔：预算已用尽 → 明确报错且不发起任何供应商请求
        with pytest.raises(DeepSeekError) as excinfo:
            ai_client.complete_json(
                messages=[{"role": "user", "content": "x"}], request_id="budget-2",
                purpose="unit_test"
            )
        assert excinfo.value.code == "ai_budget_exceeded"
        assert excinfo.value.retryable is False
        assert session.calls == 1  # 没有新的供应商请求

        blocked = db_session.scalar(
            select(AICallAudit).where(AICallAudit.request_id == "budget-2")
        )
        assert blocked is not None
        assert blocked.status == "budget_blocked"


def test_default_budget_zero_never_locks_out_users(db_session, app):
    """默认配置（预算 0 = 不限额）下连续多笔调用不受任何限制。"""
    user = _make_user(db_session, "audit.unlimited")
    session = _FakeSession(
        [_FakeResponse(200, _payload()) for _ in range(3)]
    )
    ai_client = DeepSeekClient(
        base_url="https://ai.example.com/v1",
        api_key="sk-test",
        model="primary-model",
        timeout_seconds=5,
        session=session,
        sleep=lambda _s: None,
    )
    with app.app_context():
        from flask import g

        g.current_user = user
        for index in range(3):
            ai_client.complete_json(
                messages=[{"role": "user", "content": "x"}],
                request_id=f"unlimited-{index}",
                purpose="unit_test"
            )
        db_session.commit()
        assert session.calls == 3
        audits = db_session.scalars(
            select(AICallAudit).where(
                AICallAudit.request_id.like("unlimited-%")
            )
        ).all()
        assert len(audits) == 3
        assert all(audit.status == "succeeded" for audit in audits)


def test_failed_call_writes_failed_audit(db_session, app):
    user = _make_user(db_session, "audit.failed")
    session = _FakeSession([_FakeResponse(500)])
    ai_client = DeepSeekClient(
        base_url="https://ai.example.com/v1",
        api_key="sk-test",
        model="primary-model",
        timeout_seconds=5,
        session=session,
        sleep=lambda _s: None,
    )
    with app.app_context():
        from flask import g

        g.current_user = user
        with pytest.raises(DeepSeekError):
            ai_client.complete_json(
                messages=[{"role": "user", "content": "x"}], request_id="fail-1",
                purpose="unit_test"
            )
        db_session.commit()
        audit = db_session.scalar(
            select(AICallAudit).where(AICallAudit.request_id == "fail-1")
        )
        assert audit is not None
        assert audit.status == "failed"
        assert audit.error_code == "ai_service_unavailable"
