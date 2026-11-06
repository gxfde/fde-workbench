"""goal-d2 S0 收尾：方案骨架 + 健康分 v0 + SOW→合同串联 + 指引确认埋点 + 行业模板种子。

对应《技术实施方案-智能体交付工作台》S0-3~S0-6 与 PRD §10 P0 四指标埋点。
"""
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from test_document_drafts_api import (
    _add_viewer_member,
    _persist_doc_template,
    _persist_project,
    authorized_client_factory,  # noqa: F401  (leader/viewer/outsider 的依赖夹具)
    leader_client,  # noqa: F401  (pytest fixture)
    outsider_client,  # noqa: F401
    viewer_client,  # noqa: F401
)
from fde_api.files.models import ProjectFile, ProjectFileVersion
from fde_api.guidance.models import PresurveyIntake, ProjectGuidanceAnalysis
from fde_api.research.models import (
    ProjectAIOpportunityProfile,
    ProjectResearchSubject,
    TemplateResearchField,
    TemplateResearchForm,
    TemplateResearchSection,
)
from fde_api.workbench.models import (
    IndustryTemplate,
    IndustryTemplateVersion,
    OperationEvent,
    Quote,
    TemplateModule,
)
from fde_api.workbench.seed import INDUSTRY_TEMPLATE_SEEDS, seed_industry_templates, seed_workbench


def _opportunity(db_session, project, key="one"):
    item = ProjectResearchSubject(
        project_id=project.id, subject_type="opportunity", subject_key=key,
        name=f"机会-{key}", description=f"需求-{key}", tracking_code=f"OPP-{key}", status="active",
    )
    item.opportunity_profile = ProjectAIOpportunityProfile(opportunity_status="ready")
    db_session.add(item)
    db_session.commit()
    return item


def _confirmed_guidance(
    db_session, project, leader, *, version_number=1, problems=(), success=(),
    systems=(), assumptions=(), out_of_scope=(), open_questions=(),
):
    """ORM 直造已确认指引（含项目文件版本桩）——骨架与埋点用例的最快路径。"""
    file_id, version_id = uuid4().hex, uuid4().hex
    project_file = ProjectFile(
        id=file_id, project=project, category="attachment",
        display_name="预调研表", description="", created_by=leader,
    )
    version = ProjectFileVersion(
        id=version_id, project_file=project_file, version_number=1,
        source="upload", original_filename="预调研表.docx",
        safe_filename="presurvey.docx", extension="docx", mime_type="",
        bucket="local", storage_key=f"projects/{project.id}/presurvey.docx",
        size_bytes=10, etag="", sha256="", uploaded_by=leader,
        status="available", scan_status="clean", preview_status="none",
    )
    analysis = ProjectGuidanceAnalysis(
        project_id=project.id, version_number=version_number,
        source_file_id=file_id, source_file_version_id=version_id,
        source_filename="预调研表.docx", source_sha256="",
        status="confirmed", analysis_state="ready",
        customer_vision="三年内建成数据驱动的门店网络",
        current_phase_objective="完成诊断与试点", executive_summary="骨架输入",
        created_by_user_id=leader.id,
        key_business_problems_json=list(problems),
        success_criteria_json=list(success),
        systems_and_deployment_constraints_json=list(systems),
        assumptions_json=list(assumptions),
        out_of_scope_json=list(out_of_scope),
        open_questions_json=list(open_questions),
    )
    # 与 test_guidance_retry 相同的分步 flush：环形外键（文件 ↔ 版本）干扰
    # 工作单元插入排序，世界实体先落库，分析行后插。
    db_session.add_all([project_file, version])
    db_session.flush()
    db_session.add(analysis)
    db_session.commit()
    return analysis


def _events(db_session, event_type, project):
    return list(db_session.scalars(
        select(OperationEvent)
        .where(OperationEvent.project_id == project.id, OperationEvent.event_type == event_type)
        .order_by(OperationEvent.created_at)
    ))


# ---------------------------------------------------------------------------
# S0-4 方案骨架
# ---------------------------------------------------------------------------


