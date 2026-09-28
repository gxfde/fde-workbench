import pytest
from sqlalchemy import func, inspect, select
from sqlalchemy.exc import IntegrityError

from fde_api.workbench.models import (
    IndustryTemplate,
    IndustryTemplateVersion,
    ModuleCatalog,
    TemplateModule,
    TemplateTask,
    TemplateTaskDependency,
)
from fde_api.workbench.seed import (
    BASE_MODULES,
    GENERIC_TEMPLATE_NAME,
    WorkbenchSeedError,
    seed_workbench,
)


def test_seed_workbench_is_idempotent(db_session):
    """Creating seed rows on every run would duplicate the base catalog."""
    seed_workbench(db_session)
    seed_workbench(db_session)

    assert [
        module.module_key
        for module in db_session.scalars(
            select(ModuleCatalog).order_by(ModuleCatalog.sort_order, ModuleCatalog.id)
        )
    ] == [
        "pre_diagnosis",
        "diagnosis",
        "pov",
        "production_deployment",
        "training_handover",
    ]


def test_seed_workbench_cli_is_idempotent_and_prints_counts_only(app, db_session):
    """Changing CLI output to record details could expose internal seed data."""
    runner = app.test_cli_runner()

    first = runner.invoke(args=["seed-workbench"])
    second = runner.invoke(args=["seed-workbench"])

    assert first.exit_code == 0
    assert second.exit_code == 0
    assert first.output.strip() == "modules_created=5"
    assert second.output.strip() == "modules_created=0"
    db_session.expire_all()
    assert db_session.scalar(select(func.count()).select_from(ModuleCatalog)) == 5


def test_seed_workbench_creates_exact_published_generic_template_once(db_session):
    """A duplicate or drifted seed would make project creation nondeterministic."""
    seed_workbench(db_session)
    db_session.commit()
    seed_workbench(db_session)
    db_session.commit()
    db_session.expire_all()

    templates = db_session.scalars(select(IndustryTemplate)).all()
    versions = db_session.scalars(select(IndustryTemplateVersion)).all()
    modules = db_session.scalars(
        select(TemplateModule).order_by(TemplateModule.sort_order)
    ).all()
    tasks = db_session.scalars(
        select(TemplateTask)
        .join(TemplateModule)
        .order_by(TemplateModule.sort_order, TemplateTask.sort_order)
    ).all()
    dependencies = db_session.scalars(select(TemplateTaskDependency)).all()

    assert len(templates) == 1
    assert templates[0].name == "通用企业 AI 落地模板"
    assert templates[0].industry_name == "通用"
    assert templates[0].status == "active"
    assert templates[0].latest_published_version_number == 1
    assert len(versions) == 1
    assert versions[0].template_id == templates[0].id
    assert versions[0].version_number == 1
    assert versions[0].status == "published"
    assert versions[0].published_at is not None
    assert [module.module_catalog.module_key for module in modules] == [
        "pre_diagnosis",
        "diagnosis",
        "pov",
        "production_deployment",
        "training_handover",
    ]
    assert [
        (
            task.template_module.module_catalog.module_key,
            task.task_key,
            task.name,
            task.duration_days,
            task.default_assignee_role,
        )
        for task in tasks
    ] == [
        ("pre_diagnosis", "collect_enterprise_info", "收集企业基础信息", 2, "project_lead"),
        (
            "pre_diagnosis",
            "confirm_business_scope",
            "明确业务目标与范围",
            1,
            "project_lead",
        ),
        ("pre_diagnosis", "deliver_pre_diagnosis", "形成预调研结论", 2, "project_lead"),
        ("diagnosis", "interview_department_leads", "访谈部门负责人", 3, "project_lead"),
        ("diagnosis", "map_roles_and_processes", "梳理岗位与流程", 3, "fde_engineer"),
        ("diagnosis", "identify_ai_scenarios", "识别 AI 机会场景", 2, "project_lead"),
        ("diagnosis", "deliver_diagnosis_report", "输出调研报告", 2, "project_lead"),
        ("pov", "confirm_pov_acceptance", "确认 PoV 场景与验收标准", 2, "project_lead"),
        ("pov", "prepare_pov_data", "准备数据与验证环境", 3, "fde_engineer"),
        ("pov", "build_pov", "开发 PoV 方案", 5, "fde_engineer"),
        ("pov", "validate_pov", "用户验证与复盘", 2, "project_lead"),
        ("pov", "deliver_pov_conclusion", "输出 PoV 结论", 1, "project_lead"),
        (
            "production_deployment",
            "confirm_production_architecture",
            "确认生产架构与安全方案",
            3,
            "project_lead",
        ),
        (
            "production_deployment",
            "integrate_production_system",
            "完成生产系统集成",
            5,
            "fde_engineer",
        ),
        (
            "production_deployment",
            "test_release_readiness",
            "完成测试与上线准备",
            3,
            "fde_engineer",
        ),
        ("production_deployment", "release_production", "完成生产发布", 1, "project_lead"),
        (
            "production_deployment",
            "observe_stable_operation",
            "稳定运行观察",
            5,
            "fde_engineer",
        ),
        ("training_handover", "write_operation_manual", "编写操作手册", 2, "fde_engineer"),
        ("training_handover", "train_administrators", "开展管理员培训", 1, "project_lead"),
        ("training_handover", "train_end_users", "开展使用者培训", 1, "fde_engineer"),
        ("training_handover", "accept_and_handover", "完成验收与移交", 2, "project_lead"),
    ]
    assert {
        (dependency.predecessor_task.task_key, dependency.successor_task.task_key)
        for dependency in dependencies
    } == {
        ("collect_enterprise_info", "confirm_business_scope"),
        ("confirm_business_scope", "deliver_pre_diagnosis"),
        ("interview_department_leads", "map_roles_and_processes"),
        ("map_roles_and_processes", "identify_ai_scenarios"),
        ("identify_ai_scenarios", "deliver_diagnosis_report"),
        ("confirm_pov_acceptance", "prepare_pov_data"),
        ("prepare_pov_data", "build_pov"),
        ("build_pov", "validate_pov"),
        ("validate_pov", "deliver_pov_conclusion"),
        ("confirm_production_architecture", "integrate_production_system"),
        ("integrate_production_system", "test_release_readiness"),
        ("test_release_readiness", "release_production"),
        ("release_production", "observe_stable_operation"),
        ("write_operation_manual", "train_administrators"),
        ("write_operation_manual", "train_end_users"),
        ("train_administrators", "accept_and_handover"),
        ("train_end_users", "accept_and_handover"),
    }
    assert len(dependencies) == 17


