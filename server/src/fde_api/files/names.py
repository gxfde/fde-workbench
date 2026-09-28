"""Stable, project-scoped object key builders for the file subsystem."""

from __future__ import annotations

import re
import unicodedata
from pathlib import PurePosixPath


REJECTED_EXTENSIONS = frozenset(
    {
        ".exe",
        ".dmg",
        ".pkg",
        ".sh",
        ".js",
        ".py",
        ".docm",
        ".xlsm",
        ".pptm",
        ".bat",
        ".cmd",
        ".com",
        ".scr",
        ".msi",
    }
)

_SAFE_NAME_RE = re.compile(r"[^\w.\-]+", re.UNICODE)
_MAX_SAFE_FILENAME = 180


class FileNameError(ValueError):
    """Raised when a filename/extension is rejected for storage."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def extension_of(filename: str) -> str:
    return PurePosixPath(filename).suffix.lower()


def safe_filename(name: str) -> str:
    """Normalize a client filename to a storage-safe, reversible alias.

    Keeps Chinese and other unicode word characters, replaces path breaks and
    punctuation with `_`, and rejects executable/macro-enabled extensions.
    """
    if not isinstance(name, str) or not name:
        raise FileNameError("file_name_required")
    normalized = unicodedata.normalize("NFKC", name).replace("/", "_").replace("\\", "_")
    cleaned = _SAFE_NAME_RE.sub("_", normalized).strip(" ._")
    if not cleaned or len(cleaned) > _MAX_SAFE_FILENAME:
        raise FileNameError("file_name_invalid")
    if extension_of(cleaned) in REJECTED_EXTENSIONS:
        raise FileNameError("file_type_not_allowed")
    return cleaned


def temporary_key(project_id: str, upload_id: str, filename: str) -> str:
    return f"projects/{project_id}/temporary/{upload_id}/{safe_filename(filename)}"


def attachment_key(
    project_id: str, file_id: str, version_id: str, filename: str
) -> str:
    return (
        f"projects/{project_id}/attachments/{file_id}/versions/{version_id}/"
        f"{safe_filename(filename)}"
    )


def document_key(
    project_id: str, document_id: str, version_id: str, filename: str
) -> str:
    return (
        f"projects/{project_id}/documents/{document_id}/versions/{version_id}/"
        f"{safe_filename(filename)}"
    )


def preview_key(project_id: str, source_version_id: str, preview_version_id: str) -> str:
    return (
        f"projects/{project_id}/previews/{source_version_id}/{preview_version_id}.pdf"
    )
