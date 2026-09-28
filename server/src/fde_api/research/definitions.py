from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
import math
import re
from typing import Any

from fde_api.research.answers import (
    MAX_JSON_SAFE_INTEGER,
    MIN_JSON_SAFE_INTEGER,
    ResearchValidationError,
    is_canonical_condition_text,
    normalize_decimal,
)

from fde_api.research.models import FIELD_TYPES, SUBJECT_TYPES


ALLOWED_OPERATORS = frozenset(
    {"equals", "not_equals", "contains", "is_empty", "all", "any"}
)
TABLE_COLUMN_FIELD_TYPES = frozenset(
    field_type for field_type in FIELD_TYPES if field_type not in {"table", "file_reference"}
)
_OPTION_KEYS = {
    "short_text": frozenset({"placeholder", "default_value", "min_length", "max_length"}),
    "long_text": frozenset({"placeholder", "default_value", "min_length", "max_length"}),
    "rich_text": frozenset({"placeholder", "default_value"}),
    "integer": frozenset({"minimum", "maximum", "default_value"}),
    "decimal": frozenset({"minimum", "maximum", "default_value"}),
    "date": frozenset({"minimum", "maximum", "default_value"}),
    "single_choice": frozenset({"choices", "default_value"}),
    "multi_choice": frozenset({"choices", "default_value"}),
    "table": frozenset({"columns"}),
    "file_reference": frozenset({"max_files"}),
}
_STABLE_KEY = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class DefinitionIssue:
    code: str
    path: str
    message: str


def validate_research_definition(definition: dict) -> list[DefinitionIssue]:
    """Return deterministic, user-addressable errors for one research definition."""
    if not isinstance(definition, dict) or set(definition) != {"forms"}:
        return [_issue("invalid_definition", "", "A research definition must contain forms.")]
    forms = definition.get("forms")
    if not isinstance(forms, list):
        return [_issue("invalid_definition", "forms", "Forms must be a list.")]

    issues = _validate_form_shapes(forms)
    issues.extend(_validate_unique_keys(forms))
    issues.extend(_validate_field_configs(forms))
    issues.extend(_validate_condition_trees(forms))
    return sorted(issues, key=lambda issue: (issue.path, issue.code))


def _validate_form_shapes(forms: list[object]) -> list[DefinitionIssue]:
    issues: list[DefinitionIssue] = []
    for form_index, form in enumerate(forms):
        form_path = f"forms[{form_index}]"
        if not isinstance(form, dict):
            issues.append(_issue("invalid_form", form_path, "A form must be an object."))
            continue
        issues.extend(_validate_mapping_keys(
            form,
            {"id", "form_key", "name", "description", "subject_type", "module_key", "sort_order", "sections"},
            {"form_key", "name", "subject_type", "sections"},
            form_path,
            "form",
        ))
        if form.get("subject_type") not in SUBJECT_TYPES:
            issues.append(_issue("invalid_subject_type", f"{form_path}.subject_type", "Unsupported research subject type."))
        if form.get("module_key") is not None:
            issues.extend(_stable_key_issue(form.get("module_key"), f"{form_path}.module_key"))
        issues.extend(_stable_key_issue(form.get("form_key"), f"{form_path}.form_key"))
        issues.extend(_text_issues(form.get("name"), f"{form_path}.name", 160))
        issues.extend(_optional_text_issues(form.get("description", ""), f"{form_path}.description"))
        issues.extend(_whole_number_issues(form.get("sort_order", 0), f"{form_path}.sort_order"))
        sections = form.get("sections")
        if not isinstance(sections, list):
            issues.append(_issue("invalid_sections", f"{form_path}.sections", "Sections must be a list."))
            continue
        for section_index, section in enumerate(sections):
            section_path = f"{form_path}.sections[{section_index}]"
            if not isinstance(section, dict):
                issues.append(_issue("invalid_section", section_path, "A section must be an object."))
                continue
            issues.extend(_validate_mapping_keys(
                section,
                {"id", "section_key", "name", "description", "sort_order", "fields"},
                {"section_key", "name", "fields"},
                section_path,
                "section",
            ))
            issues.extend(_stable_key_issue(section.get("section_key"), f"{section_path}.section_key"))
            issues.extend(_text_issues(section.get("name"), f"{section_path}.name", 160))
            issues.extend(_optional_text_issues(section.get("description", ""), f"{section_path}.description"))
            issues.extend(_whole_number_issues(section.get("sort_order", 0), f"{section_path}.sort_order"))
            fields = section.get("fields")
            if not isinstance(fields, list):
                issues.append(_issue("invalid_fields", f"{section_path}.fields", "Fields must be a list."))
                continue
            for field_index, field in enumerate(fields):
                field_path = f"{section_path}.fields[{field_index}]"
                if not isinstance(field, dict):
                    issues.append(_issue("invalid_field", field_path, "A field must be an object."))
                    continue
                issues.extend(_validate_mapping_keys(
                    field,
                    {"id", "field_key", "name", "help_text", "type", "is_required", "options", "sort_order", "condition"},
                    {"field_key", "name", "type", "is_required", "options"},
                    field_path,
                    "field",
                ))
                issues.extend(_stable_key_issue(field.get("field_key"), f"{field_path}.field_key"))
                issues.extend(_text_issues(field.get("name"), f"{field_path}.name", 160))
                issues.extend(_optional_text_issues(field.get("help_text", ""), f"{field_path}.help_text"))
                issues.extend(_whole_number_issues(field.get("sort_order", 0), f"{field_path}.sort_order"))
                if type(field.get("is_required")) is not bool:
                    issues.append(_issue("invalid_required", f"{field_path}.is_required", "Required must be a boolean."))
                if not isinstance(field.get("options"), dict):
                    issues.append(_issue("invalid_field_options", f"{field_path}.options", "Field options must be an object."))
    return issues