def test_seed_rejects_an_inactive_required_module(db_session):
    """Bypassing publication validation would seed a published unusable template."""
    db_session.add_all(
        [
            ModuleCatalog(
                module_key=module["key"],
                name=module["name"],
                description=module["description"],
                sort_order=module["sort_order"],
                is_active=module["key"] != "pov",
            )
            for module in BASE_MODULES
        ]
    )
    db_session.commit()

    with pytest.raises(RuntimeError, match="inactive"):
        seed_workbench(db_session)

    assert db_session.scalars(select(IndustryTemplate)).all() == []


def test_seed_rejects_drift_in_an_existing_generic_template(db_session):
    """Silently accepting same-identity drift would make the seed contract unverifiable."""
    seed_workbench(db_session)
    db_session.commit()
    task = db_session.scalar(
        select(TemplateTask).where(TemplateTask.task_key == "build_pov")
    )
    task.duration_days = 4
    db_session.commit()

    with pytest.raises(RuntimeError, match="drift"):
        seed_workbench(db_session)


def test_seed_rejects_a_cross_module_duplicate_task_key(db_session):
    """A dict must not hide the 22nd task when its key duplicates another module."""
    seed_workbench(db_session)
    db_session.commit()
    deployment_module = db_session.scalar(
        select(TemplateModule)
        .join(ModuleCatalog)
        .where(ModuleCatalog.module_key == "production_deployment")
    )
    db_session.add(
        TemplateTask(
            id="00000000-0000-0000-0000-000000000000",
            template_module=deployment_module,
            task_key="collect_enterprise_info",
            name="收集企业基础信息",
            description="",
            duration_days=2,
            default_assignee_role="project_lead",
            sort_order=10,
        )
    )
    db_session.commit()

    with pytest.raises(WorkbenchSeedError, match="task"):
        seed_workbench(db_session)


def test_seed_rejects_matching_root_and_version_description_drift(db_session):
    """Comparing root to version alone would accept coordinated metadata drift."""
    seed_workbench(db_session)
    db_session.commit()
    template = db_session.scalars(select(IndustryTemplate)).one()
    version = db_session.scalars(select(IndustryTemplateVersion)).one()
    template.description = "same drift"
    version.description = "same drift"
    db_session.commit()

    with pytest.raises(RuntimeError, match="drift"):
        seed_workbench(db_session)


def test_seed_rejects_same_name_with_a_different_stable_identity(db_session):
    """A same-name root with another key must not be mistaken for the canonical seed."""
    db_session.add_all(
        [
            ModuleCatalog(
                module_key=module["key"],
                name=module["name"],
                description=module["description"],
                sort_order=module["sort_order"],
                is_active=True,
            )
            for module in BASE_MODULES
        ]
    )
    conflicting = IndustryTemplate(
        template_key="another_identity",
        name=GENERIC_TEMPLATE_NAME,
        industry_name="通用",
        description="conflict",
        status="active",
    )
    db_session.add(conflicting)
    db_session.commit()

    with pytest.raises(RuntimeError, match="drift"):
        seed_workbench(db_session)


def test_template_seed_identity_has_a_database_unique_constraint(db_session):
    """Application-only name checks cannot prevent concurrent duplicate seed roots."""
    database = inspect(db_session.bind)

    assert "template_key" in {
        column["name"] for column in database.get_columns("industry_templates")
    }
    unique_column_sets = {
        tuple(constraint["column_names"])
        for constraint in database.get_unique_constraints("industry_templates")
    }
    assert ("template_key",) in unique_column_sets


def test_database_rejects_concurrent_duplicate_template_seed_identity(db_session):
    """The fixed seed key is the final arbiter when two seeders race."""
    db_session.add_all(
        [
            IndustryTemplate(
                template_key="generic_enterprise_ai",
                name=f"candidate {index}",
                industry_name="通用",
                description="",
            )
            for index in range(2)
        ]
    )

    with pytest.raises(IntegrityError):
        db_session.commit()

    db_session.rollback()
