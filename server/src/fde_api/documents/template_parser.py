"""Safe scanner and validator for Jinja placeholders inside DOCX templates.

The scanner walks the body paragraphs, tables (each cell), headers and footers
of a DOCX, collects ``{{ ... }}`` output expressions and ``{% ... %}`` statement
tags, and validates every expression against a closed, allow-listed grammar so
that rendering-time template injection (``os.system``, attribute escapes through
``__globals__``) can never execute.

The scan is deliberately non-throwing: hostile or malformed input is reported
as :class:`TemplateIssue` entries on the returned :class:`TemplateScan`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import BinaryIO, Union

from docx import Document
from jinja2 import Environment, nodes

# The roots that a template may dereference. Any other name (outside a loop
# variable introduced by ``{% for x in ... %}``) is rejected.
ALLOWED_ROOTS = frozenset(
    {"project", "enterprise", "research", "subjects", "tasks", "members", "document"}
)

# Rich-text block types and the formatting marks allowed inside blocks. These
# live here so both the parser (document roots) and the rich-text sanitizer can
# share one vocabulary without a circular import.
ALLOWED_BLOCK_TYPES = frozenset(
    {"paragraph", "heading", "ordered_list", "bullet_list", "table"}
)
ALLOWED_MARKS = frozenset(
    {
        "bold",
        "italic",
        "underline",
        "strikethrough",
        "code",
        "link",
        "highlight",
        "sub",
        "sup",
    }
)

# A Jinja attribute chain is only allowed a few hops from its root. Deeper
# chains are treated as an escape attempt ("unsafe_template_expression").
MAX_ATTRIBUTE_DEPTH = 4

# Attribute names that are never safe to reach through template access.
UNSAFE_ATTRIBUTES = frozenset(
    {
        "__class__",
        "__base__",
        "__mro__",
        "__subclasses__",
        "__globals__",
        "__builtins__",
        "__init__",
        "__dict__",
        "__getattr__",
        "__getattribute__",
        "os",
        "system",
        "popen",
        "subprocess",
        "eval",
        "exec",
        "builtins",
        "globals",
        "locals",
        "import",
        "open",
        "compile",
        "getattr",
        "setattr",
        "delattr",
    }
)

# ``{{ ... }}`` output expressions and ``{% ... %}`` statement tags.
EXPR_RE = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.DOTALL)


class TemplateSecurityError(Exception):
    """Raised when a template is rejected outright (not recorded as an issue)."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass
class TemplateIssue:
    """One recorded validation problem found during a scan."""

    code: str
    message: str
    location: str = ""


@dataclass
class TemplateScan:
    """The non-throwing result of scanning a DOCX template for placeholders."""

    placeholders: list[str] = field(default_factory=list)
    issues: list[TemplateIssue] = field(default_factory=list)
    # Row/column placeholders found inside table cells.
    tables: list[str] = field(default_factory=list)


def _issue(issues: list[TemplateIssue], code: str, location: str, message: str) -> None:
    issues.append(TemplateIssue(code=code, message=message, location=location))


def _is_unsafe_attr(attr: object) -> bool:
    if not isinstance(attr, str):
        return False
    if attr.startswith("__") and attr.endswith("__"):
        return True
    return attr in UNSAFE_ATTRIBUTES


def _getattr_depth(node: object) -> int:
    """Number of consecutive attribute hops from ``node`` back to a non-``Getattr``."""

    depth = 0
    current = node
    while isinstance(current, nodes.Getattr):
        depth += 1
        current = current.node
    return depth


def _active_loop_vars(loop_stack: list[set[str]]) -> set[str]:
    active: set[str] = set()
    for scope in loop_stack:
        active |= scope
    return active


