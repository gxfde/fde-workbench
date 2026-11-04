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
        enterprise_code="星河制造·制造·苏州",
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
    # A2 代号化：快照 enterprise 段只携带 enterprise_code，无明文字段
    assert snapshot["enterprise"]["enterprise_code"] == "星河制造·制造·苏州"
    assert isinstance(snapshot["tasks"], list)
    assert len(snapshot["tasks"]) == 1
    assert snapshot["tasks"][0]["task_key"] == "diagnose"
    assert isinstance(snapshot["members"], list)
    assert any(member["user_id"] == leader.id for member in snapshot["members"])
    assert snapshot["research"]["role_interview"]["main_problem"] == {
        "text": "排产信息分散"
    }
    # V3 T-D1（WB-DEF-7）：血缘键随答案冻结，未实例化门禁的快照 gates 为空
    assert isinstance(snapshot["research"]["role_interview"]["revision_id"], str)
    assert snapshot["gates"] == []
    assert isinstance(snapshot["captured_at"], str)


def test_snapshot_research_revision_lineage_points_at_latest_confirmed(db_session):
    """V3 T-D1（WB-DEF-7）：revision_id 必须指向最新 confirmed revision 且可反查。"""
    leader = User(username="snapshot.lead3", password_hash="x", role="project_lead")
    db_session.add(leader)
    db_session.commit()
    project = _build_persisted_project(db_session, code="SNAP-REV-001", leader=leader)

    subject = _add_role_subject(db_session, project, subject_key="planner", name="计划员")
    form = _add_confirmed_role_form(db_session, project, subject, form_key="role_interview")

    # 第二个 confirmed revision（revision_number=2）——快照必须采用它。
    second_revision = ProjectResearchFormRevision(
        form=form,
        revision_number=2,
        status="confirmed",
    )
    db_session.add(second_revision)
    db_session.flush()
    db_session.add(
        ProjectResearchAnswer(
            revision=second_revision,
            field_key="main_problem",
            value_json={"text": "已更新的主要问题"},
        )
    )
    db_session.commit()

    snapshot = build_document_snapshot(
        db_session,
        project.id,
        {"research_keys": [{"form_key": "role_interview", "subject_type": "role"}]},
    )

    values = snapshot["research"]["role_interview"]
    assert values["revision_id"] == second_revision.id
    assert values["main_problem"] == {"text": "已更新的主要问题"}
    # 血缘反查：从快照冻结的 id 找回 revision 行本身。
    backtracked = db_session.get(ProjectResearchFormRevision, values["revision_id"])
    assert backtracked is not None
    assert backtracked.status == "confirmed"
    assert backtracked.revision_number == 2


def test_snapshot_includes_gate_state_summary(db_session):
    """V3 T-D1：gates 摘要冻结生成时刻的门禁状态语义，按 gate_key 排序。"""
    from datetime import UTC, datetime

    from fde_api.workbench.models import Gate

    leader = User(username="snapshot.lead4", password_hash="x", role="project_lead")
    db_session.add(leader)
    db_session.commit()
    project = _build_persisted_project(db_session, code="SNAP-GATE-001", leader=leader)

    decided_at = datetime(2026, 9, 30, 8, 0, tzinfo=UTC)
    db_session.add(
        Gate(
            project_id=project.id,
            gate_key="G8",
            status="passed",
            decision="proceed",
            decided_at=decided_at,
        )
    )
    db_session.add(
        Gate(project_id=project.id, gate_key="G1", status="evidence")
    )
    db_session.commit()

    snapshot = build_document_snapshot(db_session, project.id, {"research_keys": []})

    gates = snapshot["gates"]
    assert [gate["gate_key"] for gate in gates] == ["G1", "G8"]
    assert gates[0] == {
        "gate_key": "G1",
        "status": "evidence",
        "decision": None,
        "submitted_at": None,
        "decided_at": None,
    }
    assert gates[1]["status"] == "passed"
    assert gates[1]["decision"] == "proceed"
    assert gates[1]["decided_at"] == decided_at.isoformat()
    # 摘要不携带清单明细/证据指针——那些属于门禁面，不属于文档快照。
    assert "evidence_checklist" not in gates[1]
    assert "evidence_uri" not in gates[1]
