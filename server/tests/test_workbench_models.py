from datetime import date

import pytest
from sqlalchemy import delete, inspect
from sqlalchemy.exc import DBAPIError, IntegrityError

from fde_api.auth.models import Base, User
from fde_api.workbench.models import (
    IndustryTemplate,
    IndustryTemplateVersion,
    ModuleCatalog,
    Project,
    ProjectModule,
    ProjectTask,
    TemplateModule,
    TemplateTask,
    TemplateTaskDependency,
)


def _create_published_template_tree(db_session):
    publisher = User(username="template.publisher", password_hash="x", role="admin")
    catalog = ModuleCatalog(module_key="published_pov", name="已发布 PoV", sort_order=30)
    template = IndustryTemplate(name="已发布模板", industry_name="通用")
    version = IndustryTemplateVersion(
        template=template,
        name=template.name,
        industry_name=template.industry_name,
        description=template.description,
        version_number=1,
        status="published",
        published_by=publisher,
    )
    template_module = TemplateModule(
        template_version=version,
        module_catalog=catalog,
        name="PoV",
    )
    predecessor = TemplateTask(
        template_module=template_module,
        task_key="prepare",
        name="准备",
        duration_days=1,
        default_assignee_role="fde_engineer",
        sort_order=10,
    )
    successor = TemplateTask(
        template_module=template_module,
        task_key="validate",
        name="验证",
        duration_days=1,
        default_assignee_role="project_lead",
        sort_order=20,
    )
    dependency = TemplateTaskDependency(
        predecessor_task=predecessor,
        successor_task=successor,
    )
    db_session.add(dependency)
    db_session.commit()
    return version, template_module, predecessor, successor, dependency


def test_workbench_models_share_auth_metadata():
    expected_tables = {
        "module_catalog",
        "industry_templates",
        "industry_template_versions",
        "template_modules",
        "template_tasks",
        "template_task_dependencies",
        "projects",
        "project_members",
        "project_modules",
        "project_tasks",
        "project_task_collaborators",
        "project_task_dependencies",
        "operation_events",
    }

    assert expected_tables <= set(Base.metadata.tables)
    assert ModuleCatalog.metadata is Base.metadata


def test_project_module_is_unique_per_project(db_session):
    leader = User(username="project.lead", password_hash="x", role="project_lead")
    module = ModuleCatalog(module_key="pov", name="PoV", sort_order=10)
    template = IndustryTemplate(name="通用模板", industry_name="通用")
    version = IndustryTemplateVersion(
        template=template,
        name=template.name,
        industry_name=template.industry_name,
        description=template.description,
        version_number=1,
        status="published",
        published_by=leader,
    )
    project = Project(
        project_code="FDE-20260821-001",
        name="星河 PoV",
        enterprise_name="星河制造",
        leader=leader,
        source_template_version=version,
        template_snapshot={"version": 1},
        planned_start_date=date(2026, 8, 21),
    )
    db_session.add_all([project, module])
    db_session.flush()
    db_session.add_all(
        [
            ProjectModule(
                project_id=project.id,
                module_catalog_id=module.id,
                name="PoV",
            ),
            ProjectModule(
                project_id=project.id,
                module_catalog_id=module.id,
                name="PoV",
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_database_exposes_required_workbench_indexes(db_session):
    database = inspect(db_session.bind)

    assert {index["name"] for index in database.get_indexes("projects")} >= {
        "ix_projects_status",
        "ix_projects_leader_user_id",
        "ix_projects_planned_dates",
    }
    assert {index["name"] for index in database.get_indexes("project_members")} >= {
        "ix_project_members_user_id"
    }
    assert {index["name"] for index in database.get_indexes("project_tasks")} >= {
        "ix_project_tasks_assignee_user_id",
        "ix_project_tasks_planned_dates",
    }
    assert {index["name"] for index in database.get_indexes("project_modules")} >= {
        "ix_project_modules_planned_dates"
    }


def test_database_rejects_deleting_published_template_tree(db_session):
    version, template_module, predecessor, successor, dependency = (
        _create_published_template_tree(db_session)
    )
    ids = {
        IndustryTemplateVersion: version.id,
        TemplateModule: template_module.id,
        TemplateTaskDependency: dependency.id,
    }
    task_ids = {predecessor.id, successor.id}

    with pytest.raises(IntegrityError):
        db_session.execute(
            delete(IndustryTemplateVersion).where(
                IndustryTemplateVersion.id == version.id
            )
        )
        db_session.commit()
    db_session.rollback()

    assert all(
        db_session.get(model, entity_id) is not None
        for model, entity_id in ids.items()
    )
    assert {
        task.id
        for task in db_session.query(TemplateTask)
        .filter(TemplateTask.id.in_(task_ids))
        .all()
    } == task_ids


def test_removing_published_module_from_relationship_preserves_history(db_session):
    version, template_module, predecessor, successor, dependency = (
        _create_published_template_tree(db_session)
    )
    version.modules.remove(template_module)

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    assert db_session.get(IndustryTemplateVersion, version.id) is not None
    assert db_session.get(TemplateModule, template_module.id) is not None
    assert db_session.get(TemplateTask, predecessor.id) is not None
    assert db_session.get(TemplateTask, successor.id) is not None
    assert db_session.get(TemplateTaskDependency, dependency.id) is not None


def test_database_rejects_invalid_project_status(db_session):
    leader = User(username="invalid.project", password_hash="x", role="project_lead")
    template = IndustryTemplate(name="行业模板", industry_name="制造")
    version = IndustryTemplateVersion(
        template=template,
        name=template.name,
        industry_name=template.industry_name,
        description=template.description,
        version_number=1,
        status="published",
        published_by=leader,
    )
    project = Project(
        project_code="FDE-20260821-002",
        name="非法状态项目",
        enterprise_name="星河制造",
        leader=leader,
        source_template_version=version,
        template_snapshot={},
        planned_start_date=date(2026, 8, 21),
        status="unknown",
    )
    db_session.add(project)

    with pytest.raises(DBAPIError):
        db_session.commit()


def test_database_rejects_invalid_project_task_default_role(db_session):
    leader = User(username="invalid.task", password_hash="x", role="project_lead")
    catalog = ModuleCatalog(module_key="diagnosis", name="诊断", sort_order=20)
    template = IndustryTemplate(name="制造模板", industry_name="制造")
    version = IndustryTemplateVersion(
        template=template,
        name=template.name,
        industry_name=template.industry_name,
        description=template.description,
        version_number=1,
        status="published",
        published_by=leader,
    )
    project = Project(
        project_code="FDE-20260821-003",
        name="角色校验项目",
        enterprise_name="星河制造",
        leader=leader,
        source_template_version=version,
        template_snapshot={},
        planned_start_date=date(2026, 8, 21),
    )
    project_module = ProjectModule(
        project=project,
        module_catalog=catalog,
        name="诊断",
    )
    task = ProjectTask(
        project_module=project_module,
        task_key="interview",
        name="访谈",
        duration_days=1,
        planned_start_date=date(2026, 8, 21),
        planned_end_date=date(2026, 8, 21),
        default_assignee_role="unknown",
    )
    db_session.add(task)

    with pytest.raises(DBAPIError):
        db_session.commit()
