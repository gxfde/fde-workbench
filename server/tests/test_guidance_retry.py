# G4：guidance 契约失败自动重试加固的语义钉子。
#
# 已知现象：MiniMax 级模型概率性不守 JSON 合同（ai_output_invalid），一次
# 自动重试即可消化绝大多数。这里钉住 jobs.handle_presurvey_analysis 的
# 重试语义与上限，任何改动（额度、顺序、消息文案）都必须显式更新这些用例。
#
# 语义契约：
#   - 可重试失败（retryable=True 的 KimiError / GuidanceContractError）
#     在同一任务内自动重试 GUIDANCE_ANALYSIS_RETRY_LIMIT 次后仍失败才落
#     failed，消息必须带上「已自动重试」的用户可见提示；
#   - 不可重试失败（ai_service_not_configured 等）一次即败、绝不消耗重试；
#   - source_missing 在构造 AI 客户端之前失败，零 AI 调用；
#   - 未预期异常兜底为 analysis_unexpected_error，分析绝不卡在 analyzing。
from __future__ import annotations

import importlib.util
import io
import json
from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest

from fde_api.ai.kimi import KimiError
from fde_api.auth.models import User
from fde_api.extensions import object_storage
from fde_api.files.models import ProjectFile, ProjectFileVersion
from fde_api.guidance import jobs as guidance_jobs
from fde_api.guidance.ai_schema import LIST_FIELDS
from fde_api.guidance.jobs import (
    GUIDANCE_ANALYSIS_RETRY_LIMIT,
    handle_presurvey_analysis,
)
from fde_api.guidance.models import ProjectGuidanceAnalysis
from fde_api.guidance.redaction import redaction_name_hash
from fde_api.jobs.models import BackgroundJob
from fde_api.jobs.worker import run_job
from fde_api.storage.base import StorageNotFoundError
from fde_api.workbench.models import IndustryTemplate, IndustryTemplateVersion, Project

_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "presurvey"


