"""T-A2 worker 集成哨兵：presurvey 分析链的企业名替换三道防线。

钉住：
1. 全文进模型前已被替换（fake client 捕获 build_messages 的产物）；
2. 模型输出回显企业名时落库前兜底替换 + 复核事件落 operation_events；
3. 词典机制性故障（RedactionConfigError）→ fail-closed，分析落 failed
   且 failure_code=pseudonym_dict_unavailable，不重试不卡 analyzing。

测试数据全部合成（AGENTS.md 红线：真实客户资料不可作测试素材）。
"""

from __future__ import annotations

import io
from datetime import date
from uuid import uuid4

import pytest

from fde_api.auth.models import User
from fde_api.extensions import db, object_storage
from fde_api.files.models import ProjectFile, ProjectFileVersion
from fde_api.guidance import jobs as guidance_jobs
from fde_api.guidance.enterprise_dict import EXTRA_DICT_ENV, reset_dict_cache
from fde_api.guidance.jobs import (
    DICT_FAILURE_CODE,
    REDACTION_EVENT_TYPE,
    handle_presurvey_analysis,
)
from fde_api.guidance.models import ProjectGuidanceAnalysis
from fde_api.jobs.models import BackgroundJob
from fde_api.workbench.models import IndustryTemplate, IndustryTemplateVersion, OperationEvent, Project

_SEED_NAME = "黑名单示例控股公司"  # server/seeds/enterprise-names.txt 合成示例


@pytest.fixture(autouse=True)
def _clean_dict_env(monkeypatch):
    monkeypatch.delenv(EXTRA_DICT_ENV, raising=False)
    reset_dict_cache()
    yield
    reset_dict_cache()


def _setup_world(db_session, *, docx_text: str):
    leader = User(
        username=f"ta2.lead.{uuid4().hex}",
        display_name="代号化负责人",
        role="project_lead",
        password_hash="x",
        must_change_password=False,
        is_active=True,
    )
    template = IndustryTemplate(name="代号化模板", industry_name="制造")
    template_version = IndustryTemplateVersion(
        template=template, name=template.name, industry_name=template.industry_name,
        description="", version_number=1, status="published", published_by=leader,
    )
    project = Project(
        id=uuid4().hex,
        project_code=f"TA2-{uuid4().hex[:8]}", name="代号化哨兵项目",
        enterprise_code="客户A·制造业·苏州", leader=leader, business_line="FDE",
        source_template_version=template_version, template_snapshot={},
        planned_start_date=date(2026, 1, 1),
    )
    db_session.add_all([leader, template])
    db_session.flush()
    db_session.add(template_version)
    db_session.flush()
    db_session.add(project)
    db_session.flush()

    from docx import Document

    document = Document()
    document.add_paragraph(docx_text)
    buffer = io.BytesIO()
    document.save(buffer)
    data = buffer.getvalue()

    file_id = uuid4().hex
    version_id = uuid4().hex
    project_file = ProjectFile(
        id=file_id, project=project, category="attachment",
        display_name="预调研表", description="", created_by=leader,
    )
    version = ProjectFileVersion(
        id=version_id, project_file=project_file, version_number=1,
        source="upload", original_filename="预调研表.docx",
        safe_filename="presurvey.docx", extension="docx", mime_type="",
        bucket="local", storage_key=f"projects/{project.id}/presurvey/p.docx",
        size_bytes=len(data), etag="", sha256="", uploaded_by=leader,
        status="available", scan_status="clean", preview_status="none",
    )
    analysis = ProjectGuidanceAnalysis(
        id=uuid4().hex, project_id=project.id, version_number=1,
        source_file_id=file_id, source_file_version_id=version_id,
        source_filename="预调研表.docx", source_sha256="",
        status="draft", analysis_state="queued", created_by_user_id=leader.id,
    )
    job = BackgroundJob(job_type="project.presurvey.analyze", target_id=analysis.id, status="pending")
    db_session.add_all([project_file])
    db_session.flush()
    db_session.add_all([version, analysis, job])
    db_session.commit()
    object_storage.current.put_stream(version.storage_key, io.BytesIO(data), "application/octet-stream", {})
    return analysis, job, project.id, leader.id


