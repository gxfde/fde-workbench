from __future__ import annotations

import io
import json
from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest
from docx import Document
from docx.oxml.ns import qn
from sqlalchemy import func, select

from fde_api.auth.models import User
from fde_api.documents.generator import handle_document_generation, render_docx
from fde_api.documents.models import (
    DocumentGenerationJob,
    DocumentTemplate,
    DocumentTemplateVersion,
    ProjectDocument,
    ProjectDocumentVersion,
)
from fde_api.documents.qa import extract_docx_xml_text
from fde_api.extensions import object_storage
from fde_api.files.models import ProjectFile, ProjectFileVersion
from fde_api.files.names import extension_of, safe_filename
from fde_api.workbench.models import (
    IndustryTemplate,
    IndustryTemplateVersion,
    Project,
)

FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "documents" / "fixture-data.json"
)
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

SOW_SECTIONS = ["工作范围", "交付物", "时间计划", "验收标准"]


@pytest.fixture
def fixture_context() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _in_memory_docx(build) -> bytes:
    doc = Document()
    build(doc)
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def _context_template_bytes() -> bytes:
    """A template exercising a context placeholder, a loop, a scalar and a table."""

    def build(doc) -> None:
        doc.add_paragraph("项目：{{ project.name }}")
        doc.add_paragraph("角色：{% for role in subjects.roles %}{{ role.name }}{% endfor %}")
        doc.add_paragraph("编号：{{ document.business_code }}")
        table = doc.add_table(rows=1, cols=2)
        table.cell(0, 0).text = "企业"
        table.cell(0, 1).text = "{{ project.enterprise_name }}"

    return _in_memory_docx(build)


def _clean_sow_template_bytes() -> bytes:
    """A template that renders and contains all SOW required sections."""

    def build(doc) -> None:
        doc.add_heading("项目信息", level=1)
        doc.add_paragraph("项目：{{ project.name }}")
        doc.add_paragraph("角色：{% for role in subjects.roles %}{{ role.name }}{% endfor %}")
        doc.add_heading("项目目标与成功边界", level=1)
        doc.add_paragraph("编号：{{ document.business_code }}")
        doc.add_heading("服务类型受控选择", level=1)

    return _in_memory_docx(build)


def _residual_sow_template_bytes() -> bytes:
    """A template that leaves a residual placeholder after rendering."""

    def build(doc) -> None:
        doc.add_heading("项目信息", level=1)
        doc.add_paragraph("企业：{% raw %}{{ enterprise.name }}{% endraw %}")
        doc.add_heading("项目目标与成功边界", level=1)
        doc.add_heading("服务类型受控选择", level=1)

    return _in_memory_docx(build)


def _sow_template_with_ai_optional_placeholder_bytes() -> bytes:
    """A valid SOW whose custom field may be omitted by the AI provider."""

    def build(doc) -> None:
        doc.add_heading("项目信息", level=1)
        doc.add_paragraph("生成日期：【待填写：生成日期】")
        doc.add_heading("项目目标与成功边界", level=1)
        doc.add_paragraph("第三方依赖：【待填写：第三方依赖】")
        doc.add_heading("服务类型受控选择", level=1)

    return _in_memory_docx(build)