def _validate_mapping_keys(
    value: dict[str, Any], allowed: set[str], required: set[str], path: str, name: str
) -> list[DefinitionIssue]:
    issues: list[DefinitionIssue] = []
    if value.keys() - allowed:
        issues.append(_issue("unknown_payload_key", path, f"Unknown {name} properties are not allowed."))
    for key in sorted(required - value.keys()):
        issues.append(_issue("missing_required_property", f"{path}.{key}", f"{name.title()} property is required."))
    return issues


def _validate_unique_keys(forms: list[object]) -> list[DefinitionIssue]:
    issues: list[DefinitionIssue] = []
    seen_forms: set[str] = set()
    for form_index, form in enumerate(forms):
        if not isinstance(form, dict):
            continue
        form_path = f"forms[{form_index}]"
        form_key = form.get("form_key")
        if isinstance(form_key, str) and form_key in seen_forms:
            issues.append(_issue("duplicate_form_key", f"{form_path}.form_key", "Form keys must be unique."))
        elif isinstance(form_key, str):
            seen_forms.add(form_key)
        seen_sections: set[str] = set()
        seen_fields: set[str] = set()
        for section_index, section in enumerate(_items(form.get("sections"))):
            if not isinstance(section, dict):
                continue
            section_path = f"{form_path}.sections[{section_index}]"
            section_key = section.get("section_key")
            if isinstance(section_key, str) and section_key in seen_sections:
                issues.append(_issue("duplicate_section_key", f"{section_path}.section_key", "Section keys must be unique within a form."))
            elif isinstance(section_key, str):
                seen_sections.add(section_key)
            for field_index, field in enumerate(_items(section.get("fields"))):
                if not isinstance(field, dict):
                    continue
                field_path = f"{section_path}.fields[{field_index}]"
                field_key = field.get("field_key")
                if isinstance(field_key, str) and field_key in seen_fields:
                    issues.append(_issue("duplicate_field_key", f"{field_path}.field_key", "Field keys must be unique within a form."))
                elif isinstance(field_key, str):
                    seen_fields.add(field_key)
    return issues