def _load_generator():
    spec = importlib.util.spec_from_file_location(
        "presurvey_generate_fixtures", _FIXTURES_DIR / "generate_fixtures.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _valid_payload(source_ref: str) -> dict:
    item = {
        "text": "客户希望先在单条产线跑通试点",
        "classification": "customer_stated",
        "source_refs": [source_ref],
        "confirmed": False,
    }
    return {
        "customer_vision": "成为细分市场头部供应商",
        "current_phase_objective": "三个月内完成试点上线",
        "executive_summary": "围绕试点验证再复制。",
        "evidence": {source_ref: "预调研表第一段"},
        **{field: [dict(item)] for field in LIST_FIELDS},
    }


def _contract_violating_payload(source_ref: str) -> dict:
    payload = _valid_payload(source_ref)
    del payload["customer_vision"]  # 顶层字段缺失 → invalid_guidance
    return payload


def _seed_analysis(db_session, *, data: bytes, version_id: str | None = None):
    leader = User(
        username=f"retry.lead.{uuid4().hex}",
        display_name="重试负责人",
        role="project_lead",
        password_hash="x",
        must_change_password=False,
        is_active=True,
    )
    template = IndustryTemplate(name="重试模板", industry_name="制造")
    template_version = IndustryTemplateVersion(
        template=template, name=template.name, industry_name=template.industry_name,
        description="", version_number=1, status="published", published_by=leader,
    )
    project_id, file_id, real_version_id = uuid4().hex, uuid4().hex, uuid4().hex
    project = Project(
        id=project_id,
        project_code=f"FDE-RETRY-{uuid4().hex[:8]}",
        name="重试项目",
        enterprise_code="星河制造·制造·苏州",
        leader=leader,
        source_template_version=template_version,
        template_snapshot={},
        planned_start_date=date(2026, 8, 22),
    )
    project_file = ProjectFile(
        id=file_id, project=project, category="attachment",
        display_name="预调研表", description="", created_by=leader,
    )
    version = ProjectFileVersion(
        id=real_version_id, project_file=project_file, version_number=1,
        source="upload", original_filename="预调研表.docx",
        safe_filename="presurvey.docx", extension="docx", mime_type="",
        bucket="local", storage_key=f"projects/{project_id}/presurvey/presurvey.docx",
        size_bytes=len(data), etag="", sha256="", uploaded_by=leader,
        status="available", scan_status="clean", preview_status="none",
    )
    analysis_id = uuid4().hex
    analysis = ProjectGuidanceAnalysis(
        id=analysis_id, project_id=project_id, version_number=1,
        source_file_id=file_id,
        source_file_version_id=version_id or real_version_id,
        source_filename="预调研表.docx", source_sha256="",
        status="draft", analysis_state="queued", created_by_user_id=leader.id,
    )
    job = BackgroundJob(
        job_type="project.presurvey.analyze", target_id=analysis_id, status="pending",
    )
    # 与 test_file_previews 相同的分步 flush：世界实体先落库，分析行后插，
    # 避免一次性 add_all 时环形外键（project_files ↔ project_file_versions）
    # 干扰工作单元的插入排序。
    db_session.add_all([leader, template, template_version, project, project_file, version])
    db_session.flush()
    db_session.add_all([analysis, job])
    db_session.commit()
    if data:
        object_storage.current.put_stream(
            version.storage_key, io.BytesIO(data), "application/octet-stream", {}
        )
    return analysis, job, version


class _CallLog(list):
    """记录每次尝试的流内容与请求号（列表语义保持 len()/索引断言不变）。"""

    def __init__(self) -> None:
        super().__init__()
        self.request_ids: list[str] = []


def _install_fake_kimi(monkeypatch, steps):
    """按 steps 顺序驱动假客户端；记录每次调用的流内容与请求号。

    钉住两件事：每次尝试重新开流（上次尝试已消费），以及每次尝试用独立请求号
    （上游若按请求号去重，复用同一个 id 会让重试拿回第一次的坏结果）。
    """
    calls = _CallLog()

    class _FakeKimiClient:
        def __init__(self, **_kwargs):
            pass

        def analyze_docx_json(self, *, stream, filename, request_id, build_messages):
            index = min(len(calls), len(steps) - 1)
            content = stream.read()
            calls.append(content)
            calls.request_ids.append(request_id)
            return steps[index](content, filename)

    monkeypatch.setattr(guidance_jobs, "KimiFileClient", _FakeKimiClient)
    return calls


def _real_extract_then(payload):
    """走真实本地 DOCX 提取：畸形样本在这里抛可分类的 KimiError。"""
    def action(content: bytes, filename: str):
        from fde_api.ai.kimi import KimiFileClient as RealKimiClient
        RealKimiClient._extract_docx_locally(io.BytesIO(content), filename)
        return payload
    return action


def test_contract_failure_retries_once_then_succeeds(app, db_session, monkeypatch):
    generator = _load_generator()
    docx_bytes = generator._build_missing_sections()  # noqa: SLF001 - 测试直接取生成器产物
    analysis, job, version = _seed_analysis(db_session, data=docx_bytes)
    source_ref = f"kimi-file:{version.id}"
    steps = [
        lambda content, filename: _contract_violating_payload(source_ref),
        lambda content, filename: _valid_payload(source_ref),
    ]
    calls = _install_fake_kimi(monkeypatch, steps)

    with app.app_context():
        handle_presurvey_analysis(job)

    db_session.refresh(analysis)
    assert analysis.analysis_state == "ready"
    assert analysis.failure_code == ""
    assert analysis.customer_vision == "成为细分市场头部供应商"
    assert len(calls) == GUIDANCE_ANALYSIS_RETRY_LIMIT + 1
    # 每次尝试都拿到完整重开的流，而不是上一次消费后的空流。
    assert all(call == docx_bytes for call in calls)


def test_contract_failure_exhausts_retry_with_visible_hint(app, db_session, monkeypatch):
    docx_bytes = _load_generator()._build_missing_sections()  # noqa: SLF001
    analysis, job, version = _seed_analysis(db_session, data=docx_bytes)
    source_ref = f"kimi-file:{version.id}"
    steps = [
        lambda content, filename: _contract_violating_payload(source_ref),
        lambda content, filename: _contract_violating_payload(source_ref),
    ]
    calls = _install_fake_kimi(monkeypatch, steps)

    with app.app_context():
        handle_presurvey_analysis(job)

    db_session.refresh(analysis)
    assert analysis.analysis_state == "failed"
    assert analysis.failure_code == "ai_output_invalid"
    assert f"已自动重试 {GUIDANCE_ANALYSIS_RETRY_LIMIT} 次" in analysis.failure_message
    # 上限钉死：重试额度用尽即停，绝不第三次调用。
    assert len(calls) == GUIDANCE_ANALYSIS_RETRY_LIMIT + 1


def test_retryable_kimi_error_exhausts_and_keeps_its_code(app, db_session, monkeypatch):
    docx_bytes = _load_generator()._build_missing_sections()  # noqa: SLF001
    analysis, job, _version = _seed_analysis(db_session, data=docx_bytes)
    error = KimiError("ai_empty_response", "AI 未返回有效分析结果，请重试。", retryable=True)
    steps = [lambda content, filename: (_ for _ in ()).throw(error)]
    calls = _install_fake_kimi(monkeypatch, steps)

    with app.app_context():
        handle_presurvey_analysis(job)

    db_session.refresh(analysis)
    assert analysis.analysis_state == "failed"
    assert analysis.failure_code == "ai_empty_response"
    assert "已自动重试" in analysis.failure_message
    assert len(calls) == GUIDANCE_ANALYSIS_RETRY_LIMIT + 1


def test_non_retryable_kimi_error_fails_without_retry(app, db_session, monkeypatch):
    docx_bytes = _load_generator()._build_missing_sections()  # noqa: SLF001
    analysis, job, _version = _seed_analysis(db_session, data=docx_bytes)
    error = KimiError("ai_service_not_configured", "AI 服务尚未配置，请联系管理员。", retryable=False)
    steps = [lambda content, filename: (_ for _ in ()).throw(error)]
    calls = _install_fake_kimi(monkeypatch, steps)

    with app.app_context():
        handle_presurvey_analysis(job)

    db_session.refresh(analysis)
    assert analysis.analysis_state == "failed"
    assert analysis.failure_code == "ai_service_not_configured"
    assert "已自动重试" not in analysis.failure_message
    # 配置类失败重试也不会好：一次即败，不消耗重试额度。
    assert len(calls) == 1


def test_adversarial_fixture_fails_classified_through_real_extraction(app, db_session, monkeypatch):
    generator = _load_generator()
    # 空表格样本：真实本地提取路径抛 kimi_file_extract_failed。本地解析是字节的
    # 纯函数——同一份文件重试也解析不出内容，故该失败不可重试，一次即落 failed。
    analysis, job, _version = _seed_analysis(db_session, data=generator._build_empty_table())  # noqa: SLF001
    steps = [
        _real_extract_then(_valid_payload("unused")),
        _real_extract_then(_valid_payload("unused")),
    ]
    calls = _install_fake_kimi(monkeypatch, steps)

    with app.app_context():
        handle_presurvey_analysis(job)

    db_session.refresh(analysis)
    assert analysis.analysis_state == "failed"
    assert analysis.failure_code == "kimi_file_extract_failed"
    # 确定性故障不消耗重试额度：只调用一次，消息不带「已自动重试」。
    assert "已自动重试" not in analysis.failure_message
    assert len(calls) == 1


def test_source_missing_fails_before_any_ai_call(app, db_session, monkeypatch):
    docx_bytes = _load_generator()._build_missing_sections()  # noqa: SLF001
    analysis, job, _version = _seed_analysis(db_session, data=docx_bytes)
    calls = _install_fake_kimi(monkeypatch, [])
    # source_file_version_id 全链 RESTRICT：悬空引用不可能经 ORM 出现，该分支
    # 防的是外部维护路径删版本后才派发任务的竞争。这里把版本模型换成分析模型
    # 使 get() 必然落空，等价复现「版本查不到」。
    monkeypatch.setattr(guidance_jobs, "ProjectFileVersion", ProjectGuidanceAnalysis)

    with app.app_context():
        handle_presurvey_analysis(job)

    db_session.refresh(analysis)
    assert analysis.analysis_state == "failed"
    assert analysis.failure_code == "source_missing"
    assert calls == []


def test_unexpected_error_is_classified_and_job_stays_green(app, db_session, monkeypatch):
    docx_bytes = _load_generator()._build_missing_sections()  # noqa: SLF001
    analysis, job, _version = _seed_analysis(db_session, data=docx_bytes)

    def explode(content, filename):
        raise RuntimeError("object storage exploded with user data")

    calls = _install_fake_kimi(monkeypatch, [explode])

    with app.app_context():
        handle_presurvey_analysis(job)

    db_session.refresh(analysis)
    # 兜底分类：绝不卡在 analyzing（否则前端无限轮询），且消息不携带异常串。
    assert analysis.analysis_state == "failed"
    assert analysis.failure_code == "analysis_unexpected_error"
    assert "exploded" not in analysis.failure_message
    assert len(calls) == 1


def test_success_path_sets_ready_in_one_call(app, db_session, monkeypatch):
    docx_bytes = _load_generator()._build_missing_sections()  # noqa: SLF001
    analysis, job, version = _seed_analysis(db_session, data=docx_bytes)
    source_ref = f"kimi-file:{version.id}"
    calls = _install_fake_kimi(monkeypatch, [lambda content, filename: _valid_payload(source_ref)])

    with app.app_context():
        handle_presurvey_analysis(job)

    db_session.refresh(analysis)
    assert analysis.analysis_state == "ready"
    assert analysis.evidence_json == {source_ref: "预调研表第一段"}
    assert len(calls) == 1


def test_retry_limit_is_one_and_pinned():
    # 语义上限的独立钉子：改上限必须有意识地改这里（连同上面的调用次数断言）。
    assert GUIDANCE_ANALYSIS_RETRY_LIMIT == 1


def test_each_attempt_uses_a_distinct_request_id(app, db_session, monkeypatch):
    """每次尝试用独立请求号：上游按 id 去重会让重试拿回第一次的坏结果。"""
    docx_bytes = _load_generator()._build_missing_sections()  # noqa: SLF001
    analysis, job, version = _seed_analysis(db_session, data=docx_bytes)
    source_ref = f"kimi-file:{version.id}"
    steps = [
        lambda content, filename: _contract_violating_payload(source_ref),
        lambda content, filename: _valid_payload(source_ref),
    ]
    calls = _install_fake_kimi(monkeypatch, steps)

    with app.app_context():
        handle_presurvey_analysis(job)

    db_session.refresh(analysis)
    assert analysis.analysis_state == "ready"
    assert len(calls.request_ids) == 2
    assert len(set(calls.request_ids)) == 2
    assert all(request_id.startswith(job.id) for request_id in calls.request_ids)


def test_transient_failure_backs_off_before_retry(app, db_session, monkeypatch):
    """限流/超时类瞬时错误重试前要退避；契约违反不退避（概率问题立即重试）。"""
    slept: list[float] = []
    monkeypatch.setattr(guidance_jobs.time, "sleep", lambda seconds: slept.append(seconds))

    docx_bytes = _load_generator()._build_missing_sections()  # noqa: SLF001
    analysis, job, _version = _seed_analysis(db_session, data=docx_bytes)
    error = KimiError("ai_rate_limited", "AI 请求过于频繁，请稍后重试。", retryable=True)
    steps = [lambda content, filename: (_ for _ in ()).throw(error)]
    _install_fake_kimi(monkeypatch, steps)

    with app.app_context():
        handle_presurvey_analysis(job)

    db_session.refresh(analysis)
    assert analysis.analysis_state == "failed"
    assert analysis.failure_code == "ai_rate_limited"
    assert slept == [guidance_jobs.RETRY_BACKOFF_SECONDS]


def test_contract_failure_does_not_back_off(app, db_session, monkeypatch):
    """契约违反是概率性问题：立即重试，不加退避（退避只会白白拉长等待）。"""
    slept: list[float] = []
    monkeypatch.setattr(guidance_jobs.time, "sleep", lambda seconds: slept.append(seconds))

    docx_bytes = _load_generator()._build_missing_sections()  # noqa: SLF001
    analysis, job, version = _seed_analysis(db_session, data=docx_bytes)
    source_ref = f"kimi-file:{version.id}"
    steps = [
        lambda content, filename: _contract_violating_payload(source_ref),
        lambda content, filename: _valid_payload(source_ref),
    ]
    _install_fake_kimi(monkeypatch, steps)

    with app.app_context():
        handle_presurvey_analysis(job)

    db_session.refresh(analysis)
    assert analysis.analysis_state == "ready"
    assert slept == []


def test_non_retryable_terminal_error_does_not_advise_reinitiation(app, db_session, monkeypatch):
    """终态错误不可重试时，消息不许劝用户「重新发起分析」（重试无意义）。"""
    docx_bytes = _load_generator()._build_missing_sections()  # noqa: SLF001
    analysis, job, _version = _seed_analysis(db_session, data=docx_bytes)
    # 第一次可重试、第二次不可重试：终态是配置类失败。
    first = KimiError("ai_rate_limited", "AI 请求过于频繁，请稍后重试。", retryable=True)
    second = KimiError("ai_authentication_failed", "AI 服务认证失败，请检查服务端配置。", retryable=False)
    steps = [
        lambda content, filename: (_ for _ in ()).throw(first),
        lambda content, filename: (_ for _ in ()).throw(second),
    ]
    _install_fake_kimi(monkeypatch, steps)

    with app.app_context():
        handle_presurvey_analysis(job)

    db_session.refresh(analysis)
    assert analysis.analysis_state == "failed"
    assert analysis.failure_code == "ai_authentication_failed"
    assert "已自动重试 1 次" in analysis.failure_message
    assert "请重新发起分析" not in analysis.failure_message


def test_missing_storage_object_is_classified_not_unexpected(app, db_session, monkeypatch):
    """存储对象被删是确定性故障：单独分类，不混进「未预期错误」。"""
    docx_bytes = _load_generator()._build_missing_sections()  # noqa: SLF001
    analysis, job, _version = _seed_analysis(db_session, data=docx_bytes)

    def explode(content, filename):
        raise StorageNotFoundError("object_not_found")

    calls = _install_fake_kimi(monkeypatch, [explode])

    with app.app_context():
        handle_presurvey_analysis(job)

    db_session.refresh(analysis)
    assert analysis.analysis_state == "failed"
    assert analysis.failure_code == guidance_jobs.SOURCE_OBJECT_MISSING_CODE
    assert "重新上传" in analysis.failure_message
    assert len(calls) == 1


def test_unexpected_failure_keeps_the_background_job_green(app, db_session, monkeypatch):
    """未预期异常被 handler 吞掉：任务本身必须成功（worker 按 handler 返回决定终态）。"""
    docx_bytes = _load_generator()._build_missing_sections()  # noqa: SLF001
    analysis, job, _version = _seed_analysis(db_session, data=docx_bytes)

    def explode(content, filename):
        raise RuntimeError("object storage exploded with user data")

    _install_fake_kimi(monkeypatch, [explode])

    with app.app_context():
        assert run_job(job.id) == "succeeded"

    db_session.refresh(job)
    db_session.refresh(analysis)
    assert job.status == "succeeded"
    assert analysis.analysis_state == "failed"
    assert analysis.failure_code == guidance_jobs.UNEXPECTED_FAILURE_CODE


def test_duplicate_delivery_of_a_failed_analysis_does_not_rerun_ai(app, db_session, monkeypatch):
    """重复投递到已终态（failed）的分析不得二次调用 AI 覆盖结论。"""
    docx_bytes = _load_generator()._build_missing_sections()  # noqa: SLF001
    analysis, job, version = _seed_analysis(db_session, data=docx_bytes)
    source_ref = f"kimi-file:{version.id}"
    calls = _install_fake_kimi(monkeypatch, [lambda content, filename: _valid_payload(source_ref)])

    # 先把分析置为 failed（模拟上一次执行已终态）
    analysis.analysis_state = "failed"
    analysis.failure_code = "ai_output_invalid"
    analysis.failure_message = "上一次执行失败。"
    db_session.commit()

    with app.app_context():
        handle_presurvey_analysis(job)

    db_session.refresh(analysis)
    assert analysis.analysis_state == "failed"
    assert analysis.failure_code == "ai_output_invalid"
    assert calls == []


def test_contract_retry_does_not_double_redaction_entries(app, db_session, monkeypatch):
    """CR-051：契约失败重试成功后，复核清单条目不翻倍（sink 重试前清空）。"""
    from docx import Document

    from fde_api.guidance.models import REDACTION_EVENT_TYPE
    from fde_api.workbench.models import OperationEvent

    buf = io.BytesIO()
    doc = Document()
    doc.add_paragraph("与合成测试集团聊排程。")
    doc.save(buf)
    docx_bytes = buf.getvalue()
    analysis, job, version = _seed_analysis(db_session, data=docx_bytes)
    source_ref = f"kimi-file:{version.id}"

    calls = _CallLog()

    class _FakeKimiClient:
        """真 client 语义：构造请求前先 build（sink 在此逐轮累积）。"""

        def __init__(self, **_kwargs):
            pass

        def analyze_docx_json(self, *, stream, filename, request_id, build_messages):
            index = len(calls)
            content = stream.read()
            calls.append(content)
            # 真 client 语义：本地抽取文本后交给 build_messages（sink 在此累积）
            from fde_api.ai.kimi import KimiFileClient as RealKimiClient
            text = RealKimiClient._extract_docx_locally(io.BytesIO(content), filename)
            build_messages(text)
            if index == 0:
                return _contract_violating_payload(source_ref)
            return _valid_payload(source_ref)

    monkeypatch.setattr(guidance_jobs, "KimiFileClient", _FakeKimiClient)

    with app.app_context():
        handle_presurvey_analysis(job)

    db_session.refresh(analysis)
    assert analysis.analysis_state == "ready"
    assert len(calls) == GUIDANCE_ANALYSIS_RETRY_LIMIT + 1
    events = db_session.query(OperationEvent).filter_by(
        target_type="project_guidance_analysis", target_id=analysis.id,
        event_type=REDACTION_EVENT_TYPE,
    ).all()
    assert len(events) == 1
    # QR-133 指纹化：条目只含 name_hash（零真名）——「合成测试集团」指纹恰 1 条。
    hashes = [entry["name_hash"] for entry in events[0].changes["entries"]]
    assert hashes.count(redaction_name_hash("合成测试集团")) == 1, (
        f"重试不得使复核条目翻倍：{hashes}"
    )
    assert "合成测试集团" not in json.dumps(events[0].changes, ensure_ascii=False, default=str)
