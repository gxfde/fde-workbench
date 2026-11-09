"""N2 仪表化轮的归因契约（AI 原生化差距台账 G-09 / G-16 / G-08）。

三组契约：

- **G-09 提示词归因**：审计行必须带「指令源指纹 + 版本标签」；指纹＝模板
  身份（同模板不同输入同指纹），正文绝不落库。
- **G-16 归因闭合**：``purpose`` 在入口**必填**（Python 机械强制）、在 DB 层
  **NOT NULL**；调用点静态钉防新增漏传；漏传时落 ``unattributed`` 而非丢账。
- **G-08 人工接受信号有消费面**：``reviewed`` 不再只写不读——chat 助手把
  「人工已接受的产物」读进上下文（仅元数据与指纹指针）。

这些用例不联网：模型调用全部 mock。
"""
from __future__ import annotations

import ast
import json
from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from fde_api.ai.auditing import (
    UNATTRIBUTED_PURPOSE,
    compute_prompt_fingerprint,
    record_audit,
)
from fde_api.auth.models import User
from fde_api.control import chat
from fde_api.control.ai_server_client import execute_ai_prompt
from fde_api.control.chat import AIChatTurn, AIConversation, create_turn, execute_chat_turn
from fde_api.workbench.models import AICallAudit, Project

SERVER_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = SERVER_ROOT / "src" / "fde_api"


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


