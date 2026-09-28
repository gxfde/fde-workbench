"""Structural QA for generated DOCX.

``inspect_generated_docx`` validates that a rendered DOCX is a well-formed
Office Open XML archive, that no residual Jinja placeholder tokens (``{{`` /
``{%``) survive rendering, and that the required content sections are present.
It is deliberately non-throwing: every problem is collected as a
:class:`DocumentQaError` on the returned :class:`DocumentQaResult`, so the
caller can decide whether a failure blocks promotion of the generated file.

``extract_docx_xml_text`` is a thin helper that returns every bit of text from a
DOCX stream (body paragraphs, tables, headers and footers) as a single string.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from typing import BinaryIO, Sequence

from docx import Document

#: Residual Jinja output / statement tokens that must never survive rendering.
_RESIDUAL_TOKEN_RE = (r"{{", "{%", "【待填写：")


@dataclass
class DocumentQaError:
    """One structural QA problem found in a generated document."""

    code: str
    message: str


@dataclass
class DocumentQaResult:
    """The non-throwing result of inspecting a generated DOCX."""

    errors: list[DocumentQaError] = field(default_factory=list)
    #: The required sections that WERE found in the document.
    sections: list[str] = field(default_factory=list)
    text: str = ""


def extract_docx_xml_text(stream: BinaryIO) -> str:
    """Return all text (body, tables, headers, footers) from a DOCX stream."""
    document = Document(io.BytesIO(_read_bytes(stream)))
    texts: list[str] = []

    def collect_paragraphs(paragraphs) -> None:
        for paragraph in paragraphs:
            if paragraph.text:
                texts.append(paragraph.text)

    def collect_table(table, seen_cells: set[object]) -> None:
        for row in table.rows:
            for cell in row.cells:
                cell_key = cell._tc if hasattr(cell, "_tc") else cell
                if cell_key in seen_cells:
                    continue
                seen_cells.add(cell_key)
                collect_paragraphs(cell.paragraphs)
                for nested in cell.tables:
                    collect_table(nested, seen_cells)

    collect_paragraphs(document.paragraphs)
    seen: set[object] = set()
    for table in document.tables:
        collect_table(table, seen)
    for section in document.sections:
        if section.header is not None:
            collect_paragraphs(section.header.paragraphs)
        if section.footer is not None:
            collect_paragraphs(section.footer.paragraphs)
    return "\n".join(texts)


def inspect_generated_docx(
    stream: BinaryIO, required_sections: Sequence[str]
) -> DocumentQaResult:
    """Validate a rendered DOCX and return a non-throwing :class:`DocumentQaResult`.

    A document is accepted when it is a valid OOXML archive, contains no residual
    ``{{`` / ``{%`` placeholder tokens, and every ``required_sections`` name
    appears in the extracted text. Faults are collected as
    :class:`DocumentQaError` entries and never raised.
    """
    errors: list[DocumentQaError] = []
    data = _read_bytes(stream)

    if not _is_ooxml_archive(data):
        errors.append(
            DocumentQaError("invalid_docx", "The file is not a valid DOCX archive.")
        )
        return DocumentQaResult(errors=errors, text="")

    try:
        document = Document(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001 - malformed archives report as QA errors
        errors.append(
            DocumentQaError("invalid_docx", f"The document could not be read: {exc}.")
        )
        return DocumentQaResult(errors=errors, text="")

    text = extract_docx_xml_text(io.BytesIO(data))

    if any(token in text for token in _RESIDUAL_TOKEN_RE):
        errors.append(
            DocumentQaError(
                "template_placeholder_remaining",
                "Document still contains an unresolved template placeholder.",
            )
        )

    sections: list[str] = []
    for section in required_sections:
        if section in text:
            sections.append(section)
        else:
            errors.append(
                DocumentQaError(
                    "missing_required_section",
                    f"The required section '{section}' is missing from the document.",
                )
            )

    _check_table_consistency(document, errors)

    return DocumentQaResult(errors=errors, sections=sections, text=text)


def _read_bytes(stream: BinaryIO) -> bytes:
    if hasattr(stream, "seek"):
        try:
            stream.seek(0)
        except Exception:  # noqa: BLE001 - seek is best-effort for non-file streams
            pass
    data = stream.read()
    return data if isinstance(data, bytes) else bytes(data)


def _is_ooxml_archive(data: bytes) -> bool:
    if not data.startswith(b"PK"):
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = archive.namelist()
    except (zipfile.BadZipFile, ValueError):
        return False
    return "word/document.xml" in names


def _check_table_consistency(document, errors: list[DocumentQaError]) -> None:
    """Leniently flag tables whose rows have genuinely inconsistent cell counts.

    Horizontal merges are accounted for by python-docx (merged cells repeat), so
    a difference in ``len(row.cells)`` across the rows of a table is a structural
    anomaly. Merged-vertical cells are common in generated documents, so this
    check is deliberately conservative and only reports when at least one cell in
    the offending table carries no ``gridSpan``/``vMerge`` marker.
    """
    for index, table in enumerate(document.tables):
        rows = list(table.rows)
        if len(rows) < 2:
            continue
        counts = [len(row.cells) for row in rows]
        if len(set(counts)) <= 1:
            continue
        if any(_has_merge_marker(row) for row in rows):
            continue
        errors.append(
            DocumentQaError(
                "inconsistent_table",
                f"Table {index + 1} has rows with inconsistent column counts.",
            )
        )


def _has_merge_marker(row) -> bool:
    for cell in row.cells:
        tc = getattr(cell, "_tc", None)
        if tc is None:
            continue
        xml = tc.xml
        if "gridSpan" in xml or "vMerge" in xml:
            return True
    return False
