from __future__ import annotations

import math
import re
from datetime import date
from decimal import Decimal, DecimalException, InvalidOperation
from typing import Any, Protocol


class ResearchValidationError(ValueError):
    code = "invalid_research_answer"

    def __init__(self, message: str = "The research answer is invalid.") -> None:
        super().__init__(f"{self.code}: {message}")


class FileReferenceValidator(Protocol):
    """Boundary for later project-file ownership validation."""

    def validate(self, reference: str) -> str: ...


_FILE_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SCRIPT = re.compile(r"<\s*/?\s*script\b", re.IGNORECASE)
_DECIMAL_LITERAL = re.compile(
    r"^[+-]?(?:(?:[0-9]+(?:\.[0-9]*)?)|(?:\.[0-9]+))(?:[eE][+-]?[0-9]+)?$"
)
ASCII_EDGE_WHITESPACE = " \t\r\n"
MAX_DECIMAL_INPUT_CHARACTERS = 256
MAX_DECIMAL_SIGNIFICANT_DIGITS = 100
MAX_DECIMAL_ABSOLUTE_EXPONENT = 100
MAX_DECIMAL_INTEGER_DIGITS = 100
MAX_DECIMAL_SCALE = 100
MAX_DECIMAL_EXPANDED_CHARACTERS = 202
MIN_JSON_SAFE_INTEGER = -(2**53 - 1)
MAX_JSON_SAFE_INTEGER = 2**53 - 1


class ShapeFileReferenceValidator:
    """Accept stable reference identifiers only; file records do not exist yet."""

    def validate(self, reference: str) -> str:
        normalized = reference.strip() if isinstance(reference, str) else ""
        if not normalized or _FILE_REFERENCE.fullmatch(normalized) is None:
            raise ResearchValidationError("File references must be non-empty stable identifiers.")
        return normalized


DEFAULT_FILE_REFERENCE_VALIDATOR = ShapeFileReferenceValidator()


def validate_answer(
    field: dict[str, Any],
    value: object,
    *,
    file_reference_validator: FileReferenceValidator = DEFAULT_FILE_REFERENCE_VALIDATOR,
) -> object:
    """Validate one snapshot field's answer and return a JSON-safe normalized value."""
    field_type = field.get("type")
    options = field.get("options")
    if not isinstance(options, dict):
        raise ResearchValidationError()
    try:
        if field_type in {"short_text", "long_text"}:
            return _bounded_text(value, options)
        if field_type == "rich_text":
            return _rich_text(value)
        if field_type == "integer":
            return _bounded_number(_integer(value), options)
        if field_type == "decimal":
            return _bounded_decimal(_decimal(value), options)
        if field_type == "date":
            return _bounded_date(_date(value), options)
        if field_type == "single_choice":
            return _single_choice(value, options)
        if field_type == "multi_choice":
            return _multi_choice(value, options)
        if field_type == "table":
            return _table(value, options, file_reference_validator)
        if field_type == "file_reference":
            return _file_references(value, options, file_reference_validator)
    except ResearchValidationError:
        raise
    except (TypeError, ValueError, InvalidOperation):
        pass
    raise ResearchValidationError()


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise ResearchValidationError()
    return normalize_text(value)


def normalize_text(value: str) -> str:
    """Trim the explicit cross-runtime ASCII edge-whitespace contract only."""
    return value.strip(ASCII_EDGE_WHITESPACE)


def is_canonical_condition_text(value: object) -> bool:
    return isinstance(value, str) and bool(value) and normalize_text(value) == value


def _bounded_text(value: object, options: dict[str, Any]) -> str:
    text = _text(value)
    minimum = options.get("min_length")
    maximum = options.get("max_length")
    if (minimum is not None and (type(minimum) is not int or len(text) < minimum)) or (
        maximum is not None and (type(maximum) is not int or len(text) > maximum)
    ):
        raise ResearchValidationError("Text answer is outside the configured length.")
    return text


