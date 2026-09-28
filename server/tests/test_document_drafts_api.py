from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import select

from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from fde_api.documents.models import (
    DocumentGenerationJob,
    DocumentTemplate,
    DocumentTemplateVersion,
    ProjectDocument,
    ProjectDocumentVersion,
)
from fde_api.research.models import ProjectAIOpportunityProfile, ProjectResearchSubject
from fde_api.jobs.models import OutboxEvent
from fde_api.workbench.models import IndustryTemplate, IndustryTemplateVersion, Project, ProjectMember

INITIAL_PASSWORD = "InitialPass!234"


@dataclass(frozen=True)
class AuthorizedClient:
    client: object
    user: User
    headers: dict[str, str]

    def get(self, *args, **kwargs):
        return self.client.get(*args, headers=self.headers, **kwargs)

    def post(self, *args, **kwargs):
        return self.client.post(*args, headers=self.headers, **kwargs)

    def patch(self, *args, **kwargs):
        return self.client.patch(*args, headers=self.headers, **kwargs)


@pytest.fixture
def authorized_client_factory(client, db_session, settings):
    def create(role: str) -> AuthorizedClient:
        user = User(
            username=f"{role}.{uuid4().hex}",
            display_name=role,
            role=role,
            password_hash=hash_password(INITIAL_PASSWORD),
            must_change_password=False,
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()
        return AuthorizedClient(
            client,
            user,
            {"Authorization": f"Bearer {issue_access_token(user, settings)}"},
        )

    return create


@pytest.fixture
def leader_client(authorized_client_factory):
    return authorized_client_factory("project_lead")


@pytest.fixture
def viewer_client(authorized_client_factory):
    return authorized_client_factory("viewer")


@pytest.fixture
def engineer_client(authorized_client_factory):
    return authorized_client_factory("fde_engineer")


@pytest.fixture
def outsider_client(authorized_client_factory):
    return authorized_client_factory("fde_engineer")


def _persist_project(db_session, leader, *, code: str):
    industry_template = IndustryTemplate(name="文档模板", industry_name="制造")
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
        name="文档项目",
        enterprise_name="星河制造",
        leader=leader,
        source_template_version=template_version,
        template_snapshot={},
        research_snapshot={},
        planned_start_date=date(2026, 8, 22),
    )
    db_session.add(project)
    db_session.flush()
    db_session.commit()
    return project


def _add_viewer_member(db_session, project, user):
    db_session.rollback()
    db_session.add(ProjectMember(project_id=project.id, user_id=user.id, role="viewer"))
    db_session.commit()


def _persist_doc_template(db_session, leader, *, document_type="sow"):
    template = DocumentTemplate(
        document_type=document_type,
        name=f"{document_type} 模板",
        description="",
        industry_name="制造",
    )
    db_session.add(template)
    db_session.flush()
    template_version = DocumentTemplateVersion(
        template=template,
        version_number=1,
        status="published",
        mapping_json={
            "document_type": document_type,
            "name": f"{document_type} 模板",
            "modules": ["pre_diagnosis"],
            "field_map": {},
            "research_keys": [],
        },
        sections_json={"sections": []},
        table_loops_json={},
        required_data_json={},
        source_sha256="",
        created_by=leader,
    )
    db_session.add(template_version)
    db_session.commit()
    return template, template_version


def assert_error(response, status: int, code: str) -> None:
    assert response.status_code == status, response.get_data(as_text=True)
    assert response.json["data"] is None
    assert response.json["error"]["code"] == code


def test_create_document_requires_project_manager(
    db_session, leader_client, viewer_client, outsider_client
):
    leader = leader_client.user
    project = _persist_project(db_session, leader, code="DOC-ROLE-001")
    _, template_version = _persist_doc_template(db_session, leader)
    _add_viewer_member(db_session, project, viewer_client.user)

    url = f"/api/v1/projects/{project.id}/documents"

    view_response = viewer_client.post(
        url,
        json={
            "document_type": "sow",
            "template_version_id": template_version.id,
            "expected_version": 1,
        },
    )
    assert_error(view_response, 403, "forbidden")

    outsider_response = outsider_client.post(
        url,
        json={
            "document_type": "sow",
            "template_version_id": template_version.id,
            "expected_version": 1,
        },
    )
    assert_error(outsider_response, 403, "forbidden")

    lead_response = leader_client.post(
        url,
        json={
            "document_type": "sow",
            "template_version_id": template_version.id,
            "expected_version": 1,
        },
    )
    assert lead_response.status_code == 201, lead_response.get_data(as_text=True)
    assert lead_response.json["data"]["status"] == "draft"
    assert lead_response.json["data"]["document_type"] == "sow"
    assert lead_response.json["data"]["project_version"] == 2