def _valid_payload(source_ref: str, *, echo_text: str = "围绕客户代号展开"):
    from fde_api.guidance.ai_schema import LIST_FIELDS

    item = {
        "text": echo_text, "classification": "customer_stated",
        "source_refs": [source_ref], "confirmed": False,
    }
    return {
        "customer_vision": echo_text,
        "current_phase_objective": echo_text,
        "executive_summary": echo_text,
        "evidence": {source_ref: echo_text},
        **{field: [dict(item)] for field in LIST_FIELDS},
    }


def test_content_redacted_before_model_and_review_event_written(app, db_session, monkeypatch):
    class _Capture:
        """走真实本地 DOCX 抽取（bytes→text），只拦截 build_messages 的产物。"""

        contents: list[str] = []

        def __init__(self, *, version_id=None, **_kwargs):
            self._version_id = version_id or ""

        def analyze_docx_json(self, *, stream, filename, request_id, build_messages):
            from fde_api.documents.qa import extract_docx_xml_text

            raw = extract_docx_xml_text(stream)
            messages = build_messages(raw)
            combined = "".join(str(m.get("content", "")) for m in messages)
            _Capture.contents.append(combined)
            source_ref = f"kimi-file:{self._version_id}"
            return _valid_payload(source_ref, echo_text=f" {_SEED_NAME} 希望试点")

    analysis, job, project_id, leader_id = _setup_world(db_session, docx_text=f"甲方是 {_SEED_NAME}，需要 MES。")
    version_id = analysis.source_file_version_id

    monkeypatch.setattr(
        guidance_jobs, "KimiFileClient",
        lambda **kwargs: _Capture(version_id=version_id),
    )

    with app.app_context():
        handle_presurvey_analysis(job)

    db_session.expire_all()
    analysis = db_session.get(ProjectGuidanceAnalysis, analysis.id)
    assert analysis.analysis_state == "ready"

    # 防线①：进模型的全文不含词典企业名，已换成 enterprise_code
    sent = _Capture.contents[-1]
    assert _SEED_NAME not in sent
    assert "客户A·制造业·苏州" not in sent
    assert "客户A" in sent

    # 防线②：模型输出回显的企业名在落库前被兜底替换
    assert _SEED_NAME not in (analysis.customer_vision or "")
    assert _SEED_NAME not in (analysis.executive_summary or "")

    # 复核事件落 operation_events（B#9 事实链可查）
    event = db_session.query(OperationEvent).filter_by(
        event_type=REDACTION_EVENT_TYPE, target_id=analysis.id
    ).one_or_none()
    assert event is not None
    names = {entry["name"] for entry in event.changes["entries"]}
    assert _SEED_NAME in names


def test_dict_failure_fails_closed_without_retry(app, db_session, monkeypatch):
    from fde_api.guidance.enterprise_dict import RedactionConfigError

    calls: list[int] = []

    class _ExplodingKimi:
        def __init__(self, **_kwargs):
            pass

        def analyze_docx_json(self, **kwargs):
            calls.append(1)
            raise RedactionConfigError("种子缺失")

    analysis, job, _project_id, _leader_id = _setup_world(db_session, docx_text="普通文本即可")
    monkeypatch.setattr(guidance_jobs, "KimiFileClient", _ExplodingKimi)

    with app.app_context():
        handle_presurvey_analysis(job)

    db_session.expire_all()
    analysis = db_session.get(ProjectGuidanceAnalysis, analysis.id)
    assert analysis.analysis_state == "failed"
    assert analysis.failure_code == DICT_FAILURE_CODE
    assert len(calls) == 1  # 不重试
