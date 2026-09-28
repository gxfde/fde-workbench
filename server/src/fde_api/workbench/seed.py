from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from fde_api.workbench.models import (
    IndustryTemplate,
    IndustryTemplateVersion,
    ModuleCatalog,
    TemplateModule,
    TemplateTask,
    TemplateTaskDependency,
)


BASE_MODULES = (
    {
        "key": "pre_diagnosis",
        "name": "预调研",
        "description": "澄清业务目标、范围和现状。",
        "sort_order": 10,
    },
    {
        "key": "diagnosis",
        "name": "调研",
        "description": "完成业务流程与技术条件调研。",
        "sort_order": 20,
    },
    {
        "key": "pov",
        "name": "PoV 验证",
        "description": "验证优先场景的可行性和价值。",
        "sort_order": 30,
    },
    {
        "key": "production_deployment",
        "name": "生产部署",
        "description": "完成生产环境部署与验收。",
        "sort_order": 40,
    },
    {
        "key": "training_handover",
        "name": "培训与交接",
        "description": "完成使用培训、运行交接和复盘。",
        "sort_order": 50,
    },
)


GENERIC_TEMPLATE_NAME = "通用企业 AI 落地模板"
GENERIC_TEMPLATE_KEY = "generic_enterprise_ai"
GENERIC_TEMPLATE_DESCRIPTION = (
    "覆盖预调研、正式调研、PoV、生产部署与培训移交的"
    "通用企业 AI 落地流程。"
)
GENERIC_TEMPLATE_TASKS = {
    "pre_diagnosis": [
        ("collect_enterprise_info", "收集企业基础信息", 2, "project_lead", ()),
        (
            "confirm_business_scope",
            "明确业务目标与范围",
            1,
            "project_lead",
            ("collect_enterprise_info",),
        ),
        (
            "deliver_pre_diagnosis",
            "形成预调研结论",
            2,
            "project_lead",
            ("confirm_business_scope",),
        ),
    ],
    "diagnosis": [
        ("interview_department_leads", "访谈部门负责人", 3, "project_lead", ()),
        (
            "map_roles_and_processes",
            "梳理岗位与流程",
            3,
            "fde_engineer",
            ("interview_department_leads",),
        ),
        (
            "identify_ai_scenarios",
            "识别 AI 机会场景",
            2,
            "project_lead",
            ("map_roles_and_processes",),
        ),
        (
            "deliver_diagnosis_report",
            "输出调研报告",
            2,
            "project_lead",
            ("identify_ai_scenarios",),
        ),
    ],
    "pov": [
        ("confirm_pov_acceptance", "确认 PoV 场景与验收标准", 2, "project_lead", ()),
        (
            "prepare_pov_data",
            "准备数据与验证环境",
            3,
            "fde_engineer",
            ("confirm_pov_acceptance",),
        ),
        ("build_pov", "开发 PoV 方案", 5, "fde_engineer", ("prepare_pov_data",)),
        ("validate_pov", "用户验证与复盘", 2, "project_lead", ("build_pov",)),
        (
            "deliver_pov_conclusion",
            "输出 PoV 结论",
            1,
            "project_lead",
            ("validate_pov",),
        ),
    ],
    "production_deployment": [
        (
            "confirm_production_architecture",
            "确认生产架构与安全方案",
            3,
            "project_lead",
            (),
        ),
        (
            "integrate_production_system",
            "完成生产系统集成",
            5,
            "fde_engineer",
            ("confirm_production_architecture",),
        ),
        (
            "test_release_readiness",
            "完成测试与上线准备",
            3,
            "fde_engineer",
            ("integrate_production_system",),
        ),
        (
            "release_production",
            "完成生产发布",
            1,
            "project_lead",
            ("test_release_readiness",),
        ),
        (
            "observe_stable_operation",
            "稳定运行观察",
            5,
            "fde_engineer",
            ("release_production",),
        ),
    ],
    "training_handover": [
        ("write_operation_manual", "编写操作手册", 2, "fde_engineer", ()),
        (
            "train_administrators",
            "开展管理员培训",
            1,
            "project_lead",
            ("write_operation_manual",),
        ),
        (
            "train_end_users",
            "开展使用者培训",
            1,
            "fde_engineer",
            ("write_operation_manual",),
        ),
        (
            "accept_and_handover",
            "完成验收与移交",
            2,
            "project_lead",
            ("train_administrators", "train_end_users"),
        ),
    ],
}


class WorkbenchSeedError(RuntimeError):
    pass