def test_create_document_generates_business_code(
    db_session, leader_client
):
    leader = leader_client.user
    project = _persist_project(db_session, leader, code="DOC-CODE-001")
    _, template_version = _persist_doc_template(db_session, leader)
    url = f"/api/v1/projects/{project.id}/documents"

    first = leader_client.post(
        url,
        json={
            "document_type": "sow",
            "template_version_id": template_version.id,
            "expected_version": 1,
        },
    )
    assert first.status_code == 201, first.get_data(as_text=True)
    first_code = first.json["data"]["business_code"]
    first_project_version = first.json["data"]["project_version"]

    second = leader_client.post(
        url,
        json={
            "document_type": "sow",
            "template_version_id": template_version.id,
            "expected_version": first_project_version,
        },
    )
    assert second.status_code == 201, second.get_data(as_text=True)
    second_code = second.json["data"]["business_code"]

    assert first_code == "SOW-1"
    assert second_code == "SOW-2"


def test_project_plan_export_reuses_document_identity(db_session, leader_client):
    project = _persist_project(db_session, leader_client.user, code="DOC-PLAN-001")
    _persist_doc_template(db_session, leader_client.user, document_type="project_plan_progress")
    url = f"/api/v1/projects/{project.id}/documents"

    first = leader_client.post(url, json={"document_type": "project_plan_progress", "expected_version": 1})
    assert first.status_code == 201, first.get_data(as_text=True)
    second = leader_client.post(url, json={
        "document_type": "project_plan_progress",
        "expected_version": first.json["data"]["project_version"],
    })

    assert second.status_code == 201, second.get_data(as_text=True)
    assert second.json["data"]["id"] == first.json["data"]["id"]
    assert second.json["data"]["business_code"] == "项目计划及进度-文档项目"
    assert second.json["data"]["reused"] is True


def test_create_pov_draft_from_opportunity_reuses_document_for_version_history(
    db_session, leader_client
):
    """Losing the source snapshot would make generated delivery drafts untraceable to research."""
    leader = leader_client.user
    project = _persist_project(db_session, leader, code="DOC-OPP-001")
    _, template_version = _persist_doc_template(
        db_session, leader, document_type="pov_plan"
    )
    opportunity = ProjectResearchSubject(
        project_id=project.id,
        subject_type="opportunity",
        subject_key="support_copilot",
        name="客服知识助手",
        description="缩短新人独立接线时间",
        status="active",
        tracking_code="OPP-0001",
    )
    opportunity.opportunity_profile = ProjectAIOpportunityProfile(opportunity_status="ready")
    db_session.add(opportunity)
    db_session.commit()
    url = f"/api/v1/projects/{project.id}/documents"

    first = leader_client.post(
        url,
        json={
            "document_type": "pov_plan",
            "expected_version": 1,
            "business_category": "PoV验证",
            "source_opportunity_id": opportunity.id,
        },
    )

    assert first.status_code == 201, first.get_data(as_text=True)
    first_data = first.json["data"]
    assert first_data["status"] == "draft"
    assert first_data["source_opportunity_id"] == opportunity.id
    assert first_data["current_version"] is None
    assert first_data["business_code"] == "PoV-客服知识助手"
    assert first_data["draft"]["field_overrides"]["opportunity_name"] == "客服知识助手"
    assert first_data["draft"]["field_overrides"]["opportunity_description"] == "缩短新人独立接线时间"
    db_session.refresh(opportunity.opportunity_profile)
    assert opportunity.opportunity_profile.opportunity_status == "converted"

    second = leader_client.post(
        url,
        json={
            "document_type": "pov_plan",
            "template_version_id": template_version.id,
            "expected_version": first_data["project_version"],
            "source_opportunity_id": opportunity.id,
        },
    )
    assert second.status_code == 201, second.get_data(as_text=True)
    second_data = second.json["data"]
    assert second_data["id"] == first_data["id"]
    assert second_data["business_code"] == first_data["business_code"]
    assert second_data["reused"] is True


def test_sow_name_uses_the_ai_opportunity_name(db_session, leader_client):
    project = _persist_project(db_session, leader_client.user, code="DOC-SOW-NAME-001")
    _persist_doc_template(db_session, leader_client.user, document_type="sow")
    opportunity = ProjectResearchSubject(
        project_id=project.id,
        subject_type="opportunity",
        subject_key="order_forecast",
        name="销售订单智能预测",
        description="",
        status="active",
        tracking_code="OPP-0002",
    )
    db_session.add(opportunity)
    db_session.commit()

    response = leader_client.post(
        f"/api/v1/projects/{project.id}/documents",
        json={
            "document_type": "sow",
            "expected_version": 1,
            "source_opportunity_id": opportunity.id,
        },
    )

    assert response.status_code == 201, response.get_data(as_text=True)
    assert response.json["data"]["business_code"] == "SOW-销售订单智能预测"