def _validate_field_configs(forms: list[object]) -> list[DefinitionIssue]:
    issues: list[DefinitionIssue] = []
    for field, path in _fields(forms):
        field_type = field.get("type")
        if field_type not in FIELD_TYPES:
            issues.append(_issue("invalid_field_type", f"{path}.type", "Unsupported research field type."))
            continue
        options = field.get("options")
        if not isinstance(options, dict):
            continue
        for option_key in sorted(set(options) - _OPTION_KEYS[field_type]):
            issues.append(
                _issue(
                    "unknown_field_option",
                    f"{path}.options.{option_key}",
                    "Unsupported field option.",
                )
            )
        issues.extend(_field_option_value_issues(field_type, options, f"{path}.options"))
        if field_type in {"single_choice", "multi_choice"}:
            choices = options.get("choices")
            choices_are_valid = not (
                not isinstance(choices, list)
                or not choices
                or any(not isinstance(choice, str) or not choice.strip() for choice in choices)
                or len(set(choices)) != len(choices)
            )
            if not choices_are_valid:
                issues.append(_issue("invalid_choice_options", f"{path}.options.choices", "Choice fields require unique non-empty choices."))
            default = options.get("default_value")
            if "default_value" in options and choices_are_valid and (
                (field_type == "single_choice" and (not isinstance(default, str) or default not in choices))
                or (
                    field_type == "multi_choice"
                    and (
                        not isinstance(default, list)
                        or any(not isinstance(item, str) or item not in choices for item in default)
                    )
                )
            ):
                issues.append(_issue("invalid_choice_default", f"{path}.options.default_value", "Choice defaults must belong to the declared choices."))
        if field_type == "file_reference" and (
            type(options.get("max_files")) is not int or options["max_files"] < 1
        ):
            issues.append(_issue("invalid_file_max_files", f"{path}.options.max_files", "File fields require a positive integer max_files."))
        if field_type == "table" and "columns" in options:
            columns = options["columns"]
            if not isinstance(columns, list) or any(
                not isinstance(column, dict)
                or set(column) - {"key", "name", "type", "options"}
                or not {"key", "name"} <= set(column)
                or not isinstance(column["key"], str)
                or not isinstance(column["name"], str)
                for column in columns
            ):
                issues.append(_issue("invalid_table_columns", f"{path}.options.columns", "Table columns must be named objects."))
            elif any(
                column.get("type", "short_text") not in TABLE_COLUMN_FIELD_TYPES
                for column in columns
            ):
                invalid_index = next(
                    index
                    for index, column in enumerate(columns)
                    if column.get("type", "short_text") not in TABLE_COLUMN_FIELD_TYPES
                )
                issues.append(
                    _issue(
                        "invalid_table_column_type",
                        f"{path}.options.columns[{invalid_index}].type",
                        "Table columns must use a non-nested field type.",
                    )
                )
            else:
                seen_column_keys: set[str] = set()
                for index, column in enumerate(columns):
                    column_path = f"{path}.options.columns[{index}]"
                    column_key = column["key"]
                    if len(column_key) > 100 or _STABLE_KEY.fullmatch(column_key) is None:
                        issues.append(_issue("invalid_table_column_key", f"{column_path}.key", "Table column keys must be lowercase identifiers."))
                    elif column_key in seen_column_keys:
                        issues.append(_issue("duplicate_table_column_key", f"{column_path}.key", "Table column keys must be unique."))
                    else:
                        seen_column_keys.add(column_key)
                    if not column["name"].strip():
                        issues.append(_issue("invalid_table_column_name", f"{column_path}.name", "Table column names must be non-empty."))
                    if "options" in column and not isinstance(column["options"], dict):
                        issues.append(_issue("invalid_table_column_options", f"{column_path}.options", "Table column options must be an object."))
                    column_type = column.get("type", "short_text")
                    column_options = column.get("options")
                    if isinstance(column_options, dict):
                        for option_key in sorted(set(column_options) - _OPTION_KEYS[column_type]):
                            issues.append(_issue("unknown_table_column_option", f"{column_path}.options.{option_key}", "Unsupported table column option."))
                        issues.extend(_field_option_value_issues(
                            column_type,
                            column_options,
                            f"{column_path}.options",
                            code="invalid_table_column_option_value",
                        ))
                    if column.get("type") in {"single_choice", "multi_choice"}:
                        choices = column_options.get("choices") if isinstance(column_options, dict) else None
                        choices_are_valid = isinstance(choices, list) and bool(choices) and all(isinstance(choice, str) and bool(choice.strip()) for choice in choices) and len(set(choices)) == len(choices)
                        if not choices_are_valid:
                            issues.append(_issue("invalid_table_choice_options", f"{column_path}.options.choices", "Table choice columns require unique non-empty choices."))
                        default = column_options.get("default_value") if isinstance(column_options, dict) else None
                        if isinstance(column_options, dict) and "default_value" in column_options and choices_are_valid and (
                            (column["type"] == "single_choice" and (not isinstance(default, str) or default not in choices))
                            or (
                                column["type"] == "multi_choice"
                                and (
                                    not isinstance(default, list)
                                    or any(not isinstance(item, str) or item not in choices for item in default)
                                )
                            )
                        ):
                            issues.append(_issue("invalid_table_choice_default", f"{column_path}.options.default_value", "Table choice defaults must belong to the declared choices."))
    return issues


