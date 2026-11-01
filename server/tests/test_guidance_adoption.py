"""goal-d10：翻译草稿「采纳流」（PRD §3.2 P3 收口）。

- POST /translator/translations/{id}/adopt：ready 草稿升格为项目指引新版本
  （version_number 递增，status=draft——确认仍走人工）。
- 全闸矩阵：401 / 400 / 404（非本人非 admin）/ 409（非 ready、重复采纳）。
- O-3 额度随路落：action_type='translation' 台账行（ref_id=translation_id）。
- 决议③钉子：translator 来源版本确认时不回写/不创建 ProjectPresurveySource
  （预调研源指针绝不被翻译器假源污染）。
- api_catalog：translator.adopt 收编（创作类写先例延续）。
"""
from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select

from test_agents_d4_harness import d4_app, d4_client, d4_settings  # noqa: F401  (pytest fixture)
from test_document_drafts_api import _persist_project
from test_metrics_report import _user

from conftest import INITIAL_PASSWORD
from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from fde_api.agents.models import SeatActionLedger
from fde_api.control.api_catalog import CATALOG
from fde_api.guidance.ai_schema import LIST_FIELDS
from fde_api.guidance.models import ProjectGuidanceAnalysis, ProjectPresurveySource
from fde_api.translator.models import TranslatorTranslation
from fde_api.workbench.models import OperationEvent


def _headers(user: User, settings) -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_access_token(user, settings)}"}


def _persist_user(db_session, role: str = "project_lead") -> User:
    user = _user(f"adopt.{role}", role)
    db_session.add(user)
    db_session.commit()
    return user


def _result_json() -> dict:
    return {
        "customer_vision": "仓储全过程留痕，管理可见",
        "current_phase_objective": "打通仓储数据采集",
        "executive_summary": "先采集后分析。",
        "evidence": {"translator:vision": "诉求原话第一句"},
        "key_business_problems": [
            {
                "text": "仓库出入库缺少系统留痕",
                "classification": "customer_stated",
                "source_refs": ["translator:vision"],
                "confirmed": False,
            }
        ],
        **{
            field: [
                {
                    "text": "验收基线未给出",
                    "classification": "open_question",
                    "source_refs": [],
                    "confirmed": False,
                }
            ]
            for field in LIST_FIELDS
            if field != "key_business_problems"
        },
    }


def _persist_translation(db_session, owner: User, *, status: str = "ready") -> TranslatorTranslation:
    row = TranslatorTranslation(
        created_by_user_id=owner.id,
        profile_json={"industry": "装备制造", "interview_mode": "onsite"},
        customer_vision="仓库出入库必须过系统留痕",
        phase_objective="打通仓储数据采集",
        status=status,
        ai_model="deepseek-v4-pro" if status == "ready" else "",
        result_json=_result_json() if status == "ready" else None,
    )
    db_session.add(row)
    db_session.commit()
    return row


def _adopt(client, user, settings, translation_id: str, project_id: str):
    return client.post(
        f"/api/v1/translator/translations/{translation_id}/adopt",
        json={"project_id": project_id},
        headers=_headers(user, settings),
    )


def test_adopt_requires_auth(client, d4_settings) -> None:
    body = client.post(
        f"/api/v1/translator/translations/{uuid4()}/adopt", json={"project_id": "p"}
    )
    assert body.status_code == 401


def test_adopt_validates_project_id(d4_client, d4_settings, db_session) -> None:
    user = _persist_user(db_session)
    body = d4_client.post(
        f"/api/v1/translator/translations/{uuid4()}/adopt",
        json={},
        headers=_headers(user, d4_settings),
    )
    assert body.status_code == 400
    assert body.json["error"]["code"] == "invalid_request"


def test_adopt_rejects_non_ready_draft(d4_client, d4_settings, db_session) -> None:
    leader = _persist_user(db_session)
    project = _persist_project(db_session, leader, code=f"adopt-{uuid4().hex[:6]}")
    translation = _persist_translation(db_session, leader, status="pending")
    body = _adopt(d4_client, leader, d4_settings, translation.id, project.id)
    assert body.status_code == 409
    assert body.json["error"]["code"] == "translation_not_ready"


def test_adopt_scoped_to_owner_or_admin(d4_client, d4_settings, db_session) -> None:
    owner = _persist_user(db_session)
    stranger = _persist_user(db_session)
    translation = _persist_translation(db_session, owner)
    body = _adopt(d4_client, stranger, d4_settings, translation.id, "whatever")
    assert body.status_code == 404
    assert body.json["error"]["code"] == "translation_not_found"
    # admin 可代采纳（读侧语义对齐：创建人或 admin）。
    admin = _persist_user(db_session, role="admin")
    project = _persist_project(db_session, owner, code=f"adopt-{uuid4().hex[:6]}")
    ok = _adopt(d4_client, admin, d4_settings, translation.id, project.id)
    assert ok.status_code == 200, ok.json
    assert ok.json["data"]["source_kind"] == "translator_draft"


def test_adopt_rejects_project_without_access(d4_client, d4_settings, db_session) -> None:
    owner = _persist_user(db_session)
    leader = _persist_user(db_session)
    translation = _persist_translation(db_session, owner)
    # owner 是草稿创建人（翻译记录闸过），但不是项目成员 → 项目闸 404。
    project = _persist_project(db_session, leader, code=f"adopt-{uuid4().hex[:6]}")
    body = _adopt(d4_client, owner, d4_settings, translation.id, project.id)
    assert body.status_code == 404
    assert body.json["error"]["code"] == "project_not_found"