def test_document_can_be_renamed_without_creating_a_new_version(db_session, leader_client):
    project = _persist_project(db_session, leader_client.user, code="DOC-RENAME-001")
    _persist_doc_template(db_session, leader_client.user, document_type="sow")
    created = leader_client.post(
        f"/api/v1/projects/{project.id}/documents",
        json={"document_type": "sow", "expected_version": 1},
    )
    assert created.status_code == 201, created.get_data(as_text=True)
    document = created.json["data"]

    renamed = leader_client.patch(
        f"/api/v1/projects/{project.id}/documents/{document['id']}",
        json={"version": document["version"], "name": "SOW-销售订单智能分析"},
    )

    assert renamed.status_code == 200, renamed.get_data(as_text=True)
    assert renamed.json["data"]["business_code"] == "SOW-销售订单智能分析"
    assert renamed.json["data"]["version"] == document["version"] + 1
    assert db_session.query(ProjectDocumentVersion).filter_by(document_id=document["id"]).count() == 0


def test_create_document_without_published_template_reports_exact_reason(
    db_session, leader_client
):
    leader = leader_client.user
    project = _persist_project(db_session, leader, code="DOC-NO-TEMPLATE")
    _, template_version = _persist_doc_template(db_session, leader, document_type="pov_plan")
    template_version.status = "inactive"
    db_session.commit()

    response = leader_client.post(
        f"/api/v1/projects/{project.id}/documents",
        json={"document_type": "pov_plan", "expected_version": 1},
    )

    assert_error(response, 422, "document_template_not_published")


def test_source_opportunity_is_only_supported_for_pov_and_sow(
    db_session, leader_client
):
    """Allowing arbitrary document types to claim opportunity provenance would corrupt traceability."""
    leader = leader_client.user
    project = _persist_project(db_session, leader, code="DOC-OPP-002")
    _, template_version = _persist_doc_template(
        db_session, leader, document_type="contract"
    )
    opportunity = ProjectResearchSubject(
        project_id=project.id,
        subject_type="opportunity",
        subject_key="sales_copilot",
        name="销售助手",
        description="",
        status="active",
        tracking_code="OPP-0001",
    )
    db_session.add(opportunity)
    db_session.commit()

    response = leader_client.post(
        f"/api/v1/projects/{project.id}/documents",
        json={
            "document_type": "contract",
            "template_version_id": template_version.id,
            "expected_version": 1,
            "source_opportunity_id": opportunity.id,
        },
    )

    assert_error(response, 400, "invalid_source_opportunity")


def test_stale_draft_patch_preserves_server_value(db_session, leader_client):
    leader = leader_client.user
    project = _persist_project(db_session, leader, code="DOC-STALE-001")
    _, template_version = _persist_doc_template(db_session, leader)
    created = leader_client.post(
        f"/api/v1/projects/{project.id}/documents",
        json={
            "document_type": "sow",
            "template_version_id": template_version.id,
            "expected_version": 1,
        },
    )
    assert created.status_code == 201, created.get_data(as_text=True)
    document_id = created.json["data"]["id"]
    draft_url = f"/api/v1/projects/{project.id}/documents/{document_id}/draft"

    first_patch = leader_client.patch(
        draft_url,
        json={"version": 1, "field_overrides": {"name": "first"}},
    )
    assert first_patch.status_code == 200, first_patch.get_data(as_text=True)
    assert first_patch.json["data"]["field_overrides"] == {"name": "first"}
    assert first_patch.json["data"]["version"] == 2

    stale_patch = leader_client.patch(
        draft_url,
        json={"version": 1, "field_overrides": {"name": "second"}},
    )
    assert_error(stale_patch, 409, "stale_version")

    detail = leader_client.get(f"/api/v1/projects/{project.id}/documents/{document_id}")
    assert detail.status_code == 200, detail.get_data(as_text=True)
    assert detail.json["data"]["draft"]["field_overrides"] == {"name": "first"}


