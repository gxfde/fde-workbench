from fde_api.documents.mapping import (
    ALLOWED_DOCUMENT_ROOTS,
    MappingIssue,
    MappingValidationError,
    validate_mapping,
)
from fde_api.documents.template_parser import TemplateScan

RESEARCH_DEFINITION = {
    "forms": {
        "role_profile": {"form_key": "role_profile", "subject_type": "role"},
        "process_map": {"form_key": "process_map", "subject_type": "process"},
        "opportunity_scan": {
            "form_key": "opportunity_scan",
            "subject_type": "opportunity",
        },
    }
}


def _valid_mapping():
    return {
        "document_type": "sow",
        "research_keys": [
            {"form_key": "role_profile", "subject_type": "role"},
            {"form_key": "process_map", "subject_type": "process"},
        ],
        "field_map": {
            "{{ custom_label }}": "research.role_profile.name",
        },
        "sections": [],
    }


def test_mapping_accepts_known_placeholders_and_forms():
    scan = TemplateScan(
        placeholders=["{{ project.name }}", "{{ custom_label }}"],
        issues=[],
        tables=[],
    )
    issues = validate_mapping(scan, _valid_mapping(), RESEARCH_DEFINITION)
    assert issues == []


def test_mapping_rejects_unknown_placeholder():
    scan = TemplateScan(
        placeholders=["{{ project.name }}", "{{ unknown_thing }}"],
        issues=[],
        tables=[],
    )
    mapping = _valid_mapping()
    issues = validate_mapping(scan, mapping, RESEARCH_DEFINITION)
    assert issues, "expected at least one issue"
    assert all(issue.code == "unknown_placeholder" for issue in issues)
    assert all("unknown_thing" in issue.message for issue in issues)


def test_mapping_rejects_missing_research_form():
    scan = TemplateScan(placeholders=["{{ project.name }}"], issues=[], tables=[])
    mapping = _valid_mapping()
    mapping["research_keys"].append(
        {"form_key": "ghost_form", "subject_type": "role"}
    )
    issues = validate_mapping(scan, mapping, RESEARCH_DEFINITION)
    assert issues
    assert any(issue.code == "missing_research_form" for issue in issues)
    assert any("ghost_form" in issue.message for issue in issues)


def test_mapping_rejects_unsupported_subject_type():
    scan = TemplateScan(placeholders=["{{ project.name }}"], issues=[], tables=[])
    mapping = _valid_mapping()
    mapping["research_keys"].append(
        {"form_key": "role_profile", "subject_type": "galaxy"}
    )
    issues = validate_mapping(scan, mapping, RESEARCH_DEFINITION)
    assert any(issue.code == "unsupported_subject_type" for issue in issues)


def test_mapping_allowed_document_roots_match_parser():
    assert ALLOWED_DOCUMENT_ROOTS == {
        "project",
        "enterprise",
        "research",
        "subjects",
        "tasks",
        "members",
        "document",
    }


def test_mapping_validation_error_carries_issues():
    error = MappingValidationError([MappingIssue("code", "msg", "path")])
    assert error.issues and error.issues[0].code == "code"