def test_skeleton_requires_confirmed_guidance_and_manager(db_session, leader_client, viewer_client, outsider_client):
    project = _persist_project(db_session, leader_client.user, code="D2-SKELETON-GATE")
    base = f"/api/v1/projects/{project.id}/solutions"
    assert leader_client.post(base + "/skeleton", json={}).status_code == 409, "无 confirmed 指引必须 409"
    body = leader_client.post(base + "/skeleton", json={})
    assert body.json["error"]["code"] == "solution_skeleton_guidance_required"
    _confirmed_guidance(db_session, project, leader_client.user)
    assert viewer_client.post(base + "/skeleton", json={}).status_code == 403
    assert outsider_client.post(base + "/skeleton", json={}).status_code == 403
    assert leader_client.post(base + "/skeleton", json={"unexpected": 1}).status_code == 400
    assert leader_client.post(base + "/skeleton", json={"business_category": "nope"}).status_code == 400
    assert leader_client.post(base + "/skeleton", json={"name": ""}).status_code == 400


def test_skeleton_composes_from_guidance_with_industry_template(db_session, leader_client):
    seed_workbench(db_session)  # 含 BASE 模块目录 + 通用模板 + 行业种子
    db_session.commit()  # API 走独立事务，种子必须先落库可见
    project = _persist_project(db_session, leader_client.user, code="D2-SKELETON-RETAIL")
    db_session.add(PresurveyIntake(
        project_id=project.id, industry="零售连锁", interview_mode="onsite",
        updated_by_user_id=leader_client.user.id,
    ))
    db_session.commit()
    _confirmed_guidance(
        db_session, project, leader_client.user,
        problems=(
            {"text": "门店巡检靠人工", "classification": "customer_stated", "source_refs": [], "confirmed": True, "severity": "high", "module": "门店运营"},
            {"text": "补货预测不准", "classification": "ai_synthesized", "source_refs": [], "confirmed": True},
        ),
        success=({"text": "巡检覆盖率≥90%", "classification": "human_added", "source_refs": [], "confirmed": True},),
        systems=({"text": "ERP 仅开放只读接口", "classification": "customer_stated", "source_refs": [], "confirmed": True},),
        assumptions=({"text": "客户可提供历史巡检记录", "classification": "ai_inferred", "source_refs": [], "confirmed": True},),
        out_of_scope=({"text": "本轮不含仓储机器人", "classification": "customer_stated", "source_refs": [], "confirmed": True},),
        open_questions=({"text": "会员数据授权范围待确认", "classification": "open_question", "source_refs": [], "confirmed": True},),
    )
    response = leader_client.post(f"/api/v1/projects/{project.id}/solutions/skeleton", json={})
    assert response.status_code == 201, response.json
    item = response.json["data"]
    assert item["source"]["kind"] == "skeleton"
    assert item["name"] == "零售连锁方案骨架"
    seeded_version = db_session.scalar(
        select(IndustryTemplateVersion).where(IndustryTemplateVersion.industry_name == "零售连锁")
    )
    assert item["source"]["industry_template_version_id"] == seeded_version.id
    assert item["source"]["guidance_version_number"] == 1
    design = item["design_markdown"]
    assert "门店巡检靠人工" in design and "high/门店运营" in design
    assert "补货预测不准" in design
    assert "## 方案设想（待人工修订）" in design
    # T-A5：三选项 + 取舍 + 明确不做三段齐备（行业模板路径同样受益）。
    assert "## 方案选项与取舍" in design
    assert "选项 A" in design and "选项 B" in design and "选项 C" in design and "取舍" in design
    assert "## 明确不做（本阶段不包含）" in design
    assert "本轮不含仓储机器人" in design
    assert "巡检覆盖率≥90%" in item["acceptance_criteria"] and "验收口径待补" in item["acceptance_criteria"]
    assert "ERP 仅开放只读接口" in item["data_systems"]
    assert "预调研" in item["schedule"] and "培训与交接" in item["schedule"], "行业模板模块应进入排期骨架"
    risks = item["risks_dependencies"]
    assert "假设" in risks and "本阶段不包含" in risks and "待确认问题" in risks
    events = _events(db_session, "project_solution_created", project)
    assert events and events[-1].changes.get("source") == "skeleton"


def test_skeleton_without_intake_stays_generic_and_links_opportunities(db_session, leader_client):
    project = _persist_project(db_session, leader_client.user, code="D2-SKELETON-GENERIC")
    opportunity = _opportunity(db_session, project)
    _confirmed_guidance(db_session, project, leader_client.user)
    response = leader_client.post(
        f"/api/v1/projects/{project.id}/solutions/skeleton",
        json={"opportunity_ids": [opportunity.id], "name": "自定义骨架名"},
    )
    assert response.status_code == 201, response.json
    item = response.json["data"]
    assert item["name"] == "自定义骨架名"
    assert item["opportunity_ids"] == [opportunity.id]
    assert item["source"]["industry_template_version_id"] is None
    assert "待补：阶段与里程碑" in item["schedule"]


