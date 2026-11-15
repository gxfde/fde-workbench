"""goal-crv-fix2 r5 批 G 回归钉（QR-133 指纹化复核清单 / QR-134 编辑复扫）。

- QR-133（拍板 #6A）：redaction_review 事件账零真名——guidance worker 与
  translator 创建/落库两阶段的确证命中只存域分隔 sha256 指纹（name_hash），
  未确证疑似名不入条目账只留聚合计数（suspect_count）；采纳流指纹形状原样
  搬运；读面投影经词典反解（命中显示词目原文、未命中 name=None 软失败）。
- QR-134（拍板 #7A）：update_analysis 保存时输出端复扫——词典确证命中即拒
  （422 redaction_name_detected，fail-closed），疑似名替换为代号放行并写
  manual_edit 复核事件（仅聚合计数）；presurvey 录入卡维持豁免（拍板登记
  AGENTS.md，用户自填自述≠AI 加工面）。

测试数据全合成（AGENTS 红线：真实客户资料不可作测试素材）。
"""
from __future__ import annotations

import json
from datetime import date
from uuid import uuid4

import pytest

from fde_api.auth.models import User
from fde_api.guidance.enterprise_dict import EXTRA_DICT_ENV, reset_dict_cache
from fde_api.guidance.models import ProjectGuidanceAnalysis, REDACTION_EVENT_TYPE
from fde_api.guidance.redaction import redaction_name_hash
from fde_api.guidance.service import (
    GuidanceServiceError,
    get_analysis,
    update_analysis,
)
from fde_api.workbench.models import IndustryTemplate, IndustryTemplateVersion, OperationEvent, Project

SEED_NAME = "黑名单示例控股公司"
SUSPECT_NAME = "未登记示例厂"


@pytest.fixture(autouse=True)
def _clean_dict_env(monkeypatch):
    monkeypatch.delenv(EXTRA_DICT_ENV, raising=False)
    reset_dict_cache()
    yield
    reset_dict_cache()


def _seed_world(db_session) -> tuple[ProjectGuidanceAnalysis, Project, User]:
    leader = User(
        username=f"crg.g.lead.{uuid4().hex}",
        display_name="批G负责人",
        role="project_lead",
        password_hash="x",
        must_change_password=False,
        is_active=True,
    )
    template = IndustryTemplate(name="批G模板", industry_name="制造")
    template_version = IndustryTemplateVersion(
        template=template, name=template.name, industry_name=template.industry_name,
        description="", version_number=1, status="published", published_by=leader,
    )
    project = Project(
        id=uuid4().hex,
        project_code=f"BG-{uuid4().hex[:8]}", name="批G哨兵项目",
        enterprise_code="客户A·制造业·苏州", leader=leader, business_line="FDE",
        source_template_version=template_version, template_snapshot={},
        planned_start_date=date(2026, 1, 1),
    )
    db_session.add_all([leader, template])
    db_session.flush()
    db_session.add(template_version)
    db_session.flush()
    db_session.add(project)
    db_session.flush()
    analysis = ProjectGuidanceAnalysis(
        id=uuid4().hex, project_id=project.id, version_number=1,
        source_kind="translator_draft", source_filename="访谈纪要.docx", source_sha256="",
        status="draft", analysis_state="ready", created_by_user_id=leader.id,
        customer_vision="围绕试点展开", current_phase_objective="三个月上线",
        executive_summary="试点先行", evidence_json={},
    )
    db_session.add(analysis)
    db_session.commit()
    return analysis, project, leader


def _write_review_event(db_session, analysis: ProjectGuidanceAnalysis, leader_id: str, changes: dict) -> None:
    db_session.add(
        OperationEvent(
            actor_user_id=leader_id,
            project_id=analysis.project_id,
            target_type="project_guidance_analysis",
            target_id=analysis.id,
            event_type=REDACTION_EVENT_TYPE,
            changes=changes,
        )
    )
    db_session.commit()


def _redaction_events(db_session, target_type: str, target_id: str) -> list[OperationEvent]:
    return (
        db_session.query(OperationEvent)
        .filter_by(target_type=target_type, target_id=target_id, event_type=REDACTION_EVENT_TYPE)
        .order_by(OperationEvent.occurred_at.asc(), OperationEvent.id.asc())
        .all()
    )


# ---------------------------------------------------------------------------
# QR-133：事件账零真名（写入侧指纹化单一真身行为）
# ---------------------------------------------------------------------------


