"""Sanitization and rendering for the rich-text document model.

``sanitize_rich_text`` accepts a ProseMirror-shaped ``{"type": "doc", "content":
[...]}`` payload, whitelists block types and formatting marks, and uses
``bleach`` to strip scripts, event-handler attributes and unsafe protocols. It
returns a typed, deterministic :class:`RichTextDocument`.

``render_rich_text`` converts that typed tree into plain render-ready block
dicts that the DOCX generator consumes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import bleach

from fde_api.documents.template_parser import ALLOWED_BLOCK_TYPES, ALLOWED_MARKS

# Bleach configuration: only allow structural text tags, only carry over the
# ``href`` / ``title`` attributes and only allow http/https/mailto protocols.
ALLOWED_TAGS = [
    "b",
    "i",
    "strong",
    "em",
    "p",
    "br",
    "ul",
    "ol",
    "li",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
]
ALLOWED_ATTRIBUTES = {"*": ["href", "title"]}
ALLOWED_PROTOCOLS = {"http", "https", "mailto"}

# The set of block types whose ``content`` is a flat string (paragraph/heading).
_TEXT_BLOCK_TYPES = frozenset({"paragraph", "heading"})
# The set of block types whose ``content`` is a list of strings (lists).
_LIST_BLOCK_TYPES = frozenset({"ordered_list", "bullet_list"})
# Table content is a list of rows, each a list of cell strings.
_TABLE_BLOCK_TYPE = "table"

# The block types that may carry a ``src`` / ``srcset`` / ``href`` we must gate
# on a safe protocol. ``image`` / ``iframe`` / ``object`` are never whitelisted,
# so they are dropped before this check is reached, but we keep the gate explicit.
_LINKED_BLOCK_TYPES = frozenset({"paragraph", "heading", "ordered_list", "bullet_list", "table"})

# Prefixes that count as "project-file" links and are allowed alongside the
# protocol allowlist.
_PROJECT_FILE_PREFIXES = ("/files/", "files/", "project-files/", "projects/")


class RichTextSanitizationError(Exception):
    """Raised when a rich-text payload is not a well-formed document."""


@dataclass
class RichTextBlock:
    """One sanitized block of the rich-text document."""

    type: str
    content: Any
    marks: list[str] = field(default_factory=list)


@dataclass
class RichTextDocument:
    """The typed, sanitized rich-text document."""

    blocks: tuple[RichTextBlock, ...] = ()


def _clean_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return bleach.clean(
        value,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        protocols=ALLOWED_PROTOCOLS,
        strip=True,
    ).strip()


def _is_safe_protocol(href: object) -> bool:
    if not isinstance(href, str):
        return False
    href = href.strip().lower()
    if any(href.startswith(prefix) for prefix in _PROJECT_FILE_PREFIXES):
        return True
    if not href:
        return False
    if href.startswith("#"):
        return True
    if href.startswith("/"):
        return True
    for protocol in ALLOWED_PROTOCOLS:
        if href.startswith(protocol + "://"):
            return True
    return False


def _filters_on_block(block: dict[str, Any]) -> bool:
    """Return True when the block must be dropped for carrying an unsafe link."""
    for key in ("src", "srcset", "href"):
        value = block.get(key)
        if isinstance(value, str) and value.strip():
            if not _is_safe_protocol(value):
                return True
    return False


def _sanitize_marks(block: dict[str, Any]) -> list[str]:
    raw = block.get("marks", [])
    if not isinstance(raw, list):
        return []
    seen: set[str] = set()
    result: list[str] = []
    for mark in raw:
        if isinstance(mark, str) and mark in ALLOWED_MARKS and mark not in seen:
            seen.add(mark)
            result.append(mark)
    return result


def sanitize_rich_text(value: Any) -> RichTextDocument:
    """Sanitize a JSON-ish rich-text document into a :class:`RichTextDocument`.

    Only whitelisted block types survive; ``script``, ``image``, ``iframe``,
    ``object`` and any block pointing at a non-http/https/mailto/project-file
    link are dropped. Blocks that become empty after cleaning are dropped too.
    """

    if not isinstance(value, dict):
        raise RichTextSanitizationError("rich text must be an object")
    if value.get("type") != "doc":
        raise RichTextSanitizationError("rich text must be a document")
    content = value.get("content")
    if not isinstance(content, list):
        raise RichTextSanitizationError("rich text document content must be a list")

    blocks: list[RichTextBlock] = []

    for raw_block in content:
        if not isinstance(raw_block, dict):
            continue
        block_type = raw_block.get("type")
        # Drop disallowed block types outright.
        if block_type not in ALLOWED_BLOCK_TYPES:
            continue
        if _filters_on_block(raw_block):
            continue

        marks = _sanitize_marks(raw_block)

        if block_type in _TEXT_BLOCK_TYPES:
            cleaned = _clean_text(raw_block.get("content"))
            if not cleaned:
                continue
            blocks.append(RichTextBlock(type=block_type, content=cleaned, marks=marks))
        elif block_type in _LIST_BLOCK_TYPES:
            raw_items = raw_block.get("content")
            if not isinstance(raw_items, list):
                continue
            cleaned_items: list[str] = []
            for item in raw_items:
                cleaned_item = _clean_text(item)
                if cleaned_item:
                    cleaned_items.append(cleaned_item)
            if not cleaned_items:
                continue
            blocks.append(
                RichTextBlock(type=block_type, content=cleaned_items, marks=marks)
            )
        elif block_type == _TABLE_BLOCK_TYPE:
            raw_rows = raw_block.get("content")
            if not isinstance(raw_rows, list):
                continue
            cleaned_rows: list[list[str]] = []
            for row in raw_rows:
                if not isinstance(row, list):
                    continue
                cleaned_row: list[str] = []
                for cell in row:
                    cleaned_cell = _clean_text(cell)
                    if cleaned_cell:
                        cleaned_row.append(cleaned_cell)
                if cleaned_row:
                    cleaned_rows.append(cleaned_row)
            if not cleaned_rows:
                continue
            blocks.append(
                RichTextBlock(type=block_type, content=cleaned_rows, marks=marks)
            )
        # Any other block_type within the whitelist but without handled content
        # semantics is dropped (defensive).

    return RichTextDocument(blocks=tuple(blocks))


def render_rich_text(document: RichTextDocument) -> list[dict]:
    """Render a :class:`RichTextDocument` into deterministic block dicts."""

    rendered: list[dict] = []
    for block in document.blocks:
        rendered.append(
            {
                "type": block.type,
                "content": block.content,
                "marks": list(block.marks),
            }
        )
    return rendered