# ---------------------------------------------------------------------------
# S0-4 健康分 v0
# ---------------------------------------------------------------------------


def _quote(db_session, project, owner, *, status="finalized", key=None):
    quote = Quote(
        project_id=project.id, quote_key=key or f"Q-{uuid4().hex[:8]}", status=status,
        tier="light", ideal_hours=Decimal("100"), realistic_hours=Decimal("100"),
        integration_factor=Decimal("1.00"), data_factor=Decimal("1.00"),
        compliance_factor=Decimal("1.00"), buffer_factor=Decimal("1.00"),
        hourly_rate=150, cash_cost=100000, margin_factor=Decimal("1.40"),
        b_layer_score=0, b_layer_factor=Decimal("1.00"), anchor_mode="steady",
        labor_cost=Decimal("100000"), total_cost=Decimal("100000"),
        formula_price=Decimal("200000"), anchor_low=200000, anchor_high=200000,
        branch="A", owner_user_id=owner.id,
    )
    db_session.add(quote)
    db_session.commit()
    return quote


def test_solution_health_scores_coverage_reference_and_quote(db_session, leader_client, viewer_client):
    project = _persist_project(db_session, leader_client.user, code="D2-HEALTH")
    opportunity = _opportunity(db_session, project)
    _confirmed_guidance(db_session, project, leader_client.user)
    url = f"/api/v1/projects/{project.id}/solutions"
    created = leader_client.post(url, json={
        "name": "部分填写方案", "opportunity_ids": [opportunity.id],
        "design_markdown": "## 业务流程\n- 已填", "deliverables": "交付应用",
    })
    assert created.status_code == 201, created.json
    item = created.json["data"]
    health_url = f"{url}/{item['id']}/health"
    health = leader_client.get(health_url)
    assert health.status_code == 200, health.json
    data = health.json["data"]
    assert data["max_score"] == 120
    assert data["breakdown"]["template_coverage"]["score"] == 20, "六段只填两段"
    assert set(data["breakdown"]["template_coverage"]["missing"]) == {"验收标准", "所需数据/系统", "计划排期", "风险与依赖"}
    assert data["breakdown"]["reference_integrity"]["score"] == 30, "机会 + confirmed 指引双满分"
    assert data["breakdown"]["quote_validity"] == {"score": 0, "max": 30, "state": "missing"}
    assert data["score"] == 50
    assert any("报价" in issue for issue in data["issues"])

    patch = leader_client.patch(f"{url}/{item['id']}", json={
        "version": item["version"], "acceptance_criteria": "按验收单",
        "data_systems": "客户 ERP", "schedule": "两周", "risks_dependencies": "接口授权",
    })
    assert patch.status_code == 200, patch.json
    _quote(db_session, project, leader_client.user, status="draft")
    data = leader_client.get(health_url).json["data"]
    assert data["breakdown"]["template_coverage"]["score"] == 60
    assert data["breakdown"]["quote_validity"]["state"] == "draft"
    assert data["score"] == 105

    _quote(db_session, project, leader_client.user, status="finalized")
    data = leader_client.get(health_url).json["data"]
    assert data["breakdown"]["quote_validity"]["state"] == "finalized"
    assert data["score"] == 120
    _add_viewer_member(db_session, project, viewer_client.user)
    assert viewer_client.get(health_url).status_code == 200, "查看健康分只需项目可读"


# ---------------------------------------------------------------------------
# S0-5 SOW→合同串联审计
# ---------------------------------------------------------------------------


def test_sow_contract_link_event_follows_confirmed_export(db_session, leader_client):
    project = _persist_project(db_session, leader_client.user, code="D2-SOW-LINK")
    opportunity = _opportunity(db_session, project)
    _persist_doc_template(db_session, leader_client.user)
    url = f"/api/v1/projects/{project.id}/solutions"
    item = leader_client.post(url, json={
        "name": "串联方案", "opportunity_ids": [opportunity.id],
        "design_markdown": "## 方案\n- 内容",
    }).json["data"]
    export = leader_client.post(f"{url}/{item['id']}/export-sow", json={"version": 1}).json["data"]

    contracts = f"/api/v1/projects/{project.id}/contracts"
    first = leader_client.post(contracts, json={"sow_type": "a"})
    assert first.status_code == 200, first.json
    assert not _events(db_session, "sow_contract_linked", project), "文档未 confirm 前不得联动"

    confirm = leader_client.post(
        f"/api/v1/projects/{project.id}/documents/{export['document_version_id']}/confirm",
        json={"version": export["document"]["version"]},
    )
    assert confirm.status_code == 200, confirm.json

    second = leader_client.post(contracts, json={"sow_type": "b"})
    assert second.status_code == 200, second.json
    linked = _events(db_session, "sow_contract_linked", project)
    assert len(linked) == 1, "仅新建档触发联动"
    changes = linked[0].changes
    assert changes["solution_id"] == item["id"]
    assert changes["solution_version"] == 1
    assert changes["document_id"] == export["document_id"]
    assert changes["document_version_id"] == export["document_version_id"]
    assert changes["sow_type"] == "b"

    update = leader_client.post(contracts, json={"sow_type": "b", "note": "补录条款"})
    assert update.status_code == 200, update.json
    assert len(_events(db_session, "sow_contract_linked", project)) == 1, "更新不再联动"
    assert len(_events(db_session, "contract_recorded", project)) == 2
    assert len(_events(db_session, "contract_updated", project)) == 1


