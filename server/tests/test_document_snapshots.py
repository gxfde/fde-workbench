from __future__ import annotations

from datetime import date

from fde_api.auth.models import User
from fde_api.documents.snapshots import build_document_snapshot
from fde_api.research.models import (
    ProjectResearchAnswer,
    ProjectResearchForm,
    ProjectResearchFormRevision,
    ProjectResearchSubject,
    TemplateResearchField,
    TemplateResearchForm,
    TemplateResearchSection,
)
from fde_api.workbench.models import (
    IndustryTemplate,
    IndustryTemplateVersion,
    ModuleCatalog,
    Project,
    ProjectMember,
    ProjectModule,
    ProjectTask,
)


def _build_persisted_project(db_session, *, code: str, leader):
    industry_template = IndustryTemplate(name="调研模板", industry_name="制造")
    template_version = IndustryTemplateVersion(
        template=industry_template,
        name=industry_template.name,
        industry_name=industry_template.industry_name,
        description="",
        version_number=1,
        status="published",
        published_by=leader,
    )
    project = Project(
        project_code=code,
        name="文档快照项目",
        enterprise_name="星河制造",
        leader=leader,
        source_template_version=template_version,
        template_snapshot={},
        research_snapshot={},
        planned_start_date=date(2026, 8, 22),
    )
    db_session.add(project)
    db_session.flush()
    db_session.add(ProjectMember(project_id=project.id, user_id=leader.id, role="member"))

    module_catalog = ModuleCatalog(
        module_key="pre_diagnosis",
        name="前期诊断",
        description="",
        sort_order=10,
        is_active=True,
    )
    db_session.add(module_catalog)
    db_session.flush()
    project_module = ProjectModule(
        project_id=project.id,
        module_catalog_id=module_catalog.id,
        name="前期诊断",
        description="",
        sort_order=10,
    )
    db_session.add(project_module)
    db_session.flush()
    task = ProjectTask(
        project_module_id=project_module.id,
        task_key="diagnose",
        name="诊断任务",
        description="",
        status="in_progress",
        planned_start_date=date(2026, 8, 22),
        planned_end_date=date(2026, 8, 24),
        duration_days=2,
        progress=40,
        sort_order=1,
    )
    db_session.add(task)
    db_session.commit()
    return project


def _add_role_subject(db_session, project, *, subject_key: str, name: str):
    subject = ProjectResearchSubject(
        project=project,
        subject_type="role",
        subject_key=subject_key,
        name=name,
        description="",
        sort_order=0,
        status="active",
    )
    db_session.add(subject)
    db_session.flush()
    return subject


def _add_confirmed_role_form(db_session, project, subject, *, form_key: str):
    template_form = TemplateResearchForm(
        template_version=project.source_template_version,
        form_key=form_key,
        name="角色访谈",
        description="",
        subject_type="role",
        sort_order=0,
    )
    db_session.add(template_form)
    db_session.flush()
    section = TemplateResearchSection(
        form=template_form,
        section_key="context",
        name="背景",
        sort_order=0,
    )
    db_session.add(section)
    db_session.flush()
    field = TemplateResearchField(
        section=section,
        field_key="main_problem",
        name="主要问题",
        field_type="short_text",
        sort_order=0,
    )
    db_session.add(field)
    db_session.flush()

    form = ProjectResearchForm(
        project=project,
        subject=subject,
        source_template_form=template_form,
        form_key=form_key,
        name="角色访谈",
        description="",
    )
    db_session.add(form)
    db_session.flush()
    revision = ProjectResearchFormRevision(
        form=form,
        revision_number=1,
        status="confirmed",
    )
    db_session.add(revision)
    db_session.flush()
    answer = ProjectResearchAnswer(
        revision=revision,
        source_template_field=field,
        field_key="main_problem",
        value_json={"text": "排产信息分散"},
    )
    db_session.add(answer)
    db_session.commit()
    return form


def test_snapshot_uses_subject_ids_not_duplicate_names(db_session):
    """Two research subjects sharing a name must stay distinct by id in the snapshot."""
    leader = User(username="snapshot.leader", password_hash="x", role="project_lead")
    db_session.add(leader)
    db_session.commit()
    project = _build_persisted_project(db_session, code="SNAP-DUP-001", leader=leader)

    first = _add_role_subject(db_session, project, subject_key="dup_role_a", name="重复角色")
    second = _add_role_subject(db_session, project, subject_key="dup_role_b", name="重复角色")
    assert first.name == second.name
    assert first.id != second.id

    snapshot = build_document_snapshot(db_session, project.id, {"research_keys": []})

    role_rows = snapshot["subjects"]["role"]
    ids = {row["id"] for row in role_rows}
    assert len(role_rows) == 2
    assert ids == {first.id, second.id}


def test_snapshot_includes_tasks_members_research(db_session):
    """The snapshot embeds non-empty tasks, members and confirmed research values."""
    leader = User(username="snapshot.lead2", password_hash="x", role="project_lead")
    db_session.add(leader)
    db_session.commit()
    project = _build_persisted_project(db_session, code="SNAP-FULL-001", leader=leader)

    subject = _add_role_subject(db_session, project, subject_key="planner", name="计划员")
    _add_confirmed_role_form(db_session, project, subject, form_key="role_interview")

    mapping = {
        "research_keys": [{"form_key": "role_interview", "subject_type": "role"}]
    }
    snapshot = build_document_snapshot(db_session, project.id, mapping)

    assert snapshot["project"]["id"] == project.id
    assert snapshot["enterprise"]["name"] == "星河制造"
    assert isinstance(snapshot["tasks"], list)
    assert len(snapshot["tasks"]) == 1
    assert snapshot["tasks"][0]["task_key"] == "diagnose"
    assert isinstance(snapshot["members"], list)
    assert any(member["user_id"] == leader.id for member in snapshot["members"])
    assert snapshot["research"]["role_interview"]["main_problem"] == {
        "text": "排产信息分散"
    }
    assert isinstance(snapshot["captured_at"], str)
