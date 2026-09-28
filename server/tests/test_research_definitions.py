import pytest

from fde_api.research import answers
from fde_api.research.definitions import validate_research_definition


def valid_definition():
    return {
        "forms": [
            {
                "form_key": "role_interview",
                "name": "Role interview",
                "description": "",
                "subject_type": "role",
                "sort_order": 10,
                "sections": [
                    {
                        "section_key": "context",
                        "name": "Context",
                        "description": "",
                        "sort_order": 10,
                        "fields": [
                            {
                                "field_key": "current_state",
                                "name": "Current state",
                                "help_text": "",
                                "type": "single_choice",
                                "is_required": True,
                                "options": {"choices": ["yes", "no"]},
                                "sort_order": 10,
                            }
                        ],
                    }
                ],
            }
        ]
    }


def form_with_condition(field_key: str, operator: str, value: object):
    definition = valid_definition()
    definition["forms"][0]["sections"][0]["fields"].append(
        {
            "field_key": "conditional_notes",
            "name": "Conditional notes",
            "help_text": "",
            "type": "long_text",
            "is_required": False,
            "options": {},
            "sort_order": 20,
            "condition": {
                "field_key": field_key,
                "operator": operator,
                "value": value,
            },
        }
    )
    return definition


def typed_condition_definition(field_type, options, operator, value=None, *, include_value=True):
    definition = form_with_condition("current_state", operator, value)
    controller = definition["forms"][0]["sections"][0]["fields"][0]
    controller["type"] = field_type
    controller["options"] = options
    if not include_value:
        definition["forms"][0]["sections"][0]["fields"][1]["condition"].pop("value")
    return definition


def test_validator_rejects_unknown_condition_reference():
    """Dropping reference validation would publish a field that can never resolve."""
    issues = validate_research_definition(form_with_condition("missing", "equals", "yes"))

    assert [(issue.code, issue.path) for issue in issues] == [
        (
            "unknown_condition_field",
            "forms[0].sections[0].fields[1].condition.field_key",
        )
    ]


def test_validator_rejects_conditional_cycle():
    """A missing graph check would make visibility evaluation recursive and undefined."""
    definition = form_with_condition("conditional_notes", "equals", "yes")
    definition["forms"][0]["sections"][0]["fields"][1]["condition"][
        "field_key"
    ] = "current_state"
    definition["forms"][0]["sections"][0]["fields"][0]["condition"] = {
        "field_key": "conditional_notes",
        "operator": "equals",
        "value": "yes",
    }

    issues = validate_research_definition(definition)

    assert [(issue.code, issue.path) for issue in issues] == [
        ("conditional_cycle", "forms[0].sections[0].fields[0].condition.field_key"),
        ("conditional_cycle", "forms[0].sections[0].fields[1].condition.field_key"),
    ]


@pytest.mark.parametrize(
    ("field_type", "options", "operator", "value", "code", "suffix"),
    [
        ("short_text", {}, "equals", 1, "invalid_condition_value", "value"),
        ("long_text", {}, "contains", [], "invalid_condition_value", "value"),
        ("integer", {}, "equals", "1", "invalid_condition_value", "value"),
        ("decimal", {}, "equals", True, "invalid_condition_value", "value"),
        ("decimal", {}, "equals", 1, "invalid_condition_value", "value"),
        ("decimal", {}, "equals", 1.25, "invalid_condition_value", "value"),
        ("short_text", {}, "equals", " ready ", "invalid_condition_value", "value"),
        ("long_text", {}, "contains", "", "invalid_condition_value", "value"),
        ("date", {}, "equals", "2026/08/24", "invalid_condition_value", "value"),
        ("single_choice", {"choices": ["yes", "no"]}, "contains", "yes", "invalid_condition_operator", "operator"),
        ("single_choice", {"choices": ["yes", "no"]}, "equals", "maybe", "invalid_condition_value", "value"),
        ("multi_choice", {"choices": ["yes", "no"]}, "equals", "yes", "invalid_condition_operator", "operator"),
        ("multi_choice", {"choices": ["yes", "no"]}, "contains", "maybe", "invalid_condition_value", "value"),
        ("rich_text", {}, "equals", "text", "invalid_condition_operator", "operator"),
        ("table", {"columns": []}, "equals", [], "invalid_condition_operator", "operator"),
        ("file_reference", {"max_files": 1}, "equals", "file-1", "invalid_condition_operator", "operator"),
    ],
)
def test_validator_rejects_condition_operators_and_values_that_do_not_match_the_referenced_field(
    field_type, options, operator, value, code, suffix
):
    """A typed condition that cannot compare a normalized answer must never be persisted."""
    definition = typed_condition_definition(field_type, options, operator, value)

    issues = validate_research_definition(definition)

    assert [(issue.code, issue.path) for issue in issues] == [
        (code, f"forms[0].sections[0].fields[1].condition.{suffix}")
    ]


