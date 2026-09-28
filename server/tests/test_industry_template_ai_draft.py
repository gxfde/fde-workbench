import pytest
from sqlalchemy import func, select

from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.research.models import TemplateResearchForm
from fde_api.templates.service import (
    TemplateServiceError,
    create_ai_template_draft,
)
from fde_api.workbench.models import IndustryTemplate, ModuleCatalog


def generated_payload():
    forms = []
    for index, subject_type in enumerate(("project", "department", "role", "process", "opportunity"), 1):
        forms.append(
            {
                "form_key": f"{subject_type}_form",
                "name": f"{subject_type} form",
                "description": "",
                "subject_type": subject_type,
                "module_key": "pre_diagnosis",
                "sort_order": index,
                "sections": [
                    {
                        "section_key": "basics",
                        "name": "基础信息",
                        "description": "",
                        "sort_order": 1,
                        "fields": [
                            {
                                "field_key": f"{subject_type}_name",
                                "name": "名称",
                                "help_text": "",
                                "type": "short_text",
                                "is_required": False,
                                "options": {},
                                "sort_order": 1,
                            }
                        ],
                    }
                ],
            }
        )
    return {
        "name": "制造业 AI 模板",
        "industry_name": "制造业",
        "description": "AI 生成",
        "modules": [
            {
                "module_key": "pre_diagnosis",
                "name": "预诊断",
                "description": "",
                "sort_order": 1,
                "tasks": [
                    {
                        "task_key": "collect_info",
                        "name": "收集信息",
                        "description": "",
                        "duration_days": 1,
                        "default_assignee_role": "project_lead",
                        "sort_order": 1,
                        "dependency_keys": [],
                    }
                ],
            }
        ],
        "research_definition": {"forms": forms},
    }


@pytest.fixture
def actor_and_catalog(db_session):
    actor = User(
        username="ai.admin",
        display_name="AI Admin",
        role="admin",
        password_hash=hash_password("InitialPass!234"),
        must_change_password=False,
        is_active=True,
    )
    db_session.add_all(
        [
            actor,
            ModuleCatalog(
                module_key="pre_diagnosis",
                name="预诊断",
                description="",
                sort_order=1,
                is_active=True,
            ),
        ]
    )
    db_session.commit()
    return actor


def test_ai_draft_creates_template_and_five_research_forms(
    app, db_session, actor_and_catalog
):
    dto = create_ai_template_draft(
        actor=actor_and_catalog, generated=generated_payload()
    )

    assert dto["status"] == "draft"
    assert db_session.scalar(select(func.count(IndustryTemplate.id))) == 1
    assert db_session.scalar(select(func.count(TemplateResearchForm.id))) == 5


def test_ai_draft_allows_module_only_template_without_research_forms(
    app, db_session, actor_and_catalog
):
    payload = generated_payload()
    payload["research_definition"] = None

    dto = create_ai_template_draft(actor=actor_and_catalog, generated=payload)

    assert dto["status"] == "draft"
    assert db_session.scalar(select(func.count(IndustryTemplate.id))) == 1
    assert db_session.scalar(select(func.count(TemplateResearchForm.id))) == 0


def test_invalid_research_rolls_back_template(app, db_session, actor_and_catalog):
    payload = generated_payload()
    payload["research_definition"]["forms"][0]["sections"] = "invalid"

    with pytest.raises(TemplateServiceError):
        create_ai_template_draft(actor=actor_and_catalog, generated=payload)

    db_session.expire_all()
    assert db_session.scalar(select(func.count(IndustryTemplate.id))) == 0
