"""V3 T-O2b：对象类型值域开放（设计 ontology-registry-v1 §2.3 兼容边界的解除）。

- 注册表闸门：create_subject_in_transaction 单原语把守「内置 ∪ 注册表 active
  −project」——人工创建与导入 commit 同闸；project 根类型永不可建；retired/
  draft 类型禁新建（存量只读）；形状非法（大写/超宽）仍 invalid_request。
- 注册类型对象可走全链路：创建（无跟踪码、根级——注册类型无父级规则）→
  导入 preview/store/commit → 文档快照（按实际类型分组，retire 不丢存量）。
- 表单定义/AI 生成/行业模板：allowed_subject_types 缺省=内置五类（防 AI 幻觉
  基线不变），注册表上下文传「内置 ∪ active 注册行」；模板完整性基线（五类
  内置必备）不放开。
- 文档映射：允许域从已发布 research definition 派生（内置 ∪ 定义声明类型），
  纯函数不查注册表。
"""
from __future__ import annotations

from io import BytesIO
from uuid import uuid4

import pytest

from test_document_drafts_api import _persist_project
from test_research_subjects_api import (  # noqa: F401  (pytest fixture)
    AuthorizedClient,
    _create_project,
    _project_payload,
    _subject_payload,
    admin_client,
    authorized_client_factory,
    leader_client,
    published_template,
)

from conftest import INITIAL_PASSWORD
from fde_api.ai.industry_template_schema import (
    AIContractError,
    validate_generated_template,
)
from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.documents.mapping import validate_mapping
from fde_api.documents.snapshots import build_document_snapshot
from fde_api.documents.template_parser import TemplateScan
from fde_api.ontology.service import (
    OntologyServiceError,
    register_relation_type,
    retire_relation_type,
    usable_subject_type_codes,
)
from fde_api.research.imports import (
    ImportServiceError,
    authorize_subject_import,
    commit_subject_import,
    preview_subject_import,
    store_subject_import_preview,
)
from fde_api.research.models import SUBJECT_TYPES, ProjectResearchSubject