@pytest.mark.parametrize(
    ("field_type", "options", "operator", "value", "include_value"),
    [
        ("short_text", {}, "contains", "yes", True),
        ("long_text", {}, "not_equals", "no", True),
        ("integer", {}, "equals", 1, True),
        ("decimal", {}, "equals", "1.25", True),
        ("decimal", {}, "not_equals", "123456789012345678901234567890.1234567890123456789", True),
        ("date", {}, "equals", "2026-08-24", True),
        ("single_choice", {"choices": ["yes", "no"]}, "equals", "yes", True),
        ("multi_choice", {"choices": ["yes", "no"]}, "contains", "no", True),
        ("rich_text", {}, "is_empty", None, False),
        ("table", {"columns": []}, "is_empty", None, False),
        ("file_reference", {"max_files": 1}, "is_empty", None, False),
    ],
)
def test_validator_accepts_condition_values_that_match_the_answer_contract(
    field_type, options, operator, value, include_value
):
    """Rejecting these values would make a valid server snapshot impossible to save again."""
    definition = typed_condition_definition(
        field_type, options, operator, value, include_value=include_value
    )

    assert validate_research_definition(definition) == []


def test_validator_rejects_integer_options_and_conditions_outside_json_safe_range():
    """A published integer definition must not admit values the desktop cannot represent exactly."""
    definition = typed_condition_definition(
        "integer",
        {"minimum": -9_007_199_254_740_992, "maximum": 9_007_199_254_740_992},
        "equals",
        9_007_199_254_740_992,
    )

    assert [(issue.code, issue.path) for issue in validate_research_definition(definition)] == [
        ("invalid_field_option_value", "forms[0].sections[0].fields[0].options.maximum"),
        ("invalid_field_option_value", "forms[0].sections[0].fields[0].options.minimum"),
        ("invalid_condition_value", "forms[0].sections[0].fields[1].condition.value"),
    ]


@pytest.mark.parametrize("value", ["1e100000", "1e-100000", "1e1000000000", "not-a-decimal"])
def test_validator_reports_extreme_or_malformed_decimal_conditions_without_expansion(
    value, monkeypatch
):
    """A definition issue, never a giant allocation or parser exception, is the boundary."""
    def fail_if_formatted(*_args, **_kwargs):
        raise AssertionError("unbounded decimal reached plain formatting")

    monkeypatch.setattr(answers, "format", fail_if_formatted, raising=False)
    definition = typed_condition_definition("decimal", {}, "equals", value)

    assert [
        (issue.code, issue.path) for issue in validate_research_definition(definition)
    ] == [
        (
            "invalid_condition_value",
            "forms[0].sections[0].fields[1].condition.value",
        )
    ]


@pytest.mark.parametrize("value", ["\ufeffready\ufeff", "\u0085ready\u0085"])
def test_validator_accepts_non_ascii_text_edge_characters_as_content(value):
    """Serializer round trips use the same explicit ASCII whitespace contract as answers."""
    definition = typed_condition_definition("short_text", {}, "equals", value)

    assert validate_research_definition(definition) == []