def _field_option_value_issues(
    field_type: str,
    options: dict[str, Any],
    path: str,
    *,
    code: str = "invalid_field_option_value",
) -> list[DefinitionIssue]:
    invalid_keys: list[str] = []
    if field_type in {"short_text", "long_text"}:
        invalid_keys.extend(
            key for key in ("placeholder", "default_value")
            if key in options and not isinstance(options[key], str)
        )
        invalid_keys.extend(
            key for key in ("min_length", "max_length")
            if key in options and (type(options[key]) is not int or options[key] < 0)
        )
        if (
            type(options.get("min_length")) is int
            and options["min_length"] >= 0
            and type(options.get("max_length")) is int
            and options["max_length"] >= 0
            and options["min_length"] > options["max_length"]
        ):
            invalid_keys.append("max_length")
    elif field_type == "rich_text":
        invalid_keys.extend(
            key for key in ("placeholder", "default_value")
            if key in options and not isinstance(options[key], str)
        )
    elif field_type == "integer":
        invalid_keys.extend(
            key for key in ("minimum", "maximum", "default_value")
            if key in options and (
                type(options[key]) is not int
                or not MIN_JSON_SAFE_INTEGER <= options[key] <= MAX_JSON_SAFE_INTEGER
            )
        )
        if (
            type(options.get("minimum")) is int
            and type(options.get("maximum")) is int
            and options["minimum"] > options["maximum"]
        ):
            invalid_keys.append("maximum")
    elif field_type == "decimal":
        invalid_keys.extend(
            key for key in ("minimum", "maximum", "default_value")
            if key in options and (
                type(options[key]) not in {int, float}
                or not math.isfinite(options[key])
            )
        )
        if (
            type(options.get("minimum")) in {int, float}
            and math.isfinite(options["minimum"])
            and type(options.get("maximum")) in {int, float}
            and math.isfinite(options["maximum"])
            and options["minimum"] > options["maximum"]
        ):
            invalid_keys.append("maximum")
    elif field_type == "date":
        invalid_keys.extend(
            key for key in ("minimum", "maximum", "default_value")
            if key in options and not isinstance(options[key], str)
        )
    return [
        _issue(code, f"{path}.{key}", "Field option value has an invalid type or range.")
        for key in invalid_keys
    ]


def _validate_condition_trees(forms: list[object]) -> list[DefinitionIssue]:
    issues: list[DefinitionIssue] = []
    for form_index, form in enumerate(forms):
        if not isinstance(form, dict):
            continue
        references: dict[str, list[tuple[str, str]]] = {}
        available = {
            field.get("field_key"): field
            for field, _ in _fields([form])
            if isinstance(field.get("field_key"), str)
        }
        for field, path in _fields([form], prefix=f"forms[{form_index}]"):
            field_key = field.get("field_key")
            condition = field.get("condition")
            if not isinstance(field_key, str) or condition is None:
                continue
            leaves = _condition_leaves(condition, f"{path}.condition", issues)
            for reference, reference_path, leaf in leaves:
                if reference not in available:
                    issues.append(_issue("unknown_condition_field", f"{reference_path}.field_key", "Conditional field does not exist in this form."))
                else:
                    references.setdefault(field_key, []).append((reference, reference_path))
                    issues.extend(_condition_semantic_issues(
                        available[reference], leaf, reference_path
                    ))
        issues.extend(_cycle_issues(references))
    return issues


def _condition_leaves(
    condition: object, path: str, issues: list[DefinitionIssue]
) -> list[tuple[str, str, dict[str, Any]]]:
    if not isinstance(condition, dict):
        issues.append(_issue("invalid_condition", path, "A condition must be an object."))
        return []
    operator = condition.get("operator")
    if operator not in ALLOWED_OPERATORS:
        issues.append(_issue("invalid_condition_operator", f"{path}.operator", "Unsupported condition operator."))
        return []
    if operator in {"all", "any"}:
        if set(condition) != {"operator", "conditions"} or not isinstance(condition.get("conditions"), list) or not condition["conditions"]:
            issues.append(_issue("invalid_condition", path, "Boolean conditions require child conditions."))
            return []
        leaves: list[tuple[str, str, dict[str, Any]]] = []
        for index, child in enumerate(condition["conditions"]):
            leaves.extend(_condition_leaves(child, f"{path}.conditions[{index}]", issues))
        return leaves
    allowed = {"field_key", "operator"} if operator == "is_empty" else {"field_key", "operator", "value"}
    if set(condition) != allowed or not isinstance(condition.get("field_key"), str):
        issues.append(_issue("invalid_condition", path, "Condition properties are invalid."))
        return []
    return [(condition["field_key"], path, condition)]