def seed_workbench(session: Session) -> None:
    """Add or refresh the base catalog and generic published template per database."""
    catalogs = {
        module.module_key: module
        for module in session.scalars(select(ModuleCatalog))
    }
    for module in BASE_MODULES:
        existing = catalogs.get(module["key"])
        if existing is None:
            existing = ModuleCatalog(
                module_key=module["key"],
                name=module["name"],
                description=module["description"],
                sort_order=module["sort_order"],
                is_active=True,
            )
            session.add(existing)
            catalogs[module["key"]] = existing
        else:
            existing.name = module["name"]
            existing.description = module["description"]
            existing.sort_order = module["sort_order"]
    session.flush()
    if set(catalogs) != set(GENERIC_TEMPLATE_TASKS):
        raise WorkbenchSeedError("generic template drift: required module missing")
    if any(not module.is_active for module in catalogs.values()):
        raise WorkbenchSeedError("required module inactive")

    existing_template = session.scalar(
        select(IndustryTemplate).where(
            IndustryTemplate.template_key == GENERIC_TEMPLATE_KEY
        )
    )
    same_name_template = session.scalar(
        select(IndustryTemplate)
        .where(
            IndustryTemplate.name == GENERIC_TEMPLATE_NAME,
            IndustryTemplate.industry_name == "通用",
            IndustryTemplate.template_key != GENERIC_TEMPLATE_KEY,
        )
        .limit(1)
    )
    if same_name_template is not None:
        raise WorkbenchSeedError("generic template drift: conflicting stable identity")
    if existing_template is not None:
        _sync_generic_template_names(session, existing_template, catalogs)
        _validate_generic_template(session, existing_template, catalogs)
        return

    template = IndustryTemplate(
        template_key=GENERIC_TEMPLATE_KEY,
        name=GENERIC_TEMPLATE_NAME,
        industry_name="通用",
        description=GENERIC_TEMPLATE_DESCRIPTION,
        status="active",
        latest_published_version_number=1,
    )
    version = IndustryTemplateVersion(
        template=template,
        name=GENERIC_TEMPLATE_NAME,
        industry_name="通用",
        description=template.description,
        version_number=1,
        status="published",
        published_at=datetime.now(UTC),
    )
    session.add(version)
    session.flush()

    tasks_by_key: dict[str, TemplateTask] = {}
    dependency_edges: list[tuple[str, str]] = []
    for module_definition in BASE_MODULES:
        module_key = module_definition["key"]
        template_module = TemplateModule(
            template_version_id=version.id,
            module_catalog_id=catalogs[module_key].id,
            name=module_definition["name"],
            description=module_definition["description"],
            sort_order=module_definition["sort_order"],
        )
        session.add(template_module)
        session.flush()
        for task_order, (
            task_key,
            task_name,
            duration_days,
            default_role,
            dependency_keys,
        ) in enumerate(GENERIC_TEMPLATE_TASKS[module_key], start=1):
            task = TemplateTask(
                template_module_id=template_module.id,
                task_key=task_key,
                name=task_name,
                description="",
                duration_days=duration_days,
                default_assignee_role=default_role,
                sort_order=task_order * 10,
            )
            session.add(task)
            session.flush()
            tasks_by_key[task_key] = task
            dependency_edges.extend(
                (dependency_key, task_key) for dependency_key in dependency_keys
            )

    session.add_all(
        [
            TemplateTaskDependency(
                predecessor_task_id=tasks_by_key[predecessor_key].id,
                successor_task_id=tasks_by_key[successor_key].id,
            )
            for predecessor_key, successor_key in dependency_edges
        ]
    )


_DIAGNOSTIC_RENAMES = (
    ("前期诊断", "预调研"),
    ("预诊断", "预调研"),
    ("正式诊断", "正式调研"),
    ("诊断报告", "调研报告"),
    ("诊断", "调研"),
)


def _rename_diagnostic_text(value: str) -> str:
    for legacy, current in _DIAGNOSTIC_RENAMES:
        value = value.replace(legacy, current)
    return value