def _actor(db_session, *, name: str) -> User:
    user = User(
        username=f"domain.{name}.{uuid4().hex[:8]}",
        display_name=name,
        role="admin",
        password_hash=hash_password(INITIAL_PASSWORD),
        must_change_password=False,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return user


def _register_subject_type(db_session, actor: User, *, project_id: str | None, code: str, status: str = "active"):
    row = register_relation_type(
        db_session,
        project_id=project_id,
        kind="subject_type",
        code=code,
        actor=actor,
        label=code,
        initial_status=status,
    )
    db_session.commit()
    return row


def _csv_bytes(rows: list[list[str]]) -> bytes:
    buffer = BytesIO()
    buffer.write("\ufeff".encode("utf-8"))
    for row in rows:
        buffer.write((",".join(row) + "\r\n").encode("utf-8"))
    return buffer.getvalue()


def _direct_subject(db_session, project_id: str, *, subject_type: str, key: str) -> ProjectResearchSubject:
    subject = ProjectResearchSubject(
        project_id=project_id,
        subject_type=subject_type,
        subject_key=key,
        name=f"{subject_type} 名称",
        description="",
        memo="",
        status="active",
        version=1,
        sort_order=0,
        tracking_code=None,
    )
    db_session.add(subject)
    db_session.commit()
    return subject


def test_usable_subject_type_codes_scope_and_status(db_session):
    """usable = 内置 ∪ active 注册行（全局∪项目内）；draft/retired 不入值域。"""
    admin = _actor(db_session, name="domain-scope")
    project_a = _persist_project(db_session, admin, code=f"DOMAIN-A-{uuid4().hex[:6]}")
    project_b = _persist_project(db_session, admin, code=f"DOMAIN-B-{uuid4().hex[:6]}")

    assert set(SUBJECT_TYPES) <= usable_subject_type_codes(db_session, project_id=None)
    assert "project" in usable_subject_type_codes(db_session, project_id=str(project_a.id))

    global_row = _register_subject_type(db_session, admin, project_id=None, code="industry_segment")
    scoped_row = _register_subject_type(db_session, admin, project_id=str(project_a.id), code="vendor_site")

    assert {"industry_segment", "vendor_site"} <= usable_subject_type_codes(
        db_session, project_id=str(project_a.id)
    )
    usable_b = usable_subject_type_codes(db_session, project_id=str(project_b.id))
    assert "industry_segment" in usable_b  # 全局行对一切项目生效
    assert "vendor_site" not in usable_b  # 项目内行只对本项目生效

    # draft 是未拍板提案、retired 禁新建——都不入值域
    _register_subject_type(db_session, admin, project_id=str(project_a.id), code="draft_kind", status="draft")
    assert "draft_kind" not in usable_subject_type_codes(db_session, project_id=str(project_a.id))
    retire_relation_type(db_session, relation_type_id=global_row.id, actor=admin)
    db_session.commit()
    assert "industry_segment" not in usable_subject_type_codes(db_session, project_id=str(project_b.id))
    # known_subject_type_codes（引用解析）仍含 retired——两把尺子语义不同
    from fde_api.ontology.service import known_subject_type_codes

    assert "industry_segment" in known_subject_type_codes(db_session, project_id=str(project_b.id))
    assert scoped_row.code == "vendor_site" and global_row.code == "industry_segment"


def test_registered_type_end_to_end_create_and_gate_semantics(
    db_session, admin_client, published_template, leader_client
):
    """注册类型走 HTTP 创建全链路；project 根保留、未知/退役拒、形状非法仍 invalid_request。"""
    admin = admin_client.user
    project = _create_project(admin_client, published_template, leader_client.user)
    project_id = project["id"]
    url = f"/api/v1/projects/{project_id}/research/subjects"
    _register_subject_type(db_session, admin, project_id=project_id, code="vendor_site")

    # 根级注册类型对象可建（注册类型无父级规则 → 只许根级）；无跟踪码前缀
    created = leader_client.post(url, json=_subject_payload("vendor_site", version=1))
    assert created.status_code == 201, created.get_data(as_text=True)
    assert created.json["data"]["subject_type"] == "vendor_site"
    assert created.json["data"]["tracking_code"] is None
    project_version = created.json["data"]["project_version"]

    # department 父级 + vendor_site 子级 → 注册类型无父级规则，拒绝嵌套
    department = leader_client.post(
        url, json=_subject_payload("department", subject_key="sales_dept", version=project_version)
    )
    assert department.status_code == 201, department.get_data(as_text=True)
    project_version = department.json["data"]["project_version"]
    nested = leader_client.post(
        url,
        json=_subject_payload(
            "vendor_site",
            subject_key="vendor_nested",
            parent_subject_id=department.json["data"]["id"],
            version=project_version,
        ),
    )
    assert nested.status_code == 400
    assert nested.json["error"]["code"] == "invalid_subject_parent"

    # project 根类型保留（永不可建）；注册表外的码拒绝——同一闸门语义
    root = leader_client.post(url, json=_subject_payload("project", version=project_version))
    assert root.status_code == 400
    assert root.json["error"]["code"] == "unsupported_subject_type"
    unknown = leader_client.post(url, json=_subject_payload("ghost_type", version=project_version))
    assert unknown.status_code == 400
    assert unknown.json["error"]["code"] == "unsupported_subject_type"
    # 形状非法（大写开头）在 _normalize_create 拦截，仍是 invalid_request
    malformed = leader_client.post(url, json=_subject_payload("VendorSite", version=project_version))
    assert malformed.status_code == 400
    assert malformed.json["error"]["code"] == "invalid_request"


def test_retire_blocks_new_but_keeps_existing_and_snapshot(db_session, admin_client, published_template, leader_client):
    """retire 只禁新建不禁存量：对象仍在清单与文档快照里（按实际类型分组）。"""
    admin = admin_client.user
    project = _create_project(admin_client, published_template, leader_client.user)
    project_id = project["id"]
    registered = _register_subject_type(db_session, admin, project_id=project_id, code="vendor_site")
    subject = _direct_subject(db_session, project_id, subject_type="vendor_site", key=f"vendor_{uuid4().hex[:6]}")

    snapshot = build_document_snapshot(db_session, project_id, {})
    assert "vendor_site" in snapshot["subjects"]
    assert snapshot["subjects"]["vendor_site"][0]["id"] == subject.id

    retire_relation_type(db_session, relation_type_id=registered.id, actor=admin)
    db_session.commit()

    response = admin_client.post(
        f"/api/v1/projects/{project_id}/research/subjects",
        json=_subject_payload("vendor_site", version=1),
    )
    assert response.status_code == 400
    assert response.json["error"]["code"] == "unsupported_subject_type"

    snapshot_after = build_document_snapshot(db_session, project_id, {})
    assert "vendor_site" in snapshot_after["subjects"]
    assert snapshot_after["subjects"]["vendor_site"][0]["id"] == subject.id


def test_import_flow_with_registered_type(db_session, admin_client, published_template, leader_client):
    """导入三闸一致：authorize 带回值域 → preview/store 前置 → commit 原语复核。"""
    admin = admin_client.user
    project = _create_project(admin_client, published_template, leader_client.user)
    project_id = project["id"]
    _register_subject_type(db_session, admin, project_id=project_id, code="vendor_site")

    allowed = authorize_subject_import(leader_client.user, project_id)
    assert "vendor_site" in allowed
    assert "project" not in allowed  # 根类型永不入导入域

    preview = preview_subject_import(
        BytesIO(_csv_bytes([["名称", "说明", "父级"], ["站点A", "主要站点", ""]])),
        "sites.csv",
        "vendor_site",
        allowed_subject_types=allowed,
    )
    stored = store_subject_import_preview(actor=leader_client.user, project_id=project_id, preview=preview)
    result = commit_subject_import(project_id, stored.preview_token, 1, leader_client.user)
    assert [item["subject_type"] for item in result.to_dict()["subjects"]] == ["vendor_site"]

    # 缺省值域（内置四类）行为不变：注册码与 project 根都被拒
    for rejected_type in ("vendor_site", "project"):
        with pytest.raises(ImportServiceError) as caught:
            preview_subject_import(
                BytesIO(_csv_bytes([["名称", "说明", "父级"], ["x", "", ""]])),
                "sites.csv",
                rejected_type,
            )
        assert caught.value.code == "unsupported_subject_type"


def test_form_definition_validation_domain(db_session):
    """表单定义值域：缺省=内置五类；传注册表域则注册类型可进。"""
    from fde_api.research.definitions import validate_research_definition

    definition = {
        "forms": [
            {
                "form_key": "vendor_visit",
                "name": "供应商走访表",
                "description": "",
                "subject_type": "vendor_site",
                "module_key": None,
                "sort_order": 1,
                "sections": [
                    {
                        "section_key": "basics",
                        "name": "基础信息",
                        "description": "",
                        "fields": [
                            {
                                "field_key": "site_name",
                                "name": "站点名称",
                                "help_text": "",
                                "type": "short_text",
                                "is_required": False,
                                "options": {},
                            }
                        ],
                    }
                ],
            }
        ]
    }
    issues = validate_research_definition(definition)
    assert any(issue.code == "invalid_subject_type" for issue in issues)
    assert validate_research_definition(definition, allowed_subject_types={"vendor_site"}) == []


def test_ai_generated_form_domain(db_session):
    """AI 生成表单校验：缺省拒注册类型（防幻觉基线），带注册表域放行。"""
    from fde_api.ai.research_form_service import _valid_generated_form

    form = {
        "form_key": "vendor_visit",
        "name": "供应商走访表",
        "description": "",
        "subject_type": "vendor_site",
        "module_key": None,
        "sections": [
            {
                "section_key": "basics",
                "name": "基础信息",
                "description": "",
                "fields": [
                    {
                        "field_key": "site_name",
                        "name": "站点名称",
                        "help_text": "",
                        "type": "short_text",
                        "is_required": False,
                        "options": {},
                    }
                ],
            }
        ],
    }
    assert _valid_generated_form(form, [], set()) is False
    assert _valid_generated_form(form, [], set(), allowed_subject_types={"vendor_site"}) is True


def test_document_mapping_domain_from_published_definition(db_session):
    """映射允许域 = 内置 ∪ 已发布定义声明的类型；garbage 码仍报 unsupported。"""
    scan = TemplateScan(placeholders=["{{ project.name }}"], issues=[], tables=[])
    definition = {
        "forms": {
            "vendor_visit": {"form_key": "vendor_visit", "subject_type": "vendor_site"},
            "role_profile": {"form_key": "role_profile", "subject_type": "role"},
        }
    }
    issues = validate_mapping(
        scan,
        {
            "research_keys": [{"form_key": "vendor_visit", "subject_type": "vendor_site"}],
            "field_map": {},
            "sections": [],
        },
        definition,
    )
    assert issues == []

    garbage = validate_mapping(
        scan,
        {
            "research_keys": [{"form_key": "vendor_visit", "subject_type": "galaxy"}],
            "field_map": {},
            "sections": [],
        },
        definition,
    )
    assert any(issue.code == "unsupported_subject_type" for issue in garbage)


def test_template_schema_domain_and_completeness(db_session):
    """行业模板：全局注册类型可进（带全局域），缺省仍拒；五类内置完整性基线不放开。"""

    def field(key: str) -> dict:
        return {
            "field_key": key,
            "name": key,
            "help_text": "",
            "type": "short_text",
            "is_required": False,
            "options": {},
            "sort_order": 1,
        }

    def extra_form(subject_type: str) -> dict:
        return {
            "form_key": f"{subject_type}_form",
            "name": f"{subject_type} form",
            "description": "",
            "subject_type": subject_type,
            "module_key": "pre_diagnosis",
            "sort_order": 6,
            "sections": [
                {
                    "section_key": "basics",
                    "name": "基础信息",
                    "description": "",
                    "sort_order": 1,
                    "fields": [field(f"{subject_type}_name")],
                }
            ],
        }

    def base_template() -> dict:
        return {
            "name": "制造业模板",
            "industry_name": "制造业",
            "description": "测试",
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
            "research_definition": {
                "forms": [extra_form(subject_type) for subject_type in SUBJECT_TYPES]
            },
        }

    global_codes = usable_subject_type_codes(db_session, project_id=None)
    admin = _actor(db_session, name="domain-template")
    _register_subject_type(db_session, admin, project_id=None, code="industry_segment")
    global_codes = usable_subject_type_codes(db_session, project_id=None)
    assert "industry_segment" in global_codes

    payload = base_template()
    payload["research_definition"]["forms"].append(extra_form("industry_segment"))
    result = validate_generated_template(
        payload,
        active_module_keys={"pre_diagnosis"},
        allowed_subject_types=global_codes,
    )
    assert len(result["research_definition"]["forms"]) == 6

    # 缺省（内置五类）：注册类型被拒——防 AI 幻觉基线不变
    with pytest.raises(AIContractError) as caught:
        validate_generated_template(payload, active_module_keys={"pre_diagnosis"})
    assert caught.value.code == "invalid_subject_type"

    # 完整性基线：删掉一个内置类型仍然拒绝（开放值域 ≠ 放弃五类底线）
    incomplete = base_template()
    incomplete["research_definition"]["forms"].pop()
    with pytest.raises(AIContractError) as caught:
        validate_generated_template(
            incomplete,
            active_module_keys={"pre_diagnosis"},
            allowed_subject_types=global_codes,
        )
    assert caught.value.code == "missing_research_subject_type"


def test_builtin_codes_registry_overlap_pinned(db_session):
    """红线钉子：注册表不得覆盖内置码（duplicate_code），值域开放不改变这一点。"""
    admin = _actor(db_session, name="domain-pin")
    with pytest.raises(OntologyServiceError) as caught:
        register_relation_type(
            db_session,
            project_id=None,
            kind="subject_type",
            code="department",
            actor=admin,
        )
    assert caught.value.code == "duplicate_code"