def ok_payload(text="已直连回答。"):
    return {
        "choices": [{"message": {"content": text}}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
    }


def provider_model():
    return {
        "id": "pref-1",
        "provider": "openai-compatible",
        "base_url": "https://api.minimaxi.com/v1",
        "model": "MiniMax-M3.1-Flash",
        "api_key": "sk-cp-test",
        "supports_tools": True,
    }


@pytest.fixture
def ai_user(db_session):
    user = User(
        username=f"attribution-{uuid4().hex}",
        display_name="归因测试",
        password_hash="unused",
        role="admin",
        is_active=True,
        must_change_password=False,
    )
    db_session.add(user)
    db_session.commit()
    return user


def _disable_dsh(app):
    from fde_api.control.dsh_runtime import dsh_runtime

    with app.app_context():
        dsh_runtime.current.primary.enabled = False


# --- G-09：指纹语义 -------------------------------------------------------


def test_fingerprint_identifies_template_not_input():
    """同模板不同输入 ⇒ 同指纹；不同模板 ⇒ 不同指纹；无源 ⇒ None。"""
    template = "你是访谈事实抽取器，只输出 JSON。"
    first = compute_prompt_fingerprint(system_prompt=template, prompt="纪要 A")
    second = compute_prompt_fingerprint(system_prompt=template, prompt="纪要 B")
    other = compute_prompt_fingerprint(system_prompt="你是另一个助手。", prompt="纪要 A")
    assert first == second
    assert first != other
    assert len(first or "") == 64
    assert compute_prompt_fingerprint() is None


def test_fingerprint_prefers_system_message_in_messages():
    """直连腿的 messages 形态：取 system 角色内容作模板身份。"""
    fingerprint = compute_prompt_fingerprint(
        messages=[
            {"role": "system", "content": "你是机会识别助手。"},
            {"role": "user", "content": "客户资料"},
        ]
    )
    assert fingerprint == compute_prompt_fingerprint(system_prompt="你是机会识别助手。")
    assert fingerprint != compute_prompt_fingerprint(
        messages=[{"role": "user", "content": "客户资料"}]
    )


def test_audit_row_records_prompt_fingerprint_and_version(app, db_session, ai_user, monkeypatch):
    """新调用落审计行：purpose / 指纹 / 版本三样齐全。"""
    monkeypatch.setattr(
        "fde_api.control.ai_server_client.requests.Session",
        lambda: FakeSession(FakeResponse(200, ok_payload())),
    )
    _disable_dsh(app)
    with app.app_context():
        execute_ai_prompt(
            user_id=ai_user.id,
            prompt="纪要正文",
            system_prompt="你是访谈事实抽取器。",
            model_override=provider_model(),
            purpose="discovery_extract",
            prompt_version="discovery-prompt-v1",
        )
    row = db_session.scalars(
        select(AICallAudit).where(AICallAudit.actor_user_id == ai_user.id)
    ).one()
    assert row.purpose == "discovery_extract"
    assert row.prompt_version == "discovery-prompt-v1"
    assert row.prompt_fingerprint == compute_prompt_fingerprint(
        system_prompt="你是访谈事实抽取器。"
    )
    assert "纪要正文" not in (row.prompt_fingerprint or "")


# --- G-16：purpose 强制 ---------------------------------------------------


def test_purpose_is_required_at_entry_point():
    """入口漏传 purpose ⇒ TypeError（Python 机械强制，不靠自觉）。"""
    with pytest.raises(TypeError):
        execute_ai_prompt(user_id="u", prompt="p")  # type: ignore[call-arg]


def test_database_rejects_empty_purpose(app, db_session, ai_user):
    """DB 层 CHECK 拒绝空 purpose（归因账本不允许匿名调用方）。"""
    with pytest.raises(DBAPIError):
        db_session.execute(
            text(
                "INSERT INTO ai_call_audits "
                "(id, request_id, actor_user_id, purpose, model, used_fallback, "
                "duration_ms, status, created_at, updated_at) "
                "VALUES (:id, 'req-empty', :actor, '', 'm', false, 0, 'succeeded', now(), now())"
            ),
            {"id": uuid4().hex, "actor": ai_user.id},
        )
        db_session.commit()


def test_missing_purpose_falls_back_to_visible_marker(app, db_session, ai_user):
    """漏传时落 'unattributed'（可见的异常），而不是丢账或写 NULL。"""
    with app.app_context():
        record_audit(
            request_id="req-unattributed",
            actor_id=ai_user.id,
            purpose="",
            model="m",
            used_fallback=False,
            duration_ms=1,
            input_tokens=1,
            output_tokens=1,
            status="succeeded",
            error_code=None,
        )
    row = db_session.scalars(
        select(AICallAudit).where(AICallAudit.request_id == "req-unattributed")
    ).one()
    assert row.purpose == UNATTRIBUTED_PURPOSE


def test_every_ai_entry_call_declares_purpose():
    """静态钉：所有 AI 入口调用点都必须显式传 purpose（防新增漏传）。"""
    targets = {"execute_ai_prompt", "complete_json"}
    offenders: list[str] = []
    for path in SRC_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name not in targets:
                continue
            for keyword in node.keywords:
                if keyword.arg == "purpose":
                    value = keyword.value
                    if isinstance(value, ast.Constant) and isinstance(value.value, str) and value.value:
                        break
                    if isinstance(value, ast.Name):
                        break
                    offenders.append(f"{path.relative_to(SRC_ROOT)}:{node.lineno} purpose 非字面量")
                    break
            else:
                offenders.append(f"{path.relative_to(SRC_ROOT)}:{node.lineno} {name} 漏传 purpose")
    assert offenders == []


# --- G-08：人工接受信号消费面 ---------------------------------------------


def test_build_review_signals_aggregates_accepted_only():
    from fde_api.agents.review_signals import build_review_signals

    signals = build_review_signals(
        [
            {"kind": "doc", "reviewed": True, "reviewed_at": "2026-11-09T01:00:00Z"},
            {"kind": "doc", "reviewed": True, "reviewed_at": "2026-11-09T02:00:00Z"},
            {"kind": "code", "reviewed": True, "reviewed_at": "2026-11-09T03:00:00Z"},
            {"kind": "doc", "reviewed": False, "reviewed_at": None},
        ]
    )
    assert [item["kind"] for item in signals] == ["doc", "code"]
    assert signals[0]["accepted_count"] == 2


def _seed_accepted_artifact(db_session, project_id, user_id, *, reviewed: bool):
    from fde_api.agents.models import AgentArtifact, AgentRegistry, AgentRun

    registry = AgentRegistry(
        id=uuid4().hex,
        kind="zcode",
        name=f"信号测试智能体-{uuid4().hex[:6]}",
        enabled=True,
        capability_tier="agent.module.solution",
        sandbox_profile="default",
        allowed_tools=["read_file"],
        max_cost_units=0,
        max_duration_ms=0,
    )
    db_session.add(registry)
    db_session.flush()
    run = AgentRun(
        id=uuid4().hex,
        project_id=project_id,
        agent_id=registry.id,
        initiated_by_user_id=user_id,
        capability_used="agent.module.solution",
        status="completed",
        context_ref="{}",
        token_cost=0,
        duration_ms=1,
        exit_code=0,
        degraded=False,
        fallback_level=None,
        idempotency_key=f"ut-{uuid4().hex}",
        cost_owner_type="project",
        cost_owner_id=project_id,
    )
    db_session.add(run)
    db_session.flush()
    artifact = AgentArtifact(
        id=uuid4().hex,
        run_id=run.id,
        kind="doc",
        storage_ref="host:whatever",
        sha256="abcdef0123456789" + "0" * 48,
        reviewed=reviewed,
    )
    db_session.add(artifact)
    db_session.commit()
    return artifact


def test_chat_consumes_accepted_artifact_signal(app, db_session, monkeypatch):
    """人工接受信号进入 chat 的 user 角色上下文（G-08 消费点）。"""
    user = User(
        username=f"chat-signal-{uuid4().hex}",
        display_name="信号测试",
        password_hash="unused",
        role="admin",
        is_active=True,
        must_change_password=False,
    )
    db_session.add(user)
    project = Project(
        id=uuid4().hex,
        project_code=f"FDE-SIG-{uuid4().hex[:6]}",
        name="信号项目",
        enterprise_code=f"AI·signal·{uuid4().hex[:6]}",
        planned_start_date=date(2026, 11, 9),
        leader_user_id=user.id,
        status="active",
        template_snapshot={},
    )
    db_session.add(project)
    db_session.commit()
    _seed_accepted_artifact(db_session, project.id, user.id, reviewed=True)

    captured: dict[str, str] = {}

    def fake_execute(**kwargs):
        captured.update(kwargs)
        return {"text": "好的", "model": {}, "provider_usage": {}}

    monkeypatch.setattr(chat, "execute_ai_prompt", fake_execute)
    with app.app_context():
        turn = create_turn(user=user, payload={"message": "这个项目产出过什么？", "project_id": project.id,
                          "message_id": str(uuid4())})
        execute_chat_turn(turn["id"])
    prompt = captured.get("prompt", "")
    assert "已被人工接受" in prompt
    assert "abcdef012345" in prompt  # sha256 指针（前 12 位）
    assert "doc×1" in prompt


def test_chat_omits_signal_when_artifact_not_accepted(app, db_session, monkeypatch):
    """未接受（撤回）的产物不进上下文——撤回即撤销认可。"""
    user = User(
        username=f"chat-nosignal-{uuid4().hex}",
        display_name="无信号测试",
        password_hash="unused",
        role="admin",
        is_active=True,
        must_change_password=False,
    )
    db_session.add(user)
    project = Project(
        id=uuid4().hex,
        project_code=f"FDE-NOSIG-{uuid4().hex[:6]}",
        name="无信号项目",
        enterprise_code=f"AI·nosignal·{uuid4().hex[:6]}",
        planned_start_date=date(2026, 11, 9),
        leader_user_id=user.id,
        status="active",
        template_snapshot={},
    )
    db_session.add(project)
    db_session.commit()
    _seed_accepted_artifact(db_session, project.id, user.id, reviewed=False)

    captured: dict[str, str] = {}

    def fake_execute(**kwargs):
        captured.update(kwargs)
        return {"text": "好的", "model": {}, "provider_usage": {}}

    monkeypatch.setattr(chat, "execute_ai_prompt", fake_execute)
    with app.app_context():
        turn = create_turn(user=user, payload={"message": "这个项目产出过什么？", "project_id": project.id,
                          "message_id": str(uuid4())})
        execute_chat_turn(turn["id"])
    assert "已被人工接受" not in captured.get("prompt", "")