def test_fingerprint_review_entries_shapes(db_session) -> None:
    """确证命中→指纹条目；疑似→聚合计数；全零→空事件省略。"""
    from fde_api.guidance.redaction import fingerprint_review_entries

    entries = [
        {"name": SEED_NAME, "occurrences": 2, "matched_dict": True},
        {"name": SEED_NAME, "occurrences": 1, "matched_dict": True},
        {"name": SUSPECT_NAME, "occurrences": 3, "matched_dict": False},
    ]
    fingerprinted, suspect_count = fingerprint_review_entries(entries)
    assert fingerprinted == [
        {"name_hash": redaction_name_hash(SEED_NAME), "occurrences": 2, "matched_dict": True},
        {"name_hash": redaction_name_hash(SEED_NAME), "occurrences": 1, "matched_dict": True},
    ]
    assert suspect_count == 3
    assert SEED_NAME not in json.dumps(fingerprinted, ensure_ascii=False)
    assert SUSPECT_NAME not in json.dumps(fingerprinted, ensure_ascii=False)


def test_resolve_redaction_display_dict_hit_and_miss(db_session) -> None:
    """词典命中反解原文；未命中指纹 name=None 软失败；零条目零词典调用。"""
    from fde_api.guidance.redaction import resolve_redaction_display

    assert resolve_redaction_display([]) == []
    displayed = resolve_redaction_display(
        [
            {"name_hash": redaction_name_hash(SEED_NAME), "occurrences": 2, "matched_dict": True},
            {"name_hash": redaction_name_hash(SUSPECT_NAME), "occurrences": 1, "matched_dict": True},
        ]
    )
    assert displayed[0]["name"] == SEED_NAME
    assert displayed[1]["name"] is None  # 词典未收录 → 占位不抛


def test_guidance_worker_event_zero_real_names(app, db_session, monkeypatch) -> None:
    """worker 全链（docx→AI→落库→事件）事件账 JSON 序列化零真名＋指纹在场。

    夹具级复用 test_guidance_redaction_worker 的最小世界（此处只验事件账形状，
    行为断言归该套件）。"""
    import test_guidance_redaction_worker as worker_mod

    analysis, job, _project_id, leader_id = worker_mod._setup_world(
        db_session, docx_text=f"甲方是 {SEED_NAME}，需要 MES。另有{SUSPECT_NAME}参与。"
    )

    class _Capture:
        contents: list[str] = []

        def __init__(self, *, version_id=None, **_kwargs):
            self._version_id = version_id or ""

        def analyze_docx_json(self, *, stream, filename, request_id, build_messages):
            from fde_api.documents.qa import extract_docx_xml_text

            raw = extract_docx_xml_text(stream)
            build_messages(raw)
            source_ref = f"kimi-file:{self._version_id}"
            return worker_mod._valid_payload(
                source_ref, echo_text=f" {SEED_NAME} 希望试点；{SUSPECT_NAME} 也在推进。"
            )

    monkeypatch.setattr(
        worker_mod.guidance_jobs, "KimiFileClient", lambda **kwargs: _Capture(version_id=analysis.source_file_version_id)
    )
    with app.app_context():
        worker_mod.handle_presurvey_analysis(job)

    db_session.expire_all()
    refreshed = db_session.get(ProjectGuidanceAnalysis, analysis.id)
    assert refreshed.analysis_state == "ready"
    events = _redaction_events(db_session, "project_guidance_analysis", analysis.id)
    assert events, "复核事件必须落账"
    blob = json.dumps([event.changes for event in events], ensure_ascii=False, default=str)
    assert SEED_NAME not in blob
    assert SUSPECT_NAME not in blob
    assert any(
        item["name_hash"] == redaction_name_hash(SEED_NAME) and item["matched_dict"]
        for event in events
        for item in event.changes.get("entries", [])
    )
    assert any(event.changes.get("suspect_count", 0) >= 1 for event in events)


# ---------------------------------------------------------------------------
# QR-133：读面投影（聚合＋反解＋疑似计数项）
# ---------------------------------------------------------------------------


def test_review_projection_merges_fingerprint_and_suspect_count(app, db_session) -> None:
    analysis, _project, leader = _seed_world(db_session)
    _write_review_event(
        db_session, analysis, leader.id,
        {"entries": [{"name_hash": redaction_name_hash(SEED_NAME), "occurrences": 2, "matched_dict": True}],
         "suspect_count": 1},
    )
    _write_review_event(
        db_session, analysis, leader.id,
        {"entries": [{"name_hash": redaction_name_hash(SEED_NAME), "occurrences": 1, "matched_dict": True}],
         "suspect_count": 2},
    )
    with app.app_context():
        data = get_analysis(actor=leader, project_id=analysis.project_id, analysis_id=analysis.id)
    review = data["redaction_review"]
    assert review == [
        # 词典命中反解原文；跨事件 occurrences 累加；疑似聚合计数项殿后。
        {"name_hash": redaction_name_hash(SEED_NAME), "name": SEED_NAME, "occurrences": 3, "matched_dict": True},
        {"suspect_count": 3},
    ]


