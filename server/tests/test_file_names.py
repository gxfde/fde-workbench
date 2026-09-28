import pytest

from fde_api.files.names import (
    FileNameError,
    attachment_key,
    document_key,
    preview_key,
    safe_filename,
    temporary_key,
)


def test_attachment_key_is_project_scoped_and_immutable():
    assert (
        attachment_key("p1", "f1", "v1", "需求 文档.docx")
        == "projects/p1/attachments/f1/versions/v1/需求_文档.docx"
    )


def test_document_key_and_preview_key_shapes():
    assert (
        document_key("p1", "d1", "v2", "SOW.docx")
        == "projects/p1/documents/d1/versions/v2/SOW.docx"
    )
    assert preview_key("p1", "v1", "pv9") == "projects/p1/previews/v1/pv9.pdf"


def test_temporary_key_is_under_temporary_prefix():
    assert (
        temporary_key("p1", "up1", "a.txt")
        == "projects/p1/temporary/up1/a.txt"
    )


def test_safe_filename_normalizes_spaces_and_paths():
    assert safe_filename("需求 文档.docx") == "需求_文档.docx"
    assert safe_filename("a/b\\c.txt") == "a_b_c.txt"
    assert safe_filename("  file.pdf  ") == "file.pdf"


def test_safe_filename_rejects_executable_extensions():
    for filename in ("run.exe", "setup.dmg", "job.sh", "macro.docm"):
        with pytest.raises(FileNameError, match="file_type_not_allowed"):
            safe_filename(filename)


def test_safe_filename_requires_a_name():
    with pytest.raises(FileNameError, match="file_name_required"):
        safe_filename("")
