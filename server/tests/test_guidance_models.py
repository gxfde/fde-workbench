from fde_api.guidance.models import (
    GUIDANCE_ANALYSIS_STATES,
    GUIDANCE_STATUSES,
    ProjectGuidanceAnalysis,
    ProjectPresurveySource,
)


def test_guidance_models_define_versioned_source_and_review_states():
    source = ProjectPresurveySource(
        project_id="project-1",
        project_file_id="file-1",
        current_file_version_id="version-1",
    )
    analysis = ProjectGuidanceAnalysis(
        project_id="project-1",
        source_file_id="file-1",
        source_file_version_id="version-1",
        source_filename="survey.docx",
        source_sha256="a" * 64,
        version_number=1,
        status="draft",
        analysis_state="queued",
        created_by_user_id="user-1",
    )

    assert source.__table__.c.version.default.arg == 1
    assert analysis.__table__.c.version.default.arg == 1
    assert GUIDANCE_STATUSES == ("draft", "confirmed", "superseded")
    assert "ready" in GUIDANCE_ANALYSIS_STATES