def _seed_generation(
    db_session,
    *,
    template_bytes: bytes,
    document_type: str = "sow",
    business_code: str = "OPP-0001",
):
    """Persist the full object graph needed by ``handle_document_generation``."""
    leader = User(
        username=f"gen.lead.{uuid4().hex}",
        display_name="生成负责人",
        role="project_lead",
        password_hash="x",
        must_change_password=False,
        is_active=True,
    )
    db_session.add(leader)
    db_session.flush()

    industry_template = IndustryTemplate(name="文档模板", industry_name="制造")
    industry_version = IndustryTemplateVersion(
        template=industry_template,
        name=industry_template.name,
        industry_name=industry_template.industry_name,
        description="",
        version_number=1,
        status="published",
        published_by=leader,
    )
    db_session.add_all([industry_template, industry_version])
    db_session.flush()

    project = Project(
        project_code=f"FDE-GEN-{uuid4().hex[:8]}",
        name="星河 PoV",
        enterprise_name="星河制造",
        leader=leader,
        source_template_version=industry_version,
        template_snapshot={},
        planned_start_date=date(2026, 8, 22),
    )
    db_session.add(project)
    db_session.flush()

    doc_template = DocumentTemplate(
        document_type=document_type,
        name=f"{document_type} 模板",
        description="",
        industry_name="制造",
    )
    db_session.add(doc_template)
    db_session.flush()

    template_filename = f"{document_type}-v1.docx"
    template_safe = safe_filename(template_filename)
    template_key = (
        f"projects/{project.id}/templates/{document_type}/versions/1/{template_safe}"
    )
    template_storage = object_storage.current.put_stream(
        template_key, io.BytesIO(template_bytes), DOCX_MIME, {}
    )
    template_file = ProjectFile(
        project=project,
        category="document",
        display_name=template_filename,
        description="",
        created_by=leader,
    )
    db_session.add(template_file)
    db_session.flush()
    template_file_version = ProjectFileVersion(
        project_file=template_file,
        version_number=1,
        source="system_generated",
        original_filename=template_filename,
        safe_filename=template_safe,
        extension=extension_of(template_filename),
        mime_type=DOCX_MIME,
        bucket="local",
        storage_key=template_key,
        size_bytes=template_storage.size,
        etag=template_storage.etag,
        sha256="",
        scan_status="not_required",
        preview_status="none",
        uploaded_by=leader,
        status="available",
    )
    db_session.add(template_file_version)
    db_session.flush()
    template_file.current_version_id = template_file_version.id

    template_version = DocumentTemplateVersion(
        template=doc_template,
        version_number=1,
        status="published",
        docx_file_version_id=template_file_version.id,
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
    db_session.flush()

    document = ProjectDocument(
        project=project,
        document_type=document_type,
        business_code=business_code,
        source_template_version_id=template_version.id,
        status="draft",
        owner=leader,
    )
    db_session.add(document)
    db_session.flush()

    docx_filename = f"{business_code}-v1.docx"
    docx_safe = safe_filename(docx_filename)
    docx_key = (
        f"projects/{project.id}/documents/{document.id}/versions/1/{docx_safe}"
    )
    docx_file = ProjectFile(
        project=project,
        category="document",
        display_name=docx_filename,
        description="",
        created_by=leader,
    )
    db_session.add(docx_file)
    db_session.flush()
    docx_file_version = ProjectFileVersion(
        project_file=docx_file,
        version_number=1,
        source="system_generated",
        original_filename=docx_filename,
        safe_filename=docx_safe,
        extension=extension_of(docx_filename),
        mime_type=DOCX_MIME,
        bucket="local",
        storage_key=docx_key,
        size_bytes=0,
        etag="",
        sha256="",
        scan_status="not_required",
        preview_status="none",
        uploaded_by=leader,
        status="uploading",
    )
    db_session.add(docx_file_version)
    db_session.flush()
    docx_file.current_version_id = docx_file_version.id

    snapshot = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    version = ProjectDocumentVersion(
        document=document,
        version_number=1,
        source="generated",
        status="draft",
        parent_version_id=None,
        source_template_version_id=template_version.id,
        source_snapshot_json=snapshot,
        content_snapshot_json={"field_overrides": {}, "rich_text": {}, "list_selections": {}},
        docx_file_version_id=docx_file_version.id,
        sha256="",
        generated_by=leader,
    )
    db_session.add(version)
    db_session.flush()

    job = DocumentGenerationJob(document_version_id=version.id, status="queued")
    db_session.add(job)
    db_session.commit()

    return {
        "version": version,
        "document": document,
        "docx_file_version": docx_file_version,
        "template_file_version": template_file_version,
        "project": project,
        "leader": leader,
        "job": job,
    }


def test_render_docx_renders_context_and_loop(fixture_context):
    output = render_docx(
        io.BytesIO(_context_template_bytes()), fixture_context, {}
    )
    text = extract_docx_xml_text(output)

    assert "星河 PoV" in text
    assert "仓库主管" in text
    assert "OPP-0001" in text
    assert "星河制造" in text
    assert "{{" not in text
    assert "{%" not in text


def test_render_docx_replaces_business_chinese_placeholders():
    template = _in_memory_docx(
        lambda doc: doc.add_paragraph("现状：【待填写：现状描述】")
    )
    output = render_docx(
        io.BytesIO(template), {"current_situation": "客服需要手工检索多个知识库。"}, {}
    )
    text = extract_docx_xml_text(output)

    assert "客服需要手工检索多个知识库。" in text
    assert "【待填写：" not in text


def test_render_docx_builds_project_plan_sections_from_snapshot():
    def build(doc) -> None:
        for title in ("企业与项目信息", "客户目标与项目指引", "任务甘特图", "任务清单"):
            doc.add_heading(title, level=2)
            doc.add_paragraph(f"【待插入：{title}】")

    context = {
        "project": {
            "name": "星河 AI 项目", "project_code": "FDE-001", "industry_name": "制造业",
            "background": "提升交付效率", "notes": "每周复盘", "leader_name": "王工",
            "status": "active", "planned_start_date": "2026-08-31", "planned_end_date": "2026-09-10",
        },
        "enterprise": {"name": "星河制造", "contact_name": "陈总", "contact_phone": "13800000000", "address": "深圳"},
        "guidance": {"customer_vision": "建设智能工厂", "current_phase_objective": "完成诊断", "priority_roles": ["计划员"]},
        "tasks": [{
            "name": "完成预调研", "module_name": "预调研", "status": "in_progress", "progress": 40,
            "planned_start_date": "2026-08-31", "planned_end_date": "2026-09-02", "assignee": {"display_name": "王工"},
            "dependencies": [],
        }],
    }
    output = render_docx(io.BytesIO(_in_memory_docx(build)), context, {})
    text = extract_docx_xml_text(output)

    for expected in ("星河制造", "建设智能工厂", "完成预调研", "任务甘特图", "任务清单"):
        assert expected in text
    assert "【待插入：" not in text


def test_render_docx_replaces_placeholders_across_multiple_tables():
    def build(doc) -> None:
        for index in range(12):
            table = doc.add_table(rows=1, cols=2)
            table.cell(0, 0).text = f"字段 {index + 1}"
            table.cell(0, 1).text = f"【待填写：自定义字段{index + 1}】"

    template = _in_memory_docx(build)
    context = {f"自定义字段{index + 1}": f"内容{index + 1}" for index in range(12)}

    output = render_docx(io.BytesIO(template), context, {})
    text = extract_docx_xml_text(output)

    for index in range(12):
        assert f"内容{index + 1}" in text
    assert "【待填写：" not in text


def test_render_docx_constrains_malformed_table_widths_to_page():
    def build(doc) -> None:
        table = doc.add_table(rows=1, cols=2)
        for column in table._tbl.tblGrid.gridCol_lst:
            column.set(qn("w:w"), "2976480")
        for cell in table.rows[0].cells:
            cell._tc.tcPr.tcW.set(qn("w:w"), "2976480")
            cell.text = "这是一段需要在页面内自动换行的长文本。"

    output = render_docx(io.BytesIO(_in_memory_docx(build)), {}, {})
    rendered = Document(output)
    section = rendered.sections[0]
    usable_width = int(
        (section.page_width - section.left_margin - section.right_margin) / 635
    )
    table = rendered.tables[0]
    grid_widths = [
        int(column.get(qn("w:w")))
        for column in table._tbl.tblGrid.gridCol_lst
    ]

    assert sum(grid_widths) <= usable_width
    assert table._tbl.tblPr.find(qn("w:tblLayout")).get(qn("w:type")) == "fixed"
    assert all(
        int(cell_width.get(qn("w:w"))) <= usable_width
        for cell_width in table._tbl.iter(qn("w:tcW"))
    )


def test_render_docx_rejects_attribute_escape():
    template = _in_memory_docx(
        lambda doc: doc.add_paragraph(
            "{{ cycler.__init__.__globals__.os.system('id') }}"
        )
    )

    with pytest.raises(Exception):
        render_docx(io.BytesIO(template), {"project": {}}, {})


def test_handle_document_generation_is_idempotent(db_session):
    seeded = _seed_generation(
        db_session, template_bytes=_clean_sow_template_bytes()
    )
    version = seeded["version"]

    first = handle_document_generation(version_id=version.id)
    assert first["status"] == "succeeded"
    assert first["sha256"]
    assert first["docx_file_version_id"] == version.docx_file_version_id

    db_session.refresh(version)
    db_session.refresh(seeded["docx_file_version"])
    assert version.sha256 == first["sha256"]
    assert "/documents/" in seeded["docx_file_version"].storage_key
    assert seeded["docx_file_version"].status == "available"
    assert seeded["docx_file_version"].scan_status == "not_required"

    db_session.refresh(seeded["job"])
    assert seeded["job"].status == "succeeded"

    document_id = seeded["document"].id
    docx_path_pattern = f"%documents/{document_id}/versions/%"
    count_before = db_session.scalar(
        select(func.count())
        .select_from(ProjectFileVersion)
        .where(ProjectFileVersion.storage_key.like(docx_path_pattern))
    )
    assert count_before == 1

    second = handle_document_generation(version_id=version.id)
    assert second["status"] == "succeeded"
    assert second["sha256"] == first["sha256"]
    assert second["docx_file_version_id"] == first["docx_file_version_id"]

    count_after = db_session.scalar(
        select(func.count())
        .select_from(ProjectFileVersion)
        .where(ProjectFileVersion.storage_key.like(docx_path_pattern))
    )
    assert count_after == count_before == 1


def test_handle_document_generation_fills_missing_ai_fields_instead_of_leaving_placeholders(db_session):
    seeded = _seed_generation(
        db_session, template_bytes=_sow_template_with_ai_optional_placeholder_bytes()
    )
    version = seeded["version"]

    result = handle_document_generation(version_id=version.id)

    assert result["status"] == "succeeded"
    db_session.refresh(version)
    db_session.refresh(seeded["docx_file_version"])
    stream = object_storage.current.open_stream(seeded["docx_file_version"].storage_key)
    try:
        text = extract_docx_xml_text(io.BytesIO(stream.read()))
    finally:
        stream.close()
    assert "待确认" in text
    assert "【待填写：" not in text


def test_handle_document_generation_files_qa_failure_as_failed(db_session):
    seeded = _seed_generation(
        db_session, template_bytes=_residual_sow_template_bytes()
    )
    version = seeded["version"]

    result = handle_document_generation(version_id=version.id)

    assert result["status"] == "failed"
    assert result["generation_error"]

    db_session.refresh(version)
    db_session.refresh(seeded["docx_file_version"])
    db_session.refresh(seeded["job"])

    assert version.generation_error
    assert version.sha256 == ""
    # The generator must not promote or create a file version on QA failure.
    assert seeded["docx_file_version"].status == "uploading"
    assert seeded["job"].status == "failed"