def test_validator_applies_typed_value_rules_inside_nested_condition_groups():
    """Nested all/any groups must not bypass the referenced field's answer contract."""
    definition = typed_condition_definition("integer", {}, "equals", 1)
    definition["forms"][0]["sections"][0]["fields"][1]["condition"] = {
        "operator": "all",
        "conditions": [
            {
                "operator": "any",
                "conditions": [
                    {
                        "field_key": "current_state",
                        "operator": "equals",
                        "value": "1",
                    }
                ],
            }
        ],
    }

    assert [
        (issue.code, issue.path) for issue in validate_research_definition(definition)
    ] == [
        (
            "invalid_condition_value",
            "forms[0].sections[0].fields[1].condition.conditions[0].conditions[0].value",
        )
    ]


def test_validator_reports_sorted_unique_key_and_field_config_issues():
    """Changing issue ordering or accepting bad configs would make editor feedback unstable."""
    definition = valid_definition()
    field = definition["forms"][0]["sections"][0]["fields"][0]
    field["type"] = "javascript"
    field["options"] = {"choices": ["yes", "yes"]}
    definition["forms"][0]["sections"].append(
        {
            "section_key": "context",
            "name": "Duplicate",
            "description": "",
            "sort_order": 20,
            "fields": [],
        }
    )

    issues = validate_research_definition(definition)

    assert [(issue.code, issue.path) for issue in issues] == [
        ("invalid_field_type", "forms[0].sections[0].fields[0].type"),
        ("duplicate_section_key", "forms[0].sections[1].section_key"),
    ]


def test_validator_rejects_unknown_options_and_nested_column_control_types():
    """Open config objects would persist executable values that no renderer is allowed to run."""
    definition = valid_definition()
    field = definition["forms"][0]["sections"][0]["fields"][0]
    field["options"] = {"choices": ["yes", "no"], "python": "import os"}
    table = {
        "field_key": "line_items",
        "name": "Line items",
        "help_text": "",
        "type": "table",
        "is_required": False,
        "options": {"columns": [{"key": "unsafe", "name": "Unsafe", "type": "javascript"}]},
        "sort_order": 20,
    }
    definition["forms"][0]["sections"][0]["fields"].append(table)

    issues = validate_research_definition(definition)

    assert [(issue.code, issue.path) for issue in issues] == [
        ("unknown_field_option", "forms[0].sections[0].fields[0].options.python"),
        ("invalid_table_column_type", "forms[0].sections[0].fields[1].options.columns[0].type"),
    ]


def test_validator_rejects_invalid_file_limits_and_table_choice_columns():
    """A published form must not defer impossible file or choice constraints to runtime."""
    definition = valid_definition()
    definition["forms"][0]["sections"][0]["fields"].extend([
        {"field_key": "files", "name": "Files", "help_text": "", "type": "file_reference", "is_required": False, "options": {"max_files": True}, "sort_order": 20},
        {"field_key": "table", "name": "Table", "help_text": "", "type": "table", "is_required": False, "options": {"columns": [{"key": "state", "name": "State", "type": "single_choice", "options": {"choices": ["ok", "ok"]}}]}, "sort_order": 30},
    ])

    assert [issue.code for issue in validate_research_definition(definition)] == [
        "invalid_file_max_files", "invalid_table_choice_options"
    ]


def test_validator_rejects_choice_defaults_outside_declared_choices():
    """A default the answer contract rejects must not survive a successful template PUT."""
    definition = valid_definition()
    field = definition["forms"][0]["sections"][0]["fields"][0]
    field["options"]["default_value"] = "maybe"
    field["type"] = "multi_choice"
    field["options"]["default_value"] = ["yes", "maybe"]

    assert [(issue.code, issue.path) for issue in validate_research_definition(definition)] == [
        (
            "invalid_choice_default",
            "forms[0].sections[0].fields[0].options.default_value",
        )
    ]


def test_validator_rejects_blank_malformed_and_duplicate_table_column_keys():
    """Duplicate or unstable column keys make a persisted table answer impossible to address."""
    definition = valid_definition()
    definition["forms"][0]["sections"][0]["fields"].append(
        {
            "field_key": "table",
            "name": "Table",
            "help_text": "",
            "type": "table",
            "is_required": False,
            "options": {
                "columns": [
                    {"key": "", "name": "Blank"},
                    {"key": "item", "name": "First"},
                    {"key": "item", "name": "Duplicate"},
                    {"key": "Invalid-Key", "name": "Malformed"},
                ]
            },
            "sort_order": 20,
        }
    )

    assert [(issue.code, issue.path) for issue in validate_research_definition(definition)] == [
        ("invalid_table_column_key", "forms[0].sections[0].fields[1].options.columns[0].key"),
        ("duplicate_table_column_key", "forms[0].sections[0].fields[1].options.columns[2].key"),
        ("invalid_table_column_key", "forms[0].sections[0].fields[1].options.columns[3].key"),
    ]