def test_patch_draft_sanitizes_rich_text(db_session, leader_client):
    leader = leader_client.user
    project = _persist_project(db_session, leader, code="DOC-SANITIZE-001")
    _, template_version = _persist_doc_template(db_session, leader)
    created = leader_client.post(
        f"/api/v1/projects/{project.id}/documents",
        json={
            "document_type": "sow",
            "template_version_id": template_version.id,
            "expected_version": 1,
        },
    )
    assert created.status_code == 201, created.get_data(as_text=True)
    document_id = created.json["data"]["id"]
    draft_url = f"/api/v1/projects/{project.id}/documents/{document_id}/draft"

    patch = leader_client.patch(
        draft_url,
        json={
            "version": 1,
            "rich_text": {
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": "<script>alert(1)</script>hello",
                    },
                    {"type": "script", "content": "alert(2)"},
                ],
            },
        },
    )
    assert patch.status_code == 200, patch.get_data(as_text=True)
    stored = patch.json["data"]["rich_text"]
    assert isinstance(stored, list)
    # The standalone script block is dropped and the inline tag is stripped.
    assert len(stored) == 1
    assert stored[0]["type"] == "paragraph"
    assert stored[0]["content"] == "alert(1)hello"
    assert "<script" not in stored[0]["content"]


def test_request_generation_creates_version_and_job(db_session, leader_client):
    leader = leader_client.user
    project = _persist_project(db_session, leader, code="DOC-GEN-001")
    _, template_version = _persist_doc_template(db_session, leader)
    created = leader_client.post(
        f"/api/v1/projects/{project.id}/documents",
        json={
            "document_type": "sow",
            "template_version_id": template_version.id,
            "expected_version": 1,
        },
    )
    assert created.status_code == 201, created.get_data(as_text=True)
    document_id = created.json["data"]["id"]
    document_version = created.json["data"]["version"]

    generate = leader_client.post(
        f"/api/v1/projects/{project.id}/documents/{document_id}/generate",
        json={"version": document_version},
    )
    assert generate.status_code == 200, generate.get_data(as_text=True)
    payload = generate.json["data"]
    assert payload["source"] == "generated"
    assert payload["status"] == "draft"
    assert payload["source_snapshot_json"]["project"]["id"] == project.id

    db_session.rollback()

    version = db_session.scalar(
        select(ProjectDocumentVersion).where(
            ProjectDocumentVersion.id == payload["id"]
        )
    )
    assert version is not None
    assert version.source == "generated"

    job = db_session.scalar(
        select(DocumentGenerationJob).where(
            DocumentGenerationJob.document_version_id == version.id
        )
    )
    assert job is not None
    assert job.status == "queued"

    outbox = list(
        db_session.scalars(
            select(OutboxEvent).where(OutboxEvent.topic == "document.generate")
        )
    )
    assert len(outbox) == 1
    assert outbox[0].aggregate_id == version.id


def test_create_document_roundtrips_business_category(db_session, leader_client):
    """A category set at create persists onto the document, is exposed in the
    list/detail DTOs, and the list endpoint filters by it."""
    leader = leader_client.user
    project = _persist_project(db_session, leader, code="DOC-CAT-001")
    _, template_version = _persist_doc_template(db_session, leader)
    url = f"/api/v1/projects/{project.id}/documents"

    created = leader_client.post(
        url,
        json={
            "document_type": "sow",
            "template_version_id": template_version.id,
            "expected_version": 1,
            "business_category": "调研",
        },
    )
    assert created.status_code == 201, created.get_data(as_text=True)
    assert created.json["data"]["business_category"] == "调研"
    document_id = created.json["data"]["id"]

    detail = leader_client.get(f"{url}/{document_id}")
    assert detail.status_code == 200, detail.get_data(as_text=True)
    assert detail.json["data"]["business_category"] == "调研"

    filtered = leader_client.get(f"{url}?business_category=调研")
    assert filtered.status_code == 200, filtered.get_data(as_text=True)
    assert [item["id"] for item in filtered.json["data"]["items"]] == [document_id]

    other = leader_client.get(f"{url}?business_category=商务合约")
    assert other.status_code == 200, other.get_data(as_text=True)
    assert other.json["data"]["items"] == []


def test_create_document_rejects_invalid_business_category(
    db_session, leader_client
):
    leader = leader_client.user
    project = _persist_project(db_session, leader, code="DOC-CAT-BAD")
    _, template_version = _persist_doc_template(db_session, leader)
    url = f"/api/v1/projects/{project.id}/documents"

    response = leader_client.post(
        url,
        json={
            "document_type": "sow",
            "template_version_id": template_version.id,
            "expected_version": 1,
            "business_category": "不存在",
        },
    )
    assert_error(response, 400, "invalid_business_category")


def test_list_documents_rejects_invalid_business_category_filter(
    db_session, leader_client
):
    leader = leader_client.user
    project = _persist_project(db_session, leader, code="DOC-CAT-FILTER")
    url = f"/api/v1/projects/{project.id}/documents"

    response = leader_client.get(f"{url}?business_category=不存在")
    assert_error(response, 400, "invalid_business_category")
