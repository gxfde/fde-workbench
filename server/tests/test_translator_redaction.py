"""架构评估 2026-11-07 D2（P1）：翻译器 AI 入口的企业名脱敏全链钉子。

T-A2（#160/#171）三道防线原只覆盖 presurvey DOCX 腿；translator 腿（表单
自由文本 → AI → guidance 草稿）此前零脱敏——翻译草稿可携真实企业名入库
且 confirm 复核闸不聚合其事件。本文件钉住修复后的同源语义：

1. 创建面——原文不落库（种子词典命中→「客户代号」、疑似名→替换+复核事件、
   通用词零改动不进清单）；
2. fail-closed——词典机制性故障 422 阻断创建（行不落库）、凭据串 422 拒收；
3. job 兜底层——AI 输出回显企业名 → result_json 已替换 + output 阶段事件；
4. 采纳交接——translator_translation 复核事件搬到分析目标，confirm 复核闸
   自动覆盖翻译链（未 ack 409 redaction_review_required / ack 放行留痕）；
   干净草稿零闸误伤。

测试数据全合成（AGENTS 红线：真实客户资料不可作测试素材）。
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from test_agents_d4_harness import d4_app, d4_client, d4_settings  # noqa: F401  (pytest fixture)
from test_document_drafts_api import _persist_project
from test_translator_portal import PAYLOAD, _FakeDeepSeek, _valid_contract_payload

from conftest import INITIAL_PASSWORD
from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from fde_api.guidance.enterprise_dict import (
    EXTRA_DICT_ENV,
    reset_dict_cache,
)
from fde_api.guidance.models import ProjectGuidanceAnalysis, REDACTION_EVENT_TYPE
from fde_api.guidance.redaction import redaction_name_hash
from fde_api.guidance.service import GuidanceServiceError, confirm_analysis, get_analysis
from fde_api.jobs.models import BackgroundJob
from fde_api.translator.jobs import handle_translator_translate
from fde_api.translator.models import TranslatorTranslation
from fde_api.workbench.models import OperationEvent, Project


SEED_NAME = "黑名单示例控股公司"
SUSPECT_NAME = "未登记示例厂"
GENERIC_SENTENCE = "对方是一家技术公司，流程很规范。"


@pytest.fixture(autouse=True)
def _clean_dict_env(monkeypatch):
    monkeypatch.delenv(EXTRA_DICT_ENV, raising=False)
    reset_dict_cache()
    yield
    reset_dict_cache()


def _persist_user(db_session, username: str, role: str = "project_lead") -> User:
    user = User(
        username=username,
        display_name=username,
        role=role,
        password_hash=hash_password(INITIAL_PASSWORD),
        must_change_password=False,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return user


def _headers_for(user: User, settings) -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_access_token(user, settings)}"}


def _payload_with(**overrides) -> dict:
    body = dict(PAYLOAD)
    body.update(overrides)
    return body


def _create(client, user, settings, payload=None):
    return client.post(
        "/api/v1/translator/translations",
        json=payload or PAYLOAD,
        headers=_headers_for(user, settings),
    )


def _job_for(db_session, translation_id: str) -> BackgroundJob:
    job = BackgroundJob(job_type="translator.translate", target_id=translation_id)
    db_session.add(job)
    db_session.commit()
    return job


def _redaction_events(db_session, target_type: str, target_id: str) -> list[OperationEvent]:
    return list(
        db_session.query(OperationEvent)
        .filter_by(target_type=target_type, target_id=target_id, event_type=REDACTION_EVENT_TYPE)
        .all()
    )


def _world(db_session) -> tuple[User, Project]:
    owner = _persist_user(db_session, f"tr.{uuid4().hex[:6]}")
    project = _persist_project(db_session, owner, code=f"TR{uuid4().hex[:6]}")
    return owner, project


def _adopt(d4_client, d4_settings, owner: User, project, translation_id: str) -> dict:
    body = d4_client.post(
        f"/api/v1/translator/translations/{translation_id}/adopt",
        json={"project_id": project.id},
        headers=_headers_for(owner, d4_settings),
    )
    assert body.status_code == 200, body.json
    return body.json["data"]


# ---------- 创建面：原文不落库 ----------

def test_create_replaces_seed_names_before_persist(db_session, d4_client, d4_settings) -> None:
    user = _persist_user(db_session, f"tr.{uuid4().hex[:6]}")
    body = _create(d4_client, user, d4_settings, _payload_with(
        customer_vision=f"我们和{SEED_NAME}谈了三轮，他们要仓库留痕。",
    ))
    assert body.status_code == 201, body.json
    row = db_session.get(TranslatorTranslation, body.json["data"]["id"])
    # 原文不落库：替换目标=「客户代号」（翻译器无项目维度，无 enterprise_code 首段可用）
    assert SEED_NAME not in row.customer_vision
    assert "客户代号" in row.customer_vision
    events = _redaction_events(db_session, "translator_translation", row.id)
    assert len(events) == 1
    assert events[0].changes["stage"] == "input"
    # QR-133 指纹化：确证命中只存 sha256 指纹，事件账零真名。
    assert any(
        item["name_hash"] == redaction_name_hash(SEED_NAME) and item["matched_dict"]
        for item in events[0].changes["entries"]
    )
    assert SEED_NAME not in json.dumps(events[0].changes, ensure_ascii=False, default=str)


def test_create_suspect_name_replaced_and_flagged(db_session, d4_client, d4_settings) -> None:
    user = _persist_user(db_session, f"tr.{uuid4().hex[:6]}")
    body = _create(d4_client, user, d4_settings, _payload_with(
        phase_objective=f"另有{SUSPECT_NAME}参与投标，需要跟进。",
    ))
    assert body.status_code == 201, body.json
    row = db_session.get(TranslatorTranslation, body.json["data"]["id"])
    assert SUSPECT_NAME not in row.phase_objective
    assert "客户代号" in row.phase_objective
    events = _redaction_events(db_session, "translator_translation", row.id)
    entries = [item for event in events for item in event.changes["entries"]]
    # QR-133：疑似名不入条目账——只留聚合计数（零原文），替换照常落库。
    assert entries == []
    suspect_counts = [event.changes.get("suspect_count", 0) for event in events]
    assert sum(suspect_counts) >= 1
    assert SUSPECT_NAME not in json.dumps(
        [event.changes for event in events], ensure_ascii=False, default=str
    )


def test_create_generic_words_untouched(db_session, d4_client, d4_settings) -> None:
    user = _persist_user(db_session, f"tr.{uuid4().hex[:6]}")
    body = _create(d4_client, user, d4_settings, _payload_with(customer_vision=GENERIC_SENTENCE))
    assert body.status_code == 201, body.json
    row = db_session.get(TranslatorTranslation, body.json["data"]["id"])
    assert row.customer_vision == GENERIC_SENTENCE
    assert _redaction_events(db_session, "translator_translation", row.id) == []


# ---------- 创建面：fail-closed ----------

def test_create_dict_failure_blocks_with_422(db_session, d4_client, d4_settings, tmp_path, monkeypatch) -> None:
    bad = tmp_path / "bad-dict.txt"
    bad.write_text("这不是企业名\n", encoding="utf-8")
    monkeypatch.setenv(EXTRA_DICT_ENV, str(bad))
    reset_dict_cache()
    user = _persist_user(db_session, f"tr.{uuid4().hex[:6]}")
    body = _create(d4_client, user, d4_settings)
    assert body.status_code == 422, body.json
    assert body.json["error"]["code"] == "pseudonym_dict_unavailable"
    assert db_session.query(TranslatorTranslation).count() == 0


def test_create_credential_string_rejected(db_session, d4_client, d4_settings) -> None:
    user = _persist_user(db_session, f"tr.{uuid4().hex[:6]}")
    body = _create(d4_client, user, d4_settings, _payload_with(
        customer_vision="他们把密码: sk-abcdef1234567890 发在了群里。",
    ))
    assert body.status_code == 422, body.json
    assert body.json["error"]["code"] == "sensitive_credential_detected"
    assert db_session.query(TranslatorTranslation).count() == 0


# ---------- job 兜底层：AI 输出回显也被替换 ----------

def test_job_output_echo_redacted_with_output_event(db_session, d4_app, d4_client, d4_settings) -> None:
    user = _persist_user(db_session, f"tr.{uuid4().hex[:6]}")
    data = _create(d4_client, user, d4_settings).json["data"]
    leaked = _valid_contract_payload()
    leaked["executive_summary"] = f"建议先与{SEED_NAME}共建试点。"
    d4_app.extensions["fde_api_translator_ai"] = _FakeDeepSeek([leaked])
    job = _job_for(db_session, data["id"])
    with d4_app.app_context():
        handle_translator_translate(job)
    row = db_session.get(TranslatorTranslation, data["id"])
    assert row.status == "ready"
    assert SEED_NAME not in row.result_json["executive_summary"]
    output_events = [event for event in _redaction_events(db_session, "translator_translation", row.id)
                     if event.changes.get("stage") == "output"]
    assert len(output_events) == 1
    # QR-133 指纹化：确证命中只存 sha256 指纹，事件账零真名。
    assert any(
        item["name_hash"] == redaction_name_hash(SEED_NAME) and item["matched_dict"]
        for item in output_events[0].changes["entries"]
    )
    assert SEED_NAME not in json.dumps(output_events[0].changes, ensure_ascii=False, default=str)


# ---------- 采纳交接：confirm 复核闸自动覆盖翻译链 ----------

def _run_job_and_adopt(db_session, d4_app, d4_client, d4_settings, owner, project, payload=None) -> dict:
    _create(d4_client, owner, d4_settings, payload)
    translation = db_session.query(TranslatorTranslation).filter_by(
        created_by_user_id=owner.id, status="pending").one()
    d4_app.extensions["fde_api_translator_ai"] = _FakeDeepSeek([_valid_contract_payload()])
    job = _job_for(db_session, translation.id)
    with d4_app.app_context():
        handle_translator_translate(job)
    return _adopt(d4_client, d4_settings, owner, project, translation.id)


def test_adopt_carries_entries_and_confirm_gate_blocks_without_ack(db_session, d4_app, d4_client, d4_settings) -> None:
    owner, project = _world(db_session)
    adopted = _run_job_and_adopt(
        db_session, d4_app, d4_client, d4_settings, owner, project,
        _payload_with(customer_vision=f"和{SUSPECT_NAME}聊过，他们要良率看板。"),
    )
    # 采纳响应直接携带复核清单（跨阶段聚合）——QR-133 投影：疑似名=聚合计数项。
    review = adopted["redaction_review"]
    assert review, "采纳响应应携带复核清单"
    assert review == [{"suspect_count": 1}]

    analysis_id = adopted["id"]
    analysis = db_session.get(ProjectGuidanceAnalysis, analysis_id)
    # 读面同一事件源（get_analysis 派生字段）
    detail = get_analysis(actor=owner, project_id=project.id, analysis_id=analysis_id)
    assert detail["redaction_review"] == review
    # 闸：清单非空 + 未显式 ack → 409 redaction_review_required
    with pytest.raises(GuidanceServiceError) as excinfo:
        confirm_analysis(actor=owner, project_id=project.id, analysis_id=analysis_id,
                         expected_version=analysis.version)
    assert excinfo.value.code == "redaction_review_required"
    # ack 放行 + 随事件留痕
    confirmed = confirm_analysis(actor=owner, project_id=project.id, analysis_id=analysis_id,
                                 expected_version=analysis.version, redaction_reviewed=True)
    assert confirmed["status"] == "confirmed"
    assert confirmed["redaction_review"] == review
    acked = (
        db_session.query(OperationEvent)
        .filter_by(project_id=project.id, event_type="guidance_analysis_confirmed")
        .order_by(OperationEvent.occurred_at.desc(), OperationEvent.id.desc())
        .first()
    )
    assert acked is not None
    assert acked.changes["redaction_reviewed"] is True
    assert acked.changes["redaction_review_hits"] == len(review)


def test_adopt_clean_draft_confirms_without_gate(db_session, d4_app, d4_client, d4_settings) -> None:
    owner, project = _world(db_session)
    adopted = _run_job_and_adopt(db_session, d4_app, d4_client, d4_settings, owner, project)
    # 合成 payload 无企业名/疑似名：零复核条目，confirm 不被闸误伤
    assert adopted["redaction_review"] == []
    analysis = db_session.get(ProjectGuidanceAnalysis, adopted["id"])
    confirmed = confirm_analysis(actor=owner, project_id=project.id, analysis_id=adopted["id"],
                                 expected_version=analysis.version)
    assert confirmed["status"] == "confirmed"
