from __future__ import annotations

from datetime import UTC, datetime

from flask import current_app

from fde_api.ai.kimi import KimiError, KimiFileClient
from fde_api.extensions import db, object_storage
from fde_api.files.models import ProjectFileVersion
from fde_api.guidance.ai_prompt import build_kimi_presurvey_analysis_messages
from fde_api.guidance.ai_schema import GuidanceContractError, LIST_FIELDS, validate_guidance_output
from fde_api.guidance.models import ProjectGuidanceAnalysis
from fde_api.jobs.handlers import register_handler


def handle_presurvey_analysis(job) -> None:
    session = db.session()
    try:
        analysis = session.get(ProjectGuidanceAnalysis, job.target_id)
        if analysis is None or analysis.analysis_state in {"ready", "cancelled"}:
            return
        analysis.analysis_state = "extracting"
        session.commit()
        version = session.get(ProjectFileVersion, analysis.source_file_version_id)
        if version is None:
            _fail(session, analysis, "source_missing", "预调研源文件不存在。")
            return
        analysis.analysis_state = "analyzing"
        session.commit()
        settings = current_app.config["SETTINGS"]
        client = KimiFileClient(
            base_url=settings.kimi_base_url,
            api_key=settings.kimi_project_presurvey_api_key,
            model=settings.kimi_project_presurvey_model,
            timeout_seconds=settings.kimi_timeout_seconds,
        )
        source_ref = f"kimi-file:{analysis.source_file_version_id}"
        with object_storage.current.open_stream(version.storage_key) as stream:
            payload = client.analyze_docx_json(
                stream=stream,
                filename=analysis.source_filename,
                request_id=job.id,
                build_messages=lambda content: build_kimi_presurvey_analysis_messages(content, source_ref),
            )
        draft = validate_guidance_output(payload, source_refs={source_ref})
        analysis.customer_vision = draft["customer_vision"]
        analysis.current_phase_objective = draft["current_phase_objective"]
        analysis.executive_summary = draft["executive_summary"]
        analysis.evidence_json = draft["evidence"]
        for field in LIST_FIELDS:
            setattr(analysis, f"{field}_json", draft[field])
        analysis.ai_model = settings.kimi_project_presurvey_model
        analysis.ai_generated_at = datetime.now(UTC)
        analysis.analysis_state = "ready"
        analysis.failure_code = ""
        analysis.failure_message = ""
        analysis.version += 1
        session.commit()
    except KimiError as error:
        _safe_fail(session, job.target_id, error.code, error.public_message)
    except GuidanceContractError:
        _safe_fail(session, job.target_id, "ai_output_invalid", "AI 返回的项目指引格式不正确，请重试。")
    finally:
        session.close()


def _safe_fail(session, analysis_id: str, code: str, message: str) -> None:
    session.rollback()
    row = session.get(ProjectGuidanceAnalysis, analysis_id)
    if row is not None:
        _fail(session, row, code, message)


def _fail(session, row: ProjectGuidanceAnalysis, code: str, message: str) -> None:
    row.analysis_state = "failed"
    row.failure_code = code
    row.failure_message = message
    row.version += 1
    session.commit()


def register_presurvey_analysis_handler() -> None:
    register_handler("project.presurvey.analyze", handle_presurvey_analysis)
