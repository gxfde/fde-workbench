from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import BinaryIO, Mapping, Protocol, runtime_checkable
from urllib.parse import quote


MAX_SIGNATURE_SECONDS = 300
MAX_MULTIPART_PARTS = 10_000
_METADATA_KEY = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_SLASH_CONFUSABLES = frozenset(
    {
        "⁄",  # fraction slash
        "∕",  # division slash
        "╱",  # box drawings light diagonal
        "⧵",  # reverse solidus operator
        "⧸",  # big solidus
        "⧹",  # big reverse solidus
        "﹨",  # small reverse solidus
        "／",  # fullwidth solidus
        "＼",  # fullwidth reverse solidus
    }
)
_DISALLOWED_UNICODE_CATEGORIES = frozenset({"Cc", "Cf", "Zl", "Zp"})


class StorageError(RuntimeError):
    """A stable, credential-free object storage failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class StorageNotFoundError(StorageError):
    pass


@dataclass(frozen=True, slots=True)
class StoredObject:
    key: str
    size: int
    etag: str
    content_type: str
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MultipartUpload:
    key: str
    upload_id: str


@dataclass(frozen=True, slots=True)
class UploadedPart:
    part_number: int
    etag: str


@runtime_checkable
class ObjectStorage(Protocol):
    def begin_multipart(self, key: str, content_type: str) -> MultipartUpload: ...

    def sign_part(
        self,
        key: str,
        upload_id: str,
        part_number: int,
        expires_seconds: int = MAX_SIGNATURE_SECONDS,
    ) -> str: ...

    def complete_multipart(
        self, key: str, upload_id: str, parts: list[UploadedPart]
    ) -> StoredObject: ...

    def abort_multipart(self, key: str, upload_id: str) -> None: ...

    def put_stream(
        self,
        key: str,
        stream: BinaryIO,
        content_type: str,
        metadata: Mapping[str, str],
    ) -> StoredObject: ...

    def open_stream(self, key: str) -> BinaryIO: ...

    def head(self, key: str) -> StoredObject: ...

    def copy(self, source_key: str, target_key: str) -> StoredObject: ...

    def sign_download(
        self,
        key: str,
        filename: str,
        expires_seconds: int = MAX_SIGNATURE_SECONDS,
    ) -> str: ...

    def delete(self, key: str) -> None: ...


def validate_object_key(key: str) -> str:
    if not isinstance(key, str) or not key or key.startswith("/"):
        raise StorageError("invalid_object_key")
    if not _is_rejectively_canonical(key):
        raise StorageError("invalid_object_key")

    parts = key.split("/")
    allowed_root = parts[0] in {"projects", "document-templates"}
    if len(parts) < 3 or not allowed_root or any(
        not part or part in {".", ".."} for part in parts
    ):
        raise StorageError("invalid_object_key")
    return key


def validate_project_key(project_id: str, key: str) -> str:
    if not _is_safe_segment(project_id):
        raise StorageError("invalid_object_key")
    validate_object_key(key)
    parts = key.split("/", 2)
    if parts[0] != "projects" or parts[1] != project_id:
        raise StorageError("invalid_object_key")
    return key


def validate_expiration(expires_seconds: int) -> int:
    if (
        isinstance(expires_seconds, bool)
        or not isinstance(expires_seconds, int)
        or not 1 <= expires_seconds <= MAX_SIGNATURE_SECONDS
    ):
        raise StorageError("invalid_expiration")
    return expires_seconds


def validate_part_number(part_number: int) -> int:
    if (
        isinstance(part_number, bool)
        or not isinstance(part_number, int)
        or not 1 <= part_number <= MAX_MULTIPART_PARTS
    ):
        raise StorageError("invalid_part_number")
    return part_number


def normalize_parts(parts: list[UploadedPart]) -> list[UploadedPart]:
    if not parts:
        raise StorageError("invalid_parts")
    normalized: list[UploadedPart] = []
    numbers: set[int] = set()
    for part in parts:
        validate_part_number(part.part_number)
        if part.part_number in numbers or not isinstance(part.etag, str):
            raise StorageError("invalid_parts")
        etag = part.etag
        if len(etag) >= 2 and etag.startswith('"') and etag.endswith('"'):
            etag = etag[1:-1]
        if not etag:
            raise StorageError("invalid_parts")
        numbers.add(part.part_number)
        normalized.append(UploadedPart(part.part_number, etag))
    return sorted(normalized, key=lambda part: part.part_number)


def normalize_metadata(metadata: Mapping[str, str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, value in metadata.items():
        lowered = key.lower()
        if not _METADATA_KEY.fullmatch(lowered):
            raise StorageError("invalid_metadata")
        if not isinstance(value, str) or _has_control_character(value):
            raise StorageError("invalid_metadata")
        normalized[lowered] = value
    return normalized


def content_disposition(filename: str) -> str:
    if (
        not isinstance(filename, str)
        or not filename
        or _has_control_character(filename)
    ):
        raise StorageError("invalid_download_filename")
    return f"attachment; filename*=UTF-8''{quote(filename, safe='')}"


def _is_rejectively_canonical(value: str) -> bool:
    return (
        "%" not in value
        and "\\" not in value
        and not any(character in _SLASH_CONFUSABLES for character in value)
        and unicodedata.normalize("NFKC", value) == value
        and not any(
            unicodedata.category(character) in _DISALLOWED_UNICODE_CATEGORIES
            for character in value
        )
    )


def _is_safe_segment(value: str) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value not in {".", ".."}
        and "/" not in value
        and _is_rejectively_canonical(value)
    )


def _has_control_character(value: str) -> bool:
    return any(
        unicodedata.category(character) in _DISALLOWED_UNICODE_CATEGORIES
        for character in value
    )