def _walk(node: object, location: str, issues: list[TemplateIssue], loop_stack: list[set[str]]) -> None:
    """Recursively validate one expression AST node against the closed grammar."""

    if isinstance(node, nodes.Const):
        return
    if isinstance(node, nodes.Name):
        # Assignments (store context) are targets, not references.
        if node.ctx == "store":
            return
        name = node.name
        active = _active_loop_vars(loop_stack)
        in_loop = bool(loop_stack)
        if name in ALLOWED_ROOTS or (in_loop and name == "loop") or name in active:
            return
        _issue(
            issues,
            "unknown_template_root",
            location,
            f"template references unknown root '{name}'",
        )
        return
    if isinstance(node, nodes.Call):
        _issue(
            issues,
            "unsafe_template_expression",
            location,
            "function calls are not allowed in template placeholders",
        )
        for child in node.iter_child_nodes():
            _walk(child, location, issues, loop_stack)
        return
    if isinstance(node, nodes.Filter):
        _issue(
            issues,
            "unsafe_template_expression",
            location,
            "filters are not allowed in template placeholders",
        )
        for child in node.iter_child_nodes():
            _walk(child, location, issues, loop_stack)
        return
    if isinstance(node, nodes.Test):
        _issue(
            issues,
            "unsafe_template_expression",
            location,
            "tests are not allowed in template placeholders",
        )
        for child in node.iter_child_nodes():
            _walk(child, location, issues, loop_stack)
        return
    if isinstance(node, nodes.Getattr):
        attr = node.attr
        if _getattr_depth(node) > MAX_ATTRIBUTE_DEPTH or _is_unsafe_attr(attr):
            _issue(
                issues,
                "unsafe_template_expression",
                location,
                f"unsafe attribute chain reaching '{attr}'",
            )
        for child in node.iter_child_nodes():
            _walk(child, location, issues, loop_stack)
        return
    for child in node.iter_child_nodes():
        _walk(child, location, issues, loop_stack)


def _validate_expression(inner: str, location: str, issues: list[TemplateIssue], loop_stack: list[set[str]]) -> None:
    env = Environment()
    try:
        tree = env.parse("{{ " + inner + " }}")
    except Exception:
        _issue(
            issues,
            "invalid_template_expression",
            location,
            f"could not parse expression '{inner}'",
        )
        return
    if not tree.body or not isinstance(tree.body[0], nodes.Output):
        _issue(
            issues,
            "invalid_template_expression",
            location,
            f"expression '{inner}' is not a valid output expression",
        )
        return
    for expression in tree.body[0].nodes:
        _walk(expression, location, issues, loop_stack)


def _collect_target_names(node: object) -> list[str]:
    if isinstance(node, nodes.Name):
        return [node.name]
    if isinstance(node, nodes.Tuple):
        return [item.name for item in node.items if isinstance(item, nodes.Name)]
    return []


def _validate_statement(inner: str, location: str, issues: list[TemplateIssue], loop_stack: list[set[str]]) -> None:
    env = Environment()
    stripped = inner.strip()

    if stripped.startswith("for "):
        try:
            tree = env.parse("{% " + stripped + " %}{% endfor %}")
        except Exception:
            _issue(
                issues,
                "invalid_template_expression",
                location,
                f"could not parse loop '{stripped}'",
            )
            return
        if not tree.body or not isinstance(tree.body[0], nodes.For):
            _issue(
                issues,
                "invalid_template_expression",
                location,
                f"loop statement '{stripped}' is malformed",
            )
            return
        loop_node = tree.body[0]
        _walk(loop_node.iter, location, issues, loop_stack)
        loop_stack.append(set(_collect_target_names(loop_node.target)))
        return

    if stripped == "endfor":
        if not loop_stack:
            _issue(
                issues,
                "unbalanced_loop",
                location,
                "{% endfor %} found without a matching {% for %}",
            )
        else:
            loop_stack.pop()
        return

    if stripped.startswith("if "):
        try:
            tree = env.parse("{% " + stripped + " %}{% endif %}")
        except Exception:
            _issue(
                issues,
                "invalid_template_expression",
                location,
                f"could not parse condition '{stripped}'",
            )
            return
        if tree.body and isinstance(tree.body[0], nodes.If):
            _walk(tree.body[0].test, location, issues, loop_stack)
        return

    if stripped.startswith("elif "):
        try:
            tree = env.parse("{% " + stripped + " %}{% endif %}")
        except Exception:
            _issue(
                issues,
                "invalid_template_expression",
                location,
                f"could not parse condition '{stripped}'",
            )
            return
        if tree.body and isinstance(tree.body[0], nodes.If):
            _walk(tree.body[0].test, location, issues, loop_stack)
        return

    if stripped in {"endif", "else"}:
        return

    # Fallback for any other statement tag (e.g. ``{% set %}``). Parse it and
    # validate the expressions it references; assignment targets are skipped by
    # ``_walk`` (store context), so foreign variables still surface as issues.
    try:
        tree = env.parse("{% " + stripped + " %}")
    except Exception:
        _issue(
            issues,
            "invalid_template_expression",
            location,
            f"could not parse statement '{stripped}'",
        )
        return
    for node in tree.body:
        _walk(node, location, issues, loop_stack)


