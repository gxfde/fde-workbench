"""Mapping validator that ties a scanned template to a research definition.

``validate_mapping`` inspects the placeholders collected by
:func:`fde_api.documents.template_parser.scan_docx_placeholders` against a
declarative ``mapping`` and a published research definition, returning a list of
:class:`MappingIssue` (empty when the mapping is valid). It never raises for a
validation failure --- callers inspect the returned list.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from jinja2 import Environment, nodes

from fde_api.documents.template_parser import ALLOWED_ROOTS
from fde_api.research.models import SUBJECT_TYPES

# Re-use the scan grammar's allow-listed roots as the valid document roots.
ALLOWED_DOCUMENT_ROOTS = ALLOWED_ROOTS

# Research root attributes that are wrapper structures, not form references.
_STRUCTURAL_RESEARCH_KEYS = frozenset({"forms", "form", "fields", "sections", "answers"})
_SUBJECT_STRUCTURAL_KEYS = frozenset({"subjects", "roles", "types", "list"})


@dataclass
class MappingIssue:
    """One deterministic, user-addressable mapping problem."""

    code: str
    message: str
    path: str


class MappingValidationError(Exception):
    """Raised only for internal mapping failures, not ordinary validation."""

    def __init__(self, issues: list[MappingIssue] | None = None) -> None:
        self.issues = issues or []
        super().__init__("mapping validation failed")


def _strip_delimiters(token: object) -> str | None:
    if not isinstance(token, str) or len(token) < 5:
        return None
    if token.startswith("{{") and token.endswith("}}"):
        return token[2:-2].strip()
    if token.startswith("{%") and token.endswith("%}"):
        return token[2:-2].strip()
    return None


def _root_name(node: object) -> str | None:
    while isinstance(node, (nodes.Getattr, nodes.Getitem)):
        node = node.node
    if isinstance(node, nodes.Name):
        return node.name
    return None


def _chain_attributes(node: object) -> list[Any]:
    attrs: list[Any] = []
    cur = node
    while isinstance(cur, (nodes.Getattr, nodes.Getitem)):
        if isinstance(cur, nodes.Getattr):
            attrs.append(cur.attr)
        else:
            attrs.append(cur.slice)
        cur = cur.node
    return list(reversed(attrs))


def _expression_root(inner: str) -> str | None:
    env = Environment()
    try:
        tree = env.parse("{{ " + inner + " }}")
    except Exception:
        return None
    if not tree.body or not isinstance(tree.body[0], nodes.Output):
        return None
    for node in tree.body[0].nodes:
        return _root_name(node)
    return None


def _for_iter_root(inner: str) -> str | None:
    env = Environment()
    try:
        tree = env.parse("{% " + inner + " %}{% endfor %}")
    except Exception:
        return None
    if not tree.body or not isinstance(tree.body[0], nodes.For):
        return None
    return _root_name(tree.body[0].iter)


def _placeholder_is_known_root(placeholder: object) -> bool:
    inner = _strip_delimiters(placeholder)
    if inner is None:
        return False
    if isinstance(placeholder, str) and placeholder.startswith("{%"):
        root = _for_iter_root(inner)
        return root in ALLOWED_ROOTS
    root = _expression_root(inner)
    return root in ALLOWED_ROOTS


def _research_forms_index(research_definition: Any) -> dict[str, dict[str, Any]]:
    """Normalise a research definition into ``{form_key: {...}}``.

    Accepts either ``{"forms": {...}}`` / ``{"forms": [...]}`` or a bare dict of
    ``{form_key: {...}}``.
    """

    index: dict[str, dict[str, Any]] = {}
    if not isinstance(research_definition, dict):
        return index
    forms = research_definition.get("forms")
    if isinstance(forms, dict):
        for key, value in forms.items():
            if isinstance(value, dict):
                index[str(key)] = value
        return index
    if isinstance(forms, list):
        for value in forms:
            if isinstance(value, dict) and isinstance(value.get("form_key"), str):
                index[value["form_key"]] = value
        return index
    for key, value in research_definition.items():
        if isinstance(value, dict):
            index[str(key)] = value
    return index


def _loop_iterable_roots(placeholders: list[Any]) -> list[tuple[str, list[Any]]]:
    results: list[tuple[str, list[Any]]] = []
    for placeholder in placeholders:
        if not isinstance(placeholder, str) or not placeholder.startswith("{% for "):
            continue
        inner = _strip_delimiters(placeholder)
        if inner is None:
            continue
        env = Environment()
        try:
            tree = env.parse("{% " + inner + " %}{% endfor %}")
        except Exception:
            continue
        if not tree.body or not isinstance(tree.body[0], nodes.For):
            continue
        iter_node = tree.body[0].iter
        root = _root_name(iter_node)
        if root is None:
            continue
        results.append((root, _chain_attributes(iter_node)))
    return results


def validate_mapping(scan: Any, mapping: Any, research_definition: Any) -> list[MappingIssue]:
    """Validate ``scan.placeholders`` against ``mapping`` and ``research_definition``.

    Returns a list of :class:`MappingIssue`; an empty list means the mapping is
    consistent. Raises :class:`MappingValidationError` only for non-validator
    failures (e.g. invalid internal structures), never for ordinary issues.
    """

    issues: list[MappingIssue] = []

    mapping_dict = mapping if isinstance(mapping, dict) else {}
    placeholders = [p for p in (getattr(scan, "placeholders", None) or []) if isinstance(p, str)]

    field_map = mapping_dict.get("field_map", {})
    if not isinstance(field_map, dict):
        field_map = {}

    # 1. Every placeholder is a known data root or appears in the field map.
    for placeholder in placeholders:
        if _placeholder_is_known_root(placeholder):
            continue
        if placeholder in field_map:
            continue
        issues.append(
            MappingIssue(
                "unknown_placeholder",
                f"placeholder '{placeholder}' is neither a known data root nor mapped in field_map",
                placeholder,
            )
        )

    forms_index = _research_forms_index(research_definition)

    # 2. Each declared research form key / subject type must exist.
    research_keys = mapping_dict.get("research_keys", [])
    if isinstance(research_keys, dict):
        research_keys = [
            {"form_key": form_key, "subject_type": subject_type}
            for form_key, subject_type in research_keys.items()
        ]
    if not isinstance(research_keys, list):
        research_keys = []

    seen_forms: set[str] = set()
    for entry in research_keys:
        if not isinstance(entry, dict):
            continue
        form_key = entry.get("form_key")
        if form_key is None:
            continue
        subject_type = entry.get("subject_type")

        form = forms_index.get(str(form_key))
        if form is None:
            issues.append(
                MappingIssue(
                    "missing_research_form",
                    f"research form '{form_key}' is not present in the published research definition",
                    str(form_key),
                )
            )
            continue

        if subject_type is not None:
            if subject_type not in SUBJECT_TYPES:
                issues.append(
                    MappingIssue(
                        "unsupported_subject_type",
                        f"subject type '{subject_type}' is not supported",
                        str(form_key),
                    )
                )
            else:
                declared = form.get("subject_type")
                if declared is not None and subject_type != declared:
                    issues.append(
                        MappingIssue(
                            "unsupported_subject_type",
                            f"form '{form_key}' declares subject type '{declared}', not '{subject_type}'",
                            str(form_key),
                        )
                    )
        if isinstance(form_key, str):
            seen_forms.add(form_key)

    # 3. Loop contexts must reference research form keys present in the definition.
    for root, attrs in _loop_iterable_roots(placeholders):
        if root != "research" or not attrs:
            continue
        if len(attrs) != 1:
            continue
        key_candidate = attrs[0]
        if not isinstance(key_candidate, str) or key_candidate in _STRUCTURAL_RESEARCH_KEYS:
            continue
        if key_candidate not in forms_index:
            issues.append(
                MappingIssue(
                    "missing_research_form",
                    f"loop iterable references missing research form '{key_candidate}'",
                    key_candidate,
                )
            )

    return issues