def _condition_semantic_issues(
    referenced_field: dict[str, Any], condition: dict[str, Any], path: str
) -> list[DefinitionIssue]:
    field_type = referenced_field.get("type")
    operator = condition["operator"]
    allowed_operators = {
        "short_text": {"equals", "not_equals", "contains", "is_empty"},
        "long_text": {"equals", "not_equals", "contains", "is_empty"},
        "integer": {"equals", "not_equals", "is_empty"},
        "decimal": {"equals", "not_equals", "is_empty"},
        "date": {"equals", "not_equals", "is_empty"},
        "single_choice": {"equals", "not_equals", "is_empty"},
        "multi_choice": {"contains", "is_empty"},
        "rich_text": {"is_empty"},
        "table": {"is_empty"},
        "file_reference": {"is_empty"},
    }.get(field_type)
    if allowed_operators is None:
        return []
    if operator not in allowed_operators:
        return [_issue(
            "invalid_condition_operator",
            f"{path}.operator",
            "Condition operator is not supported by the referenced field type.",
        )]
    if operator == "is_empty":
        return []
    if not _condition_value_matches(referenced_field, condition["value"]):
        return [_issue(
            "invalid_condition_value",
            f"{path}.value",
            "Condition value does not match the referenced field type.",
        )]
    return []


def _condition_value_matches(field: dict[str, Any], value: object) -> bool:
    field_type = field.get("type")
    if field_type in {"short_text", "long_text"}:
        return is_canonical_condition_text(value)
    if field_type == "integer":
        return type(value) is int and MIN_JSON_SAFE_INTEGER <= value <= MAX_JSON_SAFE_INTEGER
    if field_type == "decimal":
        return _is_condition_decimal(value)
    if field_type == "date":
        if not isinstance(value, str):
            return False
        try:
            return date.fromisoformat(value).isoformat() == value
        except ValueError:
            return False
    if field_type in {"single_choice", "multi_choice"}:
        choices = field.get("options", {}).get("choices")
        return (
            isinstance(value, str)
            and isinstance(choices, list)
            and value in choices
        )
    return False


def _is_condition_decimal(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        return normalize_decimal(value) == value
    except ResearchValidationError:
        return False


def _cycle_issues(references: dict[str, list[tuple[str, str]]]) -> list[DefinitionIssue]:
    graph = {key: {reference for reference, _ in edges} for key, edges in references.items()}
    cyclic_keys: set[str] = set()
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(key: str, trail: list[str]) -> None:
        if key in visiting:
            cyclic_keys.update(trail[trail.index(key) :])
            return
        if key in visited:
            return
        visiting.add(key)
        for child in graph.get(key, set()):
            visit(child, [*trail, child])
        visiting.remove(key)
        visited.add(key)

    for key in graph:
        visit(key, [key])
    return [
        _issue("conditional_cycle", f"{path}.field_key", "Conditional visibility may not contain a cycle.")
        for key, edges in references.items()
        if key in cyclic_keys
        for _reference, path in edges
    ]


def _fields(forms: Iterable[object], prefix: str = "forms") -> Iterable[tuple[dict[str, Any], str]]:
    for form_index, form in enumerate(forms):
        if not isinstance(form, dict):
            continue
        form_path = prefix if prefix != "forms" else f"forms[{form_index}]"
        for section_index, section in enumerate(_items(form.get("sections"))):
            if not isinstance(section, dict):
                continue
            for field_index, field in enumerate(_items(section.get("fields"))):
                if isinstance(field, dict):
                    yield field, f"{form_path}.sections[{section_index}].fields[{field_index}]"


def _items(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _stable_key_issue(value: object, path: str) -> list[DefinitionIssue]:
    if not isinstance(value, str) or len(value) > 100 or _STABLE_KEY.fullmatch(value) is None:
        return [_issue("invalid_stable_key", path, "Stable keys must be lowercase identifiers.")]
    return []


def _text_issues(value: object, path: str, maximum: int) -> list[DefinitionIssue]:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        return [_issue("invalid_text", path, "Text is required and exceeds the supported length.")]
    return []


def _optional_text_issues(value: object, path: str) -> list[DefinitionIssue]:
    if not isinstance(value, str):
        return [_issue("invalid_text", path, "Text must be a string.")]
    return []


def _whole_number_issues(value: object, path: str) -> list[DefinitionIssue]:
    if type(value) is not int:
        return [_issue("invalid_sort_order", path, "Sort order must be an integer.")]
    return []


def _issue(code: str, path: str, message: str) -> DefinitionIssue:
    return DefinitionIssue(code=code, path=path, message=message)