def test_adopt_creates_guidance_version_and_ledger_row(
    d4_client, d4_settings, db_session
) -> None:
    owner = _persist_user(db_session)
    # owner 自建项目（can_manage）+ 自提草稿：最常见的自采纳路径。
    project = _persist_project(db_session, owner, code=f"adopt-{uuid4().hex[:6]}")
    translation = _persist_translation(db_session, owner)

    body = _adopt(d4_client, owner, d4_settings, translation.id, project.id)
    assert body.status_code == 200, body.json
    data = body.json["data"]
    # 内容逐字段 = 原草稿（决议①：升格不是重建）
    assert data["customer_vision"] == "仓储全过程留痕，管理可见"
    assert data["current_phase_objective"] == "打通仓储数据采集"
    assert data["executive_summary"] == "先采集后分析。"
    assert data["evidence"] == {"translator:vision": "诉求原话第一句"}
    assert data["key_business_problems"][0]["text"] == "仓库出入库缺少系统留痕"
    assert data["key_business_problems"][0]["confirmed"] is False
    # 来源标记与待确认态
    assert data["source_kind"] == "translator_draft"
    assert data["translation_id"] == translation.id
    assert data["source_filename"] == f"translator:{translation.id}"
    assert data["source_file_id"] is None
    assert data["source_file_version_id"] is None
    assert data["status"] == "draft"
    assert data["analysis_state"] == "ready"
    assert data["version_number"] == 1
    assert data["source_is_stale"] is False
    assert data["ai_model"] == "deepseek-v4-pro"

    row = db_session.get(ProjectGuidanceAnalysis, data["id"])
    assert row is not None and row.project_id == project.id

    ledger = db_session.scalar(
        select(SeatActionLedger).where(
            SeatActionLedger.action_type == "translation",
            SeatActionLedger.ref_id == translation.id,
        )
    )
    assert ledger is not None
    assert ledger.project_id == project.id
    # seat 归集键 = 采纳发起人（决议②）
    assert ledger.user_id == owner.id
    assert ledger.units == 1
    assert ledger.over_quota is False

    event = db_session.scalar(
        select(OperationEvent).where(
            OperationEvent.event_type == "translator_draft_adopted",
            OperationEvent.project_id == project.id,
        )
    )
    assert event is not None
    assert event.changes["translation_id"] == translation.id
    assert event.changes["analysis_id"] == data["id"]


def test_adopt_duplicate_in_same_project_and_multi_project(
    d4_client, d4_settings, db_session
) -> None:
    owner = _persist_user(db_session)
    project_a = _persist_project(db_session, owner, code=f"adopt-a-{uuid4().hex[:6]}")
    project_b = _persist_project(db_session, owner, code=f"adopt-b-{uuid4().hex[:6]}")
    translation = _persist_translation(db_session, owner)

    assert _adopt(d4_client, owner, d4_settings, translation.id, project_a.id).status_code == 200
    duplicate = _adopt(d4_client, owner, d4_settings, translation.id, project_a.id)
    assert duplicate.status_code == 409
    assert duplicate.json["error"]["code"] == "already_adopted"
    # 个人席位资产可采纳到多个项目（决议①）；版本号按项目独立递增。
    second = _adopt(d4_client, owner, d4_settings, translation.id, project_b.id)
    assert second.status_code == 200
    assert second.json["data"]["version_number"] == 1
    assert second.json["data"]["project_id"] == project_b.id


def test_confirm_translator_source_keeps_presurvey_source(
    d4_client, d4_settings, db_session
) -> None:
    """决议③钉子：translator 来源确认时预调研源指针不被回写也不被凭空创建。"""
    owner = _persist_user(db_session)
    project = _persist_project(db_session, owner, code=f"adopt-{uuid4().hex[:6]}")
    translation = _persist_translation(db_session, owner)
    data = _adopt(d4_client, owner, d4_settings, translation.id, project.id).json["data"]

    body = d4_client.post(
        f"/api/v1/projects/{project.id}/guidance-analyses/{data['id']}/confirm",
        json={"version": data["version"]},
        headers=_headers(owner, d4_settings),
    )
    assert body.status_code == 200, body.json
    confirmed = body.json["data"]
    assert confirmed["status"] == "confirmed"
    assert confirmed["reviewed_by_user_id"] == owner.id
    # 钉子：ProjectPresurveySource 行未被创建（旧行为会拿空 source_file_id
    # 击穿 NOT NULL 或写入翻译器假源）。
    assert (
        db_session.get(ProjectPresurveySource, project.id) is None
    )
    event = db_session.scalar(
        select(OperationEvent).where(
            OperationEvent.event_type == "guidance_analysis_confirmed",
            OperationEvent.project_id == project.id,
        )
    )
    assert event is not None
    assert event.changes["source_kind"] == "translator_draft"


def test_translator_adopt_in_catalog() -> None:
    """创作类写收编先例延续（d9 translator.translate 先例）；确认动作仍人工。"""
    assert "translator.adopt" in CATALOG
    entry = CATALOG["translator.adopt"]
    assert entry["method"] == "POST"
    assert entry["write"] is True
    assert entry["path"] == "/api/v1/translator/translations/{translation_id}/adopt"