def test_sow_contract_link_skips_projects_without_export(db_session, leader_client):
    project = _persist_project(db_session, leader_client.user, code="D2-SOW-NOEXPORT")
    contracts = f"/api/v1/projects/{project.id}/contracts"
    assert leader_client.post(contracts, json={"sow_type": "a"}).status_code == 200
    assert not _events(db_session, "sow_contract_linked", project)


# ---------------------------------------------------------------------------
# P0 指标①：指引确认事件
# ---------------------------------------------------------------------------


def test_confirm_analysis_records_metric_event(db_session, leader_client):
    project = _persist_project(db_session, leader_client.user, code="D2-CONFIRM-EVENT")
    analysis = _confirmed_guidance(db_session, project, leader_client.user)  # 占位：先造文件桩
    draft = ProjectGuidanceAnalysis(
        project_id=project.id, version_number=2,
        source_file_id=analysis.source_file_id, source_file_version_id=analysis.source_file_version_id,
        source_filename="预调研表-v2.docx", source_sha256="",
        status="draft", analysis_state="ready",
        customer_vision="愿景", current_phase_objective="目标", executive_summary="摘要",
        created_by_user_id=leader_client.user.id,
    )
    db_session.add(draft)
    db_session.commit()
    response = leader_client.post(
        f"/api/v1/projects/{project.id}/guidance-analyses/{draft.id}/confirm",
        json={"version": draft.version},
    )
    assert response.status_code == 200, response.json
    events = _events(db_session, "guidance_analysis_confirmed", project)
    assert len(events) == 1
    changes = events[0].changes
    assert changes["analysis_id"] == draft.id
    assert changes["version_number"] == 2
    assert changes["source_file_version_id"] == draft.source_file_version_id


# ---------------------------------------------------------------------------
# S0-6 行业模板种子
# ---------------------------------------------------------------------------


def test_industry_template_seeds_are_idempotent_and_complete(db_session):
    seed_workbench(db_session)  # 生产入口：模块目录 → 通用模板 → 行业种子
    seed_industry_templates(db_session)  # 幂等：二次播种不新增不报错
    db_session.flush()
    keys = set()
    for seed in INDUSTRY_TEMPLATE_SEEDS:
        template = db_session.scalar(
            select(IndustryTemplate).where(IndustryTemplate.template_key == seed["template_key"])
        )
        assert template is not None and template.status == "active"
        assert template.latest_published_version_number == 1
        keys.add(template.template_key)
        versions = list(db_session.scalars(
            select(IndustryTemplateVersion).where(IndustryTemplateVersion.template_id == template.id)
        ))
        assert len(versions) == 1 and versions[0].status == "published"
        modules = db_session.scalar(select(func.count()).select_from(TemplateModule).where(
            TemplateModule.template_version_id == versions[0].id))
        assert modules == 5, "每行业模板铺 BASE 五模块"
        form = db_session.scalar(select(TemplateResearchForm).where(
            TemplateResearchForm.template_version_id == versions[0].id,
            TemplateResearchForm.form_key == seed["form"]["form_key"]))
        assert form is not None
        sections = list(db_session.scalars(select(TemplateResearchSection).where(
            TemplateResearchSection.form_id == form.id).order_by(TemplateResearchSection.sort_order)))
        assert len(sections) == len(seed["form"]["sections"])
        for section, expected in zip(sections, seed["form"]["sections"]):
            fields = db_session.scalars(select(TemplateResearchField).where(
                TemplateResearchField.section_id == section.id)).all()
            assert len(fields) == len(expected["fields"])
            assert all(field.field_type in {"short_text", "long_text"} for field in fields)
    assert len(keys) == 3