def _process_text(text: str, location: str, issues: list[TemplateIssue], loop_stack: list[set[str]]) -> list[str]:
    found: list[str] = []
    for match in EXPR_RE.finditer(text):
        token = match.group(0)
        found.append(token)
        inner = token[2:-2].strip()
        if token.startswith("{{"):
            _validate_expression(inner, location, issues, loop_stack)
        else:
            _validate_statement(inner, location, issues, loop_stack)
    return found


def _process_paragraphs(paragraphs: object, location: str, issues: list[TemplateIssue], loop_stack: list[set[str]]) -> list[str]:
    found: list[str] = []
    for paragraph in paragraphs:
        found.extend(_process_text(paragraph.text, location, issues, loop_stack))
    return found


def _process_table(table: object, location: str, issues: list[TemplateIssue], loop_stack: list[set[str]]) -> list[str]:
    found: list[str] = []
    seen_cells: set[object] = set()
    for row in table.rows:
        for cell in row.cells:
            cell_key = cell._tc if hasattr(cell, "_tc") else cell
            if cell_key in seen_cells:
                continue
            seen_cells.add(cell_key)
            found.extend(_process_paragraphs(cell.paragraphs, location, issues, loop_stack))
            for nested in cell.tables:
                found.extend(_process_table(nested, location, issues, loop_stack))
    return found


def scan_docx_placeholders(stream: Union[BinaryIO, bytes]) -> TemplateScan:
    """Scan a DOCX ``stream`` and return a :class:`TemplateScan`.

    Hostile or malformed placeholder content is recorded as issues and never
    raises. The doc itself is expected to be a valid Office Open XML archive.
    """

    document = Document(stream)
    placeholders: list[str] = []
    tables: list[str] = []
    issues: list[TemplateIssue] = []
    loop_stack: list[set[str]] = []

    # Body paragraphs.
    placeholders.extend(_process_paragraphs(document.paragraphs, "body", issues, loop_stack))

    # Body tables (recursive for nested tables).
    for table in document.tables:
        table_hits = _process_table(table, "table", issues, loop_stack)
        placeholders.extend(table_hits)
        tables.extend(table_hits)

    # Headers and footers, one per section.
    for index, section in enumerate(document.sections):
        header = section.header
        if header is not None:
            placeholders.extend(
                _process_paragraphs(header.paragraphs, f"header[{index}]", issues, loop_stack)
            )
            for table in header.tables:
                table_hits = _process_table(table, f"header[{index}]/table", issues, loop_stack)
                placeholders.extend(table_hits)
                tables.extend(table_hits)
        footer = section.footer
        if footer is not None:
            placeholders.extend(
                _process_paragraphs(footer.paragraphs, f"footer[{index}]", issues, loop_stack)
            )
            for table in footer.tables:
                table_hits = _process_table(table, f"footer[{index}]/table", issues, loop_stack)
                placeholders.extend(table_hits)
                tables.extend(table_hits)

    return TemplateScan(
        placeholders=placeholders,
        issues=issues,
        tables=tables,
    )