@pytest.mark.parametrize(
    ("field_type", "options", "code"),
    [
        ("short_text", {"placeholder": 7}, "invalid_field_option_value"),
        ("long_text", {"min_length": -1}, "invalid_field_option_value"),
        ("rich_text", {"default_value": {}}, "invalid_field_option_value"),
        ("integer", {"minimum": True}, "invalid_field_option_value"),
        ("decimal", {"maximum": "10"}, "invalid_field_option_value"),
        ("date", {"minimum": 20260824}, "invalid_field_option_value"),
    ],
)
def test_validator_rejects_option_values_the_closed_response_contract_cannot_parse(
    field_type, options, code
):
    """A successful PUT must always serialize to the renderer's closed DTO contract."""
    definition = valid_definition()
    field = definition["forms"][0]["sections"][0]["fields"][0]
    field["type"] = field_type
    field["options"] = options

    assert [issue.code for issue in validate_research_definition(definition)] == [code]


@pytest.mark.parametrize(
    ("field_type", "options", "path"),
    [
        ("short_text", {"min_length": 10, "max_length": 5}, "max_length"),
        ("long_text", {"min_length": 2, "max_length": 1}, "max_length"),
        ("integer", {"minimum": 5, "maximum": 4}, "maximum"),
        ("decimal", {"minimum": 1.5, "maximum": 1.25}, "maximum"),
    ],
)
def test_validator_rejects_reversed_deterministic_option_ranges(
    field_type, options, path
):
    """A legal definition cannot configure a range no normalized answer can satisfy."""
    definition = valid_definition()
    field = definition["forms"][0]["sections"][0]["fields"][0]
    field["type"] = field_type
    field["options"] = options

    assert [
        (issue.code, issue.path) for issue in validate_research_definition(definition)
    ] == [
        (
            "invalid_field_option_value",
            f"forms[0].sections[0].fields[0].options.{path}",
        )
    ]


def test_validator_rejects_a_reversed_table_column_text_range():
    """Table columns use the same deterministic answer option contract as fields."""
    definition = valid_definition()
    definition["forms"][0]["sections"][0]["fields"].append(
        {
            "field_key": "table",
            "name": "Table",
            "help_text": "",
            "type": "table",
            "is_required": False,
            "options": {
                "columns": [
                    {
                        "key": "title",
                        "name": "Title",
                        "type": "short_text",
                        "options": {"min_length": 4, "max_length": 3},
                    }
                ]
            },
            "sort_order": 20,
        }
    )

    assert [
        (issue.code, issue.path) for issue in validate_research_definition(definition)
    ] == [
        (
            "invalid_table_column_option_value",
            "forms[0].sections[0].fields[1].options.columns[0].options.max_length",
        )
    ]


def test_validator_closes_and_validates_table_column_options_and_names():
    """Table column serializer output must obey the same option schema as top-level fields."""
    definition = valid_definition()
    definition["forms"][0]["sections"][0]["fields"].append(
        {
            "field_key": "table",
            "name": "Table",
            "help_text": "",
            "type": "table",
            "is_required": False,
            "options": {
                "columns": [
                    {"key": "title", "name": "", "type": "short_text", "options": {"script": "x"}},
                    {"key": "state", "name": "State", "type": "single_choice", "options": {"choices": ["open"], "default_value": "closed"}},
                ]
            },
            "sort_order": 20,
        }
    )

    assert [(issue.code, issue.path) for issue in validate_research_definition(definition)] == [
        ("invalid_table_column_name", "forms[0].sections[0].fields[1].options.columns[0].name"),
        ("unknown_table_column_option", "forms[0].sections[0].fields[1].options.columns[0].options.script"),
        ("invalid_table_choice_default", "forms[0].sections[0].fields[1].options.columns[1].options.default_value"),
    ]
