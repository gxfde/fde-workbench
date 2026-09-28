from decimal import Decimal
from time import monotonic

import pytest

from fde_api.research import answers
from fde_api.research.answers import ResearchValidationError, normalize_decimal, validate_answer


def field(field_type: str, options: dict | None = None) -> dict:
    return {"field_key": "answer", "type": field_type, "options": options or {}}


@pytest.mark.parametrize(
    ("field_type", "value", "options", "expected"),
    [
        ("short_text", " concise ", {}, "concise"),
        ("long_text", "A detailed note.", {}, "A detailed note."),
        (
            "rich_text",
            {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "safe"}]}]},
            {},
            {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "safe"}]}]},
        ),
        ("integer", 12, {}, 12),
        ("decimal", Decimal("12.3400"), {}, "12.34"),
        ("date", "2026-08-22", {}, "2026-08-22"),
        ("single_choice", "yes", {"choices": ["yes", "no"]}, "yes"),
        ("multi_choice", ["no", "yes", "no"], {"choices": ["yes", "no"]}, ["no", "yes"]),
        (
            "table",
            [{"name": "Ada", "count": 2}],
            {"columns": [{"key": "name", "name": "Name", "type": "short_text"}, {"key": "count", "name": "Count", "type": "integer"}]},
            [{"name": "Ada", "count": 2}],
        ),
        ("file_reference", [" file-2 ", "file-1", "file-2"], {"max_files": 2}, ["file-2", "file-1"]),
    ],
)
def test_each_field_type_normalizes_a_hand_written_literal(field_type, value, options, expected):
    """Changing a type branch or its normalizer would reject or alter a documented answer literal."""
    assert validate_answer(field(field_type, options), value) == expected


def test_integer_answers_are_limited_to_the_exact_json_safe_range():
    """Persisting a larger Python integer would silently lose precision in the desktop JSON runtime."""
    assert validate_answer(field("integer"), 9_007_199_254_740_991) == 9_007_199_254_740_991
    assert validate_answer(field("integer"), -9_007_199_254_740_991) == -9_007_199_254_740_991
    for value in (9_007_199_254_740_992, -9_007_199_254_740_992):
        with pytest.raises(ResearchValidationError, match="invalid_research_answer"):
            validate_answer(field("integer"), value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (
            "1234567890123456789012345678901234567890.1234567890123456789012345678900",
            "1234567890123456789012345678901234567890.12345678901234567890123456789",
        ),
        (
            "99999999999999999999999999999999999999999999999999",
            "99999999999999999999999999999999999999999999999999",
        ),
    ],
)
def test_decimal_normalization_preserves_large_and_high_precision_digits(value, expected):
    """Decimal normalization must not use a context that rounds persisted answers."""
    assert validate_answer(field("decimal"), value) == expected


@pytest.mark.parametrize(
    "value",
    ["1e100000", "1e-100000", "-1e1000000000", "0e1000000000", "0e-1000000000"],
)
def test_extreme_decimal_exponents_are_rejected_before_plain_expansion(
    value, monkeypatch
):
    """A short exponent literal must be bounded before format can allocate its plain form."""
    def fail_if_formatted(*_args, **_kwargs):
        raise AssertionError("unbounded decimal reached plain formatting")

    monkeypatch.setattr(answers, "format", fail_if_formatted, raising=False)
    started = monotonic()

    with pytest.raises(ResearchValidationError, match="invalid_research_answer"):
        normalize_decimal(value)

    assert monotonic() - started < 0.25


@pytest.mark.parametrize(
    "value",
    [
        "9" * 101,
        "0." + ("0" * 100) + "1",
        "0" * 257,
    ],
)
def test_decimal_business_limits_reject_oversized_plain_values(value):
    """Answers beyond the hand-checked digit, scale, or input limits stay bounded."""
    with pytest.raises(ResearchValidationError, match="invalid_research_answer"):
        normalize_decimal(value)


def test_normalize_decimal_maps_parser_failures_to_the_research_error():
    """Definition and answer callers must never observe decimal module exceptions."""
    class InvalidStringInteger(int):
        def __str__(self):
            raise ValueError("cannot stringify")

    for value in ("not-a-decimal", InvalidStringInteger(1)):
        with pytest.raises(ResearchValidationError, match="invalid_research_answer"):
            normalize_decimal(value)


@pytest.mark.parametrize("value", ["1_0", "١.٢", "\u00851\u0085"])
def test_decimal_input_uses_the_same_explicit_ascii_literal_grammar_as_the_client(value):
    """Runtime-specific Decimal syntax must not create server/client normalization drift."""
    with pytest.raises(ResearchValidationError, match="invalid_research_answer"):
        normalize_decimal(value)


@pytest.mark.parametrize("value", ["\ufeffready\ufeff", "\u0085ready\u0085"])
def test_text_answers_treat_non_ascii_edge_characters_as_content(value):
    """Only explicit ASCII edge whitespace is normalized away from stored text answers."""
    assert validate_answer(field("short_text"), value) == value


@pytest.mark.parametrize(
    ("field_type", "value", "options"),
    [
        ("short_text", 1, {}),
        ("long_text", [], {}),
        ("rich_text", {"type": "script", "content": []}, {}),
        ("integer", True, {}),
        ("integer", "12", {}),
        ("decimal", True, {}),
        ("date", "2026/08/22", {}),
        ("single_choice", "unknown", {"choices": ["yes", "no"]}),
        ("multi_choice", ["unknown"], {"choices": ["yes", "no"]}),
        ("table", [{"name": "Ada", "unknown": "no"}], {"columns": [{"key": "name", "name": "Name", "type": "short_text"}]}),
        ("file_reference", ["file-1", ""], {}),
    ],
)
def test_invalid_answer_values_are_rejected(field_type, value, options):
    """Removing a type or shape guard would let an unsupported answer enter the research record."""
    with pytest.raises(ResearchValidationError, match="invalid_research_answer"):
        validate_answer(field(field_type, options), value)


def test_rich_text_rejects_unknown_nodes_and_script_text():
    """Permitting arbitrary rich-text nodes or script content would store executable markup in answers."""
    with pytest.raises(ResearchValidationError, match="invalid_research_answer"):
        validate_answer(field("rich_text"), {"type": "doc", "content": [{"type": "image", "src": "x"}]})
    with pytest.raises(ResearchValidationError, match="invalid_research_answer"):
        validate_answer(field("rich_text"), {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "<script>x</script>"}]}]})


def test_file_references_respect_schema_maximum_and_a_custom_validator():
    """Dropping max_files or the validator hook would admit more files than the frozen form permits."""
    class PrefixValidator:
        def validate(self, reference):
            if not reference.startswith("owned-"):
                raise ResearchValidationError()
            return reference

    with pytest.raises(ResearchValidationError, match="invalid_research_answer"):
        validate_answer(field("file_reference", {"max_files": 1}), ["file-1", "file-2"])
    assert validate_answer(
        field("file_reference", {"max_files": 1}), ["owned-1"], file_reference_validator=PrefixValidator()
    ) == ["owned-1"]


def test_table_choice_column_uses_its_own_choices():
    """Ignoring table-column options would let a row use a value outside its defined choices."""
    column = {"key": "status", "name": "Status", "type": "single_choice", "options": {"choices": ["open", "closed"]}}
    assert validate_answer(field("table", {"columns": [column]}), [{"status": "open"}]) == [{"status": "open"}]
    with pytest.raises(ResearchValidationError, match="invalid_research_answer"):
        validate_answer(field("table", {"columns": [column]}), [{"status": "unknown"}])
