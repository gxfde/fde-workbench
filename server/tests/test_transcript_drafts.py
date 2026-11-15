"""T-A9：转写草稿区 + 访谈纪要正式库（goal-tb tb1）。

验收面（backlog 登记原文）：
- 草稿与正式库物理隔离（两表 + 独立文件根 + 零外键引用）；
- 无客户确认的转写文本**无法**进入正式库（晋升三要素缺一即 422）；
- 清理作业按 T+7 生效（到期墓碑化：正文/指纹/复核条目抹除 + 文件根清空）；
- 转写文本过 T-A2 代号化管线（不因「草稿」豁免；词典不可用 fail-closed）。
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from test_agents_d4_harness import (
    ApiClient,
    api_client,
    issue_access_token,
    make_user,
)
from test_agents_d4_harness import d4_app, d4_client, d4_settings  # noqa: F401  (pytest fixture)
from test_document_drafts_api import _persist_project

from fde_api.guidance import enterprise_dict
from fde_api.transcripts.models import InterviewMinutes, TranscriptDraft
from fde_api.transcripts.service import purge_expired_drafts
from fde_api.workbench.models import OperationEvent, ProjectMember

_DICT_NAME = "合成测试集团"  # seeds/enterprise-names.txt 合成条目（零真实资料）


def _confirmed_at() -> str:
    """客户确认时间戳：两小时前（绝对时戳在本地时区下午跑会落入未来被拒）。"""
    return (datetime.now(UTC) - timedelta(hours=2)).isoformat()


def _member_client(db_session, d4_client, d4_settings, project, role: str = "fde_engineer") -> tuple[ApiClient, object]:
    """入项目的普通成员＋其已认证客户端（草稿写入/读取=成员级，T-A3 校准同构）。"""
    user = make_user(db_session, role)
    db_session.add(ProjectMember(project_id=project.id, user_id=user.id, role="member"))
    db_session.commit()
    return ApiClient(d4_client, user, {"Authorization": f"Bearer {issue_access_token(user, d4_settings)}"}), user


def _new_project(db_session, leader_user, tag: str):
    """enterprise_code 全局唯一（uq_projects_enterprise_code）——码唯一、别名前缀稳定。"""
    return _persist_project(db_session, leader_user, code=f"{tag}{uuid4().hex[:4]}·制造业·苏州")


def _create_draft(client: ApiClient, project, *, content: str | None = None, **overrides) -> dict:
    body = {
        "project_id": project.id,
        "title": "初诊访谈录音转写",
        "content": content or f"与{_DICT_NAME}的访谈记录，聊了生产排程的痛点。",
        "source_kind": "asr",
        "engine": "faster-whisper:base",
    }
    body.update(overrides)
    response = client.post("/api/v1/transcript-drafts", json=body)
    assert response.status_code == 201, response.get_json()
    return response.get_json()["data"]


def test_draft_create_redacts_via_t2_pipeline(db_session, d4_client, d4_settings) -> None:
    """T-A2 代号化不豁免：词典命中名替换为代号、复核条目回显、文件根落盘带指纹。"""
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _new_project(db_session, leader.user, "客户A")
    member, _user = _member_client(db_session, d4_client, d4_settings, project)

    data = _create_draft(
        member,
        project,
        content=f"今天和{_DICT_NAME}开了初诊会，对方痛点是排程靠Excel。",
    )
    assert _DICT_NAME not in data["content"], "词典命中名必须已替换（放行=不留库）"
    assert "文档企业" in data["content"], "替换目标=enterprise_code 首段代号"
    entries = data["redaction_entries"]
    # 盲审追批零真名换代：读面经词典反解（name=词目原文，仅显示不落库）；
    # 行内账只存指纹（＋疑似哨兵）。
    from fde_api.guidance.redaction import redaction_name_hash as _rnh

    assert entries and any(
        entry.get("name") == _DICT_NAME and entry.get("name_hash") == _rnh(_DICT_NAME)
        for entry in entries
    )
    from fde_api.transcripts.models import TranscriptDraft as _TD

    draft_row_raw = db_session.get(_TD, data["id"])
    assert all(
        not item.get("name") for item in (draft_row_raw.redaction_entries or [])
    ), "行内复核账零真名"
    # T+7：expires_at ≈ created_at + 保留天数
    expires = datetime.fromisoformat(data["expires_at"])
    created = datetime.fromisoformat(data["created_at"])
    assert timedelta(days=6) < expires - created <= timedelta(days=7, minutes=1)
    # 独立文件根：正文落盘且 sha256 与行一致
    # M4 批次 D：新写入落主体段（org/{org_id}/…；与产品 _draft_dir 同源解析）
    from fde_api.transcripts.models import TranscriptDraft
    from fde_api.transcripts.service import _draft_dir
    draft_row = db_session.get(TranscriptDraft, data["id"])
    root = _draft_dir(db_session, draft_row, settings=d4_settings)
    assert (root / "transcript.txt").read_text(encoding="utf-8") == data["content"]
    # 事件留痕：命中数在 changes 里，正文永不进事件
    event = db_session.query(OperationEvent).filter_by(event_type="transcript_draft_created").one()
    assert event.changes["draft_id"] == data["id"]
    assert event.changes["redaction_hits"] == len(entries)
    assert _DICT_NAME not in str(event.changes)


def test_draft_asr_requires_engine_and_manual_rejects_it(db_session, d4_client, d4_settings) -> None:
    """engine 标注与来源一一对应（CHECK 的服务面前置）。"""
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _new_project(db_session, leader.user, "客户A")
    member, _user = _member_client(db_session, d4_client, d4_settings, project)

    missing_engine = member.post(
        "/api/v1/transcript-drafts",
        json={"project_id": project.id, "content": "缺引擎标注的转写", "source_kind": "asr"},
    )
    assert missing_engine.status_code == 422
    stray_engine = member.post(
        "/api/v1/transcript-drafts",
        json={"project_id": project.id, "content": "手录草稿", "engine": "faster-whisper:base"},
    )
    assert stray_engine.status_code == 422
    manual = member.post(
        "/api/v1/transcript-drafts",
        json={"project_id": project.id, "content": "人工手录的访谈要点。"},
    )
    assert manual.status_code == 201
    assert manual.get_json()["data"]["source_kind"] == "manual"


def test_draft_dict_unavailable_fails_closed(db_session, d4_client, d4_settings, monkeypatch) -> None:
    """词典机制性故障 → 503 硬阻断（红线：不因草稿豁免，沿 guidance 同码）。"""
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _new_project(db_session, leader.user, "客户A")
    member, _user = _member_client(db_session, d4_client, d4_settings, project)

    def _boom(*args, **kwargs):
        raise enterprise_dict.RedactionConfigError("dict broken")

    monkeypatch.setattr("fde_api.transcripts.service.redact_text_detailed", _boom)
    response = member.post(
        "/api/v1/transcript-drafts",
        json={"project_id": project.id, "content": "任何文本都写不进去。"},
    )
    assert response.status_code == 503
    assert response.get_json()["error"]["code"] == enterprise_dict.DICT_FAILURE_CODE


def test_draft_list_scoped_without_content(db_session, d4_client, d4_settings) -> None:
    """列表权限=can_view（外人 403/未知 404/未认证 401）；列表行不带正文防大载荷。"""
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _new_project(db_session, leader.user, "客户A")
    other = _new_project(db_session, leader.user, "客户B")
    member, _user = _member_client(db_session, d4_client, d4_settings, project)
    _create_draft(member, project)
    _create_draft(member, project, title="第二段")

    response = member.get(f"/api/v1/transcript-drafts?project_id={project.id}")
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert len(data["items"]) == 2
    assert all("content" not in row and "redaction_entries" not in row for row in data["items"])

    # 项目过滤：另一项目（同 leader 但成员不在）走 project_id 查询同样只回该项目
    scoped = member.get(f"/api/v1/transcript-drafts?project_id={other.id}")
    assert scoped.status_code == 403, "非成员跨项目查询=403（project 装载闸）"

    outsider_client, _outsider = _member_client(db_session, d4_client, d4_settings, other)
    forbidden = outsider_client.get(f"/api/v1/transcript-drafts?project_id={project.id}")
    assert forbidden.status_code == 403
    missing = member.get("/api/v1/transcript-drafts?project_id=missing-project")
    assert missing.status_code == 404
    anonymous = d4_client.get(f"/api/v1/transcript-drafts?project_id={project.id}")
    assert anonymous.status_code == 401


def test_promote_requires_manage_and_triple(db_session, d4_client, d4_settings) -> None:
    """无客户确认的转写文本无法进正式库：三要素缺一即 422；晋升=can_manage。"""
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _new_project(db_session, leader.user, "客户A")
    member, _user = _member_client(db_session, d4_client, d4_settings, project)
    draft = _create_draft(member, project)

    # 成员（can_view 非 can_manage）不可晋升
    member_forbidden = member.post(
        f"/api/v1/transcript-drafts/{draft['id']}/promote",
        json={"title": "纪要", "content": "整理稿", "client_confirmed_by": "客户方负责人",
              "client_confirmed_at": _confirmed_at(), "client_confirmation_method": "verbal"},
    )
    assert member_forbidden.status_code == 403

    def _promote(payload: dict):
        return leader.post(f"/api/v1/transcript-drafts/{draft['id']}/promote", json=payload)

    base = {"title": "初诊访谈纪要", "content": f"纪要正文，来源企业已按代号记录。", "client_confirmed_by": "客户方信息化负责人"}
    # 三要素缺一：缺时间戳 / 缺方式
    missing_at = _promote({**base, "client_confirmation_method": "verbal"})
    assert missing_at.status_code == 422
    missing_method = _promote({**base, "client_confirmed_at": _confirmed_at()})
    assert missing_method.status_code == 422
    bad_method = _promote({**base, "client_confirmed_at": _confirmed_at(), "client_confirmation_method": "email"})
    assert bad_method.status_code == 422
    # CR-029 教训：未来时戳拒绝
    future = _promote({**base, "client_confirmed_at": "2099-01-01T00:00:00+00:00", "client_confirmation_method": "verbal"})
    assert future.status_code == 422

    ok = _promote({**base, "client_confirmed_at": _confirmed_at(), "client_confirmation_method": "verbal"})
    assert ok.status_code == 200, ok.get_json()
    payload = ok.get_json()["data"]
    minutes, tombstone = payload["minutes"], payload["draft"]
    assert minutes["draft_id"] == draft["id"]
    assert minutes["client_confirmation_method"] == "verbal"
    assert tombstone["status"] == "promoted"
    assert tombstone["promoted_ref"] == f"interview_minutes:{minutes['id']}"
    assert "content" not in tombstone, "晋升墓碑不带正文（草稿区不留晋升后正文）"
    assert not (d4_settings.transcript_draft_root / draft["id"]).exists(), "晋升后文件根子树清空"
    # 纪要正文同样过 T-A2（本例正文无企业名——命中计数为 0 也如实记录）
    assert "redaction_hits" in minutes

    # 已晋升草稿再晋升/再弃置 = 409
    assert _promote({**base, "client_confirmed_at": _confirmed_at(), "client_confirmation_method": "verbal"}).status_code == 409
    assert member.post(f"/api/v1/transcript-drafts/{draft['id']}/discard").status_code == 409


def test_minutes_read_faces_and_zero_fk_isolation(db_session, d4_client, d4_settings) -> None:
    """正式库读写面 + 物理隔离机械钉：全库零外键指向 transcript_drafts。"""
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _new_project(db_session, leader.user, "客户A")
    member, _user = _member_client(db_session, d4_client, d4_settings, project)
    draft = _create_draft(member, project)
    promoted = leader.post(
        f"/api/v1/transcript-drafts/{draft['id']}/promote",
        json={"title": "纪要标题", "content": "整理后的纪要正文。",
              "client_confirmed_by": "客户方负责人（口头）",
              "client_confirmed_at": _confirmed_at(), "client_confirmation_method": "meeting"},
    )
    minutes = promoted.get_json()["data"]["minutes"]

    detail = member.get(f"/api/v1/interview-minutes/{minutes['id']}")
    assert detail.status_code == 200
    body = detail.get_json()["data"]
    assert body["content"] == "整理后的纪要正文。"
    assert body["content_sha256"] and len(body["content_sha256"]) == 64

    listing = member.get(f"/api/v1/interview-minutes?project_id={project.id}")
    assert listing.status_code == 200
    rows = listing.get_json()["data"]["items"]
    assert len(rows) == 1 and "content" not in rows[0]

    # 物理隔离机械钉（B#6：引用方永不复制真相，只持指针）：
    # ① 全库无任何 FK 指向 transcript_drafts；② minutes.draft_id 不是 FK。
    from fde_api.auth.models import Base

    refs = [
        constraint.referred_table
        for table in Base.metadata.tables.values()
        for constraint in table.foreign_key_constraints
    ]
    assert "transcript_drafts" not in refs, "草稿行不可被任何表外键引用"
    assert not InterviewMinutes.__table__.c.draft_id.foreign_keys


def test_purge_expired_drafts_t_plus_7(db_session, d4_client, d4_settings) -> None:
    """T+7 清理：到期活动草稿墓碑化（正文/指纹/复核条目抹除+文件清空）；其余零触碰。"""
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _new_project(db_session, leader.user, "客户A")
    member, _user = _member_client(db_session, d4_client, d4_settings, project)

    due = _create_draft(member, project, title="到期草稿")
    fresh = _create_draft(member, project, title="未到期草稿")
    row_due = db_session.get(TranscriptDraft, due["id"])
    row_fresh = db_session.get(TranscriptDraft, fresh["id"])
    row_due.expires_at = datetime.now(UTC) - timedelta(hours=1)  # 人为过期
    db_session.commit()

    now = datetime.now(UTC)
    purged = purge_expired_drafts(now=now, settings=d4_settings)
    assert purged == 1

    db_session.refresh(row_due)
    db_session.refresh(row_fresh)
    assert row_due.status == "expired"
    assert row_due.content is None and row_due.content_sha256 is None and row_due.redaction_entries is None
    assert row_due.cleaned_at is not None
    assert not (d4_settings.transcript_draft_root / row_due.id).exists()
    # 未到期 + 幂等二轮
    assert row_fresh.status == "draft" and row_fresh.content is not None
    assert purge_expired_drafts(now=now, settings=d4_settings) == 0


def test_discard_tombstones_immediately(db_session, d4_client, d4_settings) -> None:
    """人工弃置：墓碑化即时生效，详情不再回正文；二次弃置 409。"""
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _new_project(db_session, leader.user, "客户A")
    member, _user = _member_client(db_session, d4_client, d4_settings, project)
    draft = _create_draft(member, project)

    first = member.post(f"/api/v1/transcript-drafts/{draft['id']}/discard")
    assert first.status_code == 200
    body = first.get_json()["data"]
    assert body["status"] == "discarded" and "content" not in body, "弃置墓碑不回正文键"
    assert not (d4_settings.transcript_draft_root / draft["id"]).exists()

    detail = member.get(f"/api/v1/transcript-drafts/{draft['id']}")
    assert detail.status_code == 200
    assert "content" not in detail.get_json()["data"], "墓碑详情不回正文"
    second = member.post(f"/api/v1/transcript-drafts/{draft['id']}/discard")
    assert second.status_code == 409


def test_discard_requires_owner_or_manager(db_session, d4_client, d4_settings) -> None:
    """CR-066：弃置＝不可逆破坏——创建者本人可弃；非属主成员 403；can_manage 可弃。"""
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _new_project(db_session, leader.user, "客户M")
    member, _u = _member_client(db_session, d4_client, d4_settings, project)
    draft = _create_draft(member, project)

    # 非属主成员（viewer）→ 403
    viewer, _vu = _member_client(db_session, d4_client, d4_settings, project, role="viewer")
    denied = viewer.post(f"/api/v1/transcript-drafts/{draft['id']}/discard")
    assert denied.status_code == 403
    assert denied.json["error"]["code"] == "project_forbidden"  # manage 闸既有码
    # 草稿未受影响
    assert member.get(f"/api/v1/transcript-drafts/{draft['id']}").get_json()["data"]["status"] == "draft"

    # 另一非属主普通成员 → 403
    member2, _u2 = _member_client(db_session, d4_client, d4_settings, project)
    assert member2.post(f"/api/v1/transcript-drafts/{draft['id']}/discard").status_code == 403

    # can_manage（leader）可弃他人草稿
    assert leader.post(f"/api/v1/transcript-drafts/{draft['id']}/discard").status_code == 200
