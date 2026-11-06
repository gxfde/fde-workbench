# T-A2 拍板 6① 收尾钉子：confirm 复核闸（「方案审核人 confirm 前必须复核」的
# 机械强制，补齐 #160 缺口）。
#
# #160（三道防线）把复核条目落 operation_events（guidance.redaction_review，
# 仅 entries 非空才落），但 confirm 无消费点、读面无清单——本文件钉住：
# 1. 复核清单非空 + 未带 redaction_reviewed=true → 409 redaction_review_required；
# 2. 带 ack 放行，动作随 guidance_analysis_confirmed 事件留痕；
# 3. 干净分析（无复核事件）确认零额外负担；
# 4. get_analysis / confirm 响应携带派生 redaction_review（同一事件源聚合）。
#
# 闸与来源种类无关（translator_draft / presurvey_docx 同闸），夹具用
# translator_draft 最小行（无源文件约束）；测试数据全合成。
from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest

from fde_api.auth.models import User
from fde_api.guidance.models import ProjectGuidanceAnalysis
from fde_api.guidance.service import (
    GuidanceServiceError,
    confirm_analysis,
    get_analysis,
    update_analysis,
)
from fde_api.workbench.models import IndustryTemplate, IndustryTemplateVersion, OperationEvent, Project


def _seed_world(db_session, *, source_kind: str = "translator_draft"):
    leader = User(
        username=f"crg.lead.{uuid4().hex}",
        display_name="复核闸负责人",
        role="project_lead",
        password_hash="x",
        must_change_password=False,
        is_active=True,
    )
    template = IndustryTemplate(name="复核闸模板", industry_name="制造")
    template_version = IndustryTemplateVersion(
        template=template, name=template.name, industry_name=template.industry_name,
        description="", version_number=1, status="published", published_by=leader,
    )
    project = Project(
        id=uuid4().hex,
        project_code=f"CRG-{uuid4().hex[:8]}", name="复核闸哨兵项目",
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
        source_kind=source_kind, source_filename="访谈纪要.docx", source_sha256="",
        status="draft", analysis_state="ready", created_by_user_id=leader.id,
        customer_vision="围绕试点展开", current_phase_objective="三个月上线",
        executive_summary="试点先行", evidence_json={},
    )
    db_session.add(analysis)
    db_session.commit()
    return analysis, project, leader


def _write_review_event(db_session, analysis: ProjectGuidanceAnalysis, leader_id: str, entries: list[dict]) -> None:
    db_session.add(
        OperationEvent(
            actor_user_id=leader_id,
            project_id=analysis.project_id,
            target_type="project_guidance_analysis",
            target_id=analysis.id,
            event_type="guidance.redaction_review",
            changes={"entries": entries},
        )
    )
    db_session.commit()


def _confirm_event(db_session, project_id: str) -> OperationEvent | None:
    return (
        db_session.query(OperationEvent)
        .filter_by(project_id=project_id, event_type="guidance_analysis_confirmed")
        .order_by(OperationEvent.occurred_at.desc(), OperationEvent.id.desc())
        .first()
    )


def test_confirm_without_ack_blocked_by_review_event(app, db_session):
    analysis, _project, leader = _seed_world(db_session)
    _write_review_event(db_session, analysis, leader.id, [{"name": "某示例公司", "occurrences": 2, "matched_dict": False}])
    with app.app_context():
        with pytest.raises(GuidanceServiceError) as error:
            confirm_analysis(actor=leader, project_id=analysis.project_id, analysis_id=analysis.id, expected_version=analysis.version)
    assert error.value.code == "redaction_review_required"
    assert error.value.status == 409
    db_session.expire_all()
    assert db_session.get(ProjectGuidanceAnalysis, analysis.id).status == "draft"  # 零变更


def test_confirm_with_ack_confirmed_and_event_payload(app, db_session):
    analysis, project, leader = _seed_world(db_session)
    _write_review_event(db_session, analysis, leader.id, [{"name": "某示例公司", "occurrences": 2, "matched_dict": False}])
    with app.app_context():
        data = confirm_analysis(
            actor=leader, project_id=analysis.project_id, analysis_id=analysis.id,
            expected_version=analysis.version, redaction_reviewed=True,
        )
    assert data["status"] == "confirmed"
    assert data["redaction_review"] == [{"name": "某示例公司", "occurrences": 2, "matched_dict": False}]
    event = _confirm_event(db_session, project.id)
    assert event is not None
    assert event.changes["redaction_reviewed"] is True
    assert event.changes["redaction_review_hits"] == 1


def test_confirm_clean_analysis_needs_no_ack(app, db_session):
    analysis, project, leader = _seed_world(db_session)  # 无复核事件
    with app.app_context():
        data = confirm_analysis(actor=leader, project_id=analysis.project_id, analysis_id=analysis.id, expected_version=analysis.version)
    assert data["status"] == "confirmed"
    assert data["redaction_review"] == []
    event = _confirm_event(db_session, project.id)
    assert event is not None
    assert event.changes["redaction_reviewed"] is False
    assert event.changes["redaction_review_hits"] == 0


def test_get_analysis_surfaces_review_entries(app, db_session):
    analysis, _project, leader = _seed_world(db_session)
    _write_review_event(db_session, analysis, leader.id, [
        {"name": "示例集团", "occurrences": 1, "matched_dict": True},
        {"name": "某示例公司", "occurrences": 3, "matched_dict": False},
    ])
    with app.app_context():
        data = get_analysis(actor=leader, project_id=analysis.project_id, analysis_id=analysis.id)
    assert data["redaction_review"] == [
        {"name": "某示例公司", "occurrences": 3, "matched_dict": False},
        {"name": "示例集团", "occurrences": 1, "matched_dict": True},
    ]  # 按名称排序，形状与写入条目一致


def test_review_entries_merge_across_events(app, db_session):
    analysis, _project, leader = _seed_world(db_session)
    _write_review_event(db_session, analysis, leader.id, [{"name": "示例集团", "occurrences": 1, "matched_dict": True}])
    _write_review_event(db_session, analysis, leader.id, [{"name": "示例集团", "occurrences": 2, "matched_dict": False}])
    with app.app_context():
        data = get_analysis(actor=leader, project_id=analysis.project_id, analysis_id=analysis.id)
    assert data["redaction_review"] == [
        {"name": "示例集团", "occurrences": 3, "matched_dict": True}
    ]  # 跨事件同名合并：occurrences 累加、matched_dict 求并


def test_review_persists_across_field_edits(app, db_session):
    analysis, _project, leader = _seed_world(db_session)
    _write_review_event(db_session, analysis, leader.id, [{"name": "某示例公司", "occurrences": 1, "matched_dict": False}])
    with app.app_context():
        # 复核清单是「历史上替换了什么」的审计事实：编辑正文不改写清单。
        update_analysis(
            actor=leader, project_id=analysis.project_id, analysis_id=analysis.id,
            expected_version=analysis.version, changes={"executive_summary": "人工改写后的摘要"},
        )
        data = get_analysis(actor=leader, project_id=analysis.project_id, analysis_id=analysis.id)
    assert data["executive_summary"] == "人工改写后的摘要"
    assert data["redaction_review"] == [{"name": "某示例公司", "occurrences": 1, "matched_dict": False}]