def _integer(value: object) -> int:
    if type(value) is not int or not MIN_JSON_SAFE_INTEGER <= value <= MAX_JSON_SAFE_INTEGER:
        raise ResearchValidationError("Integer answers must be JSON safe integers.")
    return value


def _decimal(value: object) -> str:
    return normalize_decimal(value)


def normalize_decimal(value: object) -> str:
    """Return a bounded exact plain string without context rounding or expansion DoS."""
    if type(value) is bool or not isinstance(value, (str, int, float, Decimal)):
        raise ResearchValidationError("Decimal answers must be finite decimal values.")
    if type(value) is float and not math.isfinite(value):
        raise ResearchValidationError("Decimal answers must be finite.")
    try:
        raw = str(value)
        if len(raw) > MAX_DECIMAL_INPUT_CHARACTERS:
            raise ResearchValidationError("Decimal answers exceed supported limits.")
        literal = normalize_text(raw)
        if _DECIMAL_LITERAL.fullmatch(literal) is None:
            raise ResearchValidationError("Decimal answers must use ASCII decimal notation.")
        decimal = Decimal(literal)
    except ResearchValidationError:
        raise
    except (DecimalException, TypeError, ValueError, OverflowError):
        raise ResearchValidationError("Decimal answers must be finite decimal values.") from None
    if not decimal.is_finite():
        raise ResearchValidationError("Decimal answers must be finite.")

    sign, tuple_digits, exponent = decimal.as_tuple()
    if not isinstance(exponent, int):
        raise ResearchValidationError("Decimal answers must be finite.")
    digits = list(tuple_digits)
    while len(digits) > 1 and digits[-1] == 0:
        digits.pop()
        exponent += 1
    significant_digits = len(digits)
    integer_digits = max(decimal.adjusted() + 1, 1)
    scale = max(-exponent, 0)
    expanded_characters = integer_digits + (scale + 1 if scale else 0) + sign
    if (
        significant_digits > MAX_DECIMAL_SIGNIFICANT_DIGITS
        or abs(exponent) > MAX_DECIMAL_ABSOLUTE_EXPONENT
        or integer_digits > MAX_DECIMAL_INTEGER_DIGITS
        or scale > MAX_DECIMAL_SCALE
        or expanded_characters > MAX_DECIMAL_EXPANDED_CHARACTERS
    ):
        raise ResearchValidationError("Decimal answers exceed supported limits.")

    normalized = format(decimal, "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    if decimal == 0:
        return "0"
    return normalized


def _bounded_number(value: int, options: dict[str, Any]) -> int:
    for key, comparison in (("minimum", lambda limit: value < limit), ("maximum", lambda limit: value > limit)):
        limit = options.get(key)
        if limit is not None and (type(limit) is not int or comparison(limit)):
            raise ResearchValidationError("Integer answer is outside the configured range.")
    return value


def _bounded_decimal(value: str, options: dict[str, Any]) -> str:
    numeric = Decimal(value)
    for key, comparison in (("minimum", lambda limit: numeric < limit), ("maximum", lambda limit: numeric > limit)):
        raw_limit = options.get(key)
        if raw_limit is None:
            continue
        try:
            limit = Decimal(str(raw_limit))
        except (InvalidOperation, ValueError):
            raise ResearchValidationError("Decimal field options are invalid.") from None
        if not limit.is_finite() or comparison(limit):
            raise ResearchValidationError("Decimal answer is outside the configured range.")
    return value


def _date(value: object) -> str:
    if not isinstance(value, str):
        raise ResearchValidationError("Date answers must use YYYY-MM-DD.")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ResearchValidationError("Date answers must use YYYY-MM-DD.") from None
    if parsed.isoformat() != value:
        raise ResearchValidationError("Date answers must use YYYY-MM-DD.")
    return value


def _bounded_date(value: str, options: dict[str, Any]) -> str:
    for key, comparison in (("minimum", lambda limit: value < limit), ("maximum", lambda limit: value > limit)):
        limit = options.get(key)
        if limit is not None and (not isinstance(limit, str) or _date(limit) != limit or comparison(limit)):
            raise ResearchValidationError("Date answer is outside the configured range.")
    return value


def _choices(options: dict[str, Any]) -> list[str]:
    choices = options.get("choices")
    if not isinstance(choices, list) or any(not isinstance(item, str) for item in choices):
        raise ResearchValidationError("Choice field options are invalid.")
    return choices


def _single_choice(value: object, options: dict[str, Any]) -> str:
    if not isinstance(value, str) or value not in _choices(options):
        raise ResearchValidationError("Choice answer is not one of the defined options.")
    return value


def _multi_choice(value: object, options: dict[str, Any]) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ResearchValidationError("Multi-choice answers must be lists of choices.")
    choices = _choices(options)
    if any(item not in choices for item in value):
        raise ResearchValidationError("Choice answer is not one of the defined options.")
    return list(dict.fromkeys(value))


def _table(
    value: object, options: dict[str, Any], validator: FileReferenceValidator
) -> list[dict[str, object]]:
    columns = options.get("columns")
    if not isinstance(value, list) or not isinstance(columns, list):
        raise ResearchValidationError("Table answers must be rows matching the defined columns.")
    normalized_columns: dict[str, dict[str, Any]] = {}
    for column in columns:
        if not isinstance(column, dict) or not isinstance(column.get("key"), str):
            raise ResearchValidationError("Table columns are invalid.")
        normalized_columns[column["key"]] = column
    if len(normalized_columns) != len(columns):
        raise ResearchValidationError("Table columns must be unique.")
    result: list[dict[str, object]] = []
    for row in value:
        if not isinstance(row, dict) or set(row) != set(normalized_columns):
            raise ResearchValidationError("Table rows must contain exactly the defined columns.")
        result.append(
            {
                key: validate_answer(
                    {"type": column.get("type", "short_text"), "options": column.get("options", {})},
                    row[key],
                    file_reference_validator=validator,
                )
                for key, column in normalized_columns.items()
            }
        )
    return result


def _file_references(
    value: object, options: dict[str, Any], validator: FileReferenceValidator
) -> list[str]:
    if not isinstance(value, list):
        raise ResearchValidationError("File references must be a list.")
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise ResearchValidationError("File references must be stable identifiers.")
        normalized = validator.validate(item)
        if normalized not in seen:
            result.append(normalized)
            seen.add(normalized)
    maximum = options.get("max_files")
    if type(maximum) is not int or maximum < 1:
        raise ResearchValidationError("File reference fields require a positive max_files option.")
    if len(result) > maximum:
        raise ResearchValidationError("File reference count exceeds max_files.")
    return result


def _rich_text(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"type", "content"} or value.get("type") != "doc":
        raise ResearchValidationError("Rich text must be a document.")
    content = value.get("content")
    if not isinstance(content, list):
        raise ResearchValidationError("Rich text document content must be a list.")
    return {"type": "doc", "content": [_paragraph(node) for node in content]}


def _paragraph(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"type", "content"} or value.get("type") != "paragraph":
        raise ResearchValidationError("Rich text only supports paragraph nodes.")
    content = value.get("content")
    if not isinstance(content, list):
        raise ResearchValidationError("Rich text paragraph content must be a list.")
    return {"type": "paragraph", "content": [_text_node(node) for node in content]}


def _text_node(value: object) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"type", "text"} or value.get("type") != "text" or not isinstance(value.get("text"), str):
        raise ResearchValidationError("Rich text only supports text nodes.")
    text = value["text"]
    if _SCRIPT.search(text):
        raise ResearchValidationError("Rich text may not contain script markup.")
    return {"type": "text", "text": text}