def test_legacy_name_shape_events_still_aggregate(app, db_session) -> None:
    """历史 name 形状事件（批 G 前落库）读面兼容：现算指纹归一聚合。"""
    analysis, _project, leader = _seed_world(db_session)
    _write_review_event(
        db_session, analysis, leader.id,
        {"entries": [{"name": SEED_NAME, "occurrences": 1, "matched_dict": True}]},
    )
    with app.app_context():
        data = get_analysis(actor=leader, project_id=analysis.project_id, analysis_id=analysis.id)
    assert data["redaction_review"] == [
        {"name_hash": redaction_name_hash(SEED_NAME), "name": SEED_NAME, "occurrences": 1, "matched_dict": True}
    ]


# ---------------------------------------------------------------------------
# QR-134：update_analysis 输出端复扫（确证命中即拒 / 疑似替换放行＋计数事件）
# ---------------------------------------------------------------------------


def test_update_analysis_rejects_dict_hit(db_session) -> None:
    """人工编辑引入词典确证客户名 → 422 fail-closed（用户先替换为客户代号）。"""
    analysis, project, leader = _seed_world(db_session)
    with pytest.raises(GuidanceServiceError) as excinfo:
        update_analysis(
            actor=leader, project_id=project.id, analysis_id=analysis.id,
            expected_version=analysis.version,
            changes={"executive_summary": f"建议先与{SEED_NAME}共建试点。"},
        )
    assert excinfo.value.status == 422
    assert excinfo.value.code == "redaction_name_detected"
    assert SEED_NAME not in excinfo.value.message  # 错误消息不回显命中原文
    db_session.expire_all()
    assert db_session.get(ProjectGuidanceAnalysis, analysis.id).executive_summary == "试点先行"


def test_update_analysis_rescans_list_fields(db_session) -> None:
    """列表字段 str 值同样过闸：命中即拒。"""
    analysis, project, leader = _seed_world(db_session)
    with pytest.raises(GuidanceServiceError) as excinfo:
        update_analysis(
            actor=leader, project_id=project.id, analysis_id=analysis.id,
            expected_version=analysis.version,
            changes={"next_actions": [{"text": f"拜访{SEED_NAME}洽谈二期", "owner": "leader"}]},
        )
    assert excinfo.value.status == 422
    assert excinfo.value.code == "redaction_name_detected"


def test_update_analysis_suspect_replaced_and_counted(db_session) -> None:
    """疑似名替换为代号放行＋manual_edit 复核事件（仅聚合计数，零真名）。"""
    analysis, project, leader = _seed_world(db_session)
    data = update_analysis(
        actor=leader, project_id=project.id, analysis_id=analysis.id,
        expected_version=analysis.version,
        changes={"customer_vision": f"主要对手是{SUSPECT_NAME}，需要差异化。"},
    )
    assert SUSPECT_NAME not in data["customer_vision"]
    assert "客户A" in data["customer_vision"]
    events = [
        event
        for event in _redaction_events(db_session, "project_guidance_analysis", analysis.id)
        if event.changes.get("stage") == "manual_edit"
    ]
    assert len(events) == 1
    assert events[0].changes["suspect_count"] >= 1
    assert SUSPECT_NAME not in json.dumps(events[0].changes, ensure_ascii=False, default=str)


def test_update_analysis_clean_edit_writes_no_event(db_session) -> None:
    """干净编辑（无命中无疑似）零复核事件、零额外负担。"""
    analysis, project, leader = _seed_world(db_session)
    update_analysis(
        actor=leader, project_id=project.id, analysis_id=analysis.id,
        expected_version=analysis.version,
        changes={"executive_summary": "人工改写后的干净摘要"},
    )
    assert _redaction_events(db_session, "project_guidance_analysis", analysis.id) == []


def test_update_analysis_credential_detected_422(db_session) -> None:
    """凭据串沿用既有 422 sensitive_credential_detected 契约（复扫面同闸）。"""
    analysis, project, leader = _seed_world(db_session)
    with pytest.raises(GuidanceServiceError) as excinfo:
        update_analysis(
            actor=leader, project_id=project.id, analysis_id=analysis.id,
            expected_version=analysis.version,
            changes={"customer_vision": "密码: sk-abcdefgh1234567890 已轮换"},
        )
    assert excinfo.value.status == 422
    assert excinfo.value.code == "sensitive_credential_detected"