def _sync_generic_template_names(
    session: Session, template: IndustryTemplate, catalogs: dict[str, ModuleCatalog]
) -> None:
    """Refresh legacy display names on an already-seeded generic template.

    Only the specific legacy → current renames (前期诊断/预诊断 → 预调研,
    诊断 → 调研) are applied, so genuine corruption is still detected by the
    drift validation while existing databases catch up on the rename.
    """
    template.name = _rename_diagnostic_text(template.name)
    template.description = _rename_diagnostic_text(template.description)
    versions = list(
        session.scalars(
            select(IndustryTemplateVersion).where(
                IndustryTemplateVersion.template_id == template.id
            )
        )
    )
    for version in versions:
        version.name = _rename_diagnostic_text(version.name)
        version.description = _rename_diagnostic_text(version.description)
    for module in session.scalars(
        select(TemplateModule).where(
            TemplateModule.template_version_id.in_([version.id for version in versions])
        )
    ):
        module.name = _rename_diagnostic_text(module.name)
        module.description = _rename_diagnostic_text(module.description)
    for task in session.scalars(
        select(TemplateTask)
        .join(TemplateModule)
        .where(TemplateModule.template_version_id.in_([version.id for version in versions]))
    ):
        task.name = _rename_diagnostic_text(task.name)
        task.description = _rename_diagnostic_text(task.description)


def _validate_generic_template(
    session: Session,
    template: IndustryTemplate,
    catalogs: dict[str, ModuleCatalog],
) -> None:
    versions = list(
        session.scalars(
            select(IndustryTemplateVersion).where(
                IndustryTemplateVersion.template_id == template.id
            )
        )
    )
    if (
        template.status != "active"
        or template.latest_published_version_number != 1
        or template.name != GENERIC_TEMPLATE_NAME
        or template.industry_name != "通用"
        or template.description != GENERIC_TEMPLATE_DESCRIPTION
        or len(versions) != 1
    ):
        raise WorkbenchSeedError("generic template drift: root or version count")
    version = versions[0]
    if (
        version.version_number != 1
        or version.status != "published"
        or version.name != GENERIC_TEMPLATE_NAME
        or version.industry_name != "通用"
        or version.description != GENERIC_TEMPLATE_DESCRIPTION
        or version.published_at is None
    ):
        raise WorkbenchSeedError("generic template drift: published v1 metadata")

    modules = list(
        session.scalars(
            select(TemplateModule)
            .where(TemplateModule.template_version_id == version.id)
            .order_by(TemplateModule.sort_order)
        )
    )
    expected_modules = {module["key"]: module for module in BASE_MODULES}
    actual_module_keys = [module.module_catalog.module_key for module in modules]
    if actual_module_keys != [module["key"] for module in BASE_MODULES]:
        raise WorkbenchSeedError("generic template drift: module set")
    for module in modules:
        expected = expected_modules[module.module_catalog.module_key]
        if (
            module.module_catalog_id != catalogs[expected["key"]].id
            or module.name != expected["name"]
            or module.description != expected["description"]
            or module.sort_order != expected["sort_order"]
        ):
            raise WorkbenchSeedError("generic template drift: module definition")

    tasks = list(
        session.scalars(
            select(TemplateTask)
            .join(TemplateModule)
            .where(TemplateModule.template_version_id == version.id)
        )
    )
    task_keys = [task.task_key for task in tasks]
    if len(tasks) != 21 or len(set(task_keys)) != 21:
        raise WorkbenchSeedError(
            "generic template drift: expected 21 globally unique task keys"
        )
    actual_tasks = {
        task.task_key: (
            task.template_module.module_catalog.module_key,
            task.name,
            task.duration_days,
            task.default_assignee_role,
            task.sort_order,
            task.description,
        )
        for task in tasks
    }
    expected_tasks = {
        task_key: (module_key, name, duration, role, index * 10, "")
        for module_key, definitions in GENERIC_TEMPLATE_TASKS.items()
        for index, (task_key, name, duration, role, _) in enumerate(
            definitions, start=1
        )
    }
    if actual_tasks != expected_tasks:
        raise WorkbenchSeedError("generic template drift: task definition")

    dependencies = list(
        session.scalars(
            select(TemplateTaskDependency)
            .join(
                TemplateTask,
                TemplateTaskDependency.successor_task_id == TemplateTask.id,
            )
            .join(TemplateModule, TemplateTask.template_module_id == TemplateModule.id)
            .where(TemplateModule.template_version_id == version.id)
        )
    )
    actual_edges = {
        (edge.predecessor_task.task_key, edge.successor_task.task_key)
        for edge in dependencies
    }
    expected_edges = {
        (dependency_key, task_key)
        for definitions in GENERIC_TEMPLATE_TASKS.values()
        for task_key, _, _, _, dependency_keys in definitions
        for dependency_key in dependency_keys
    }
    if actual_edges != expected_edges:
        raise WorkbenchSeedError("generic template drift: dependency graph")
