"""画像样本脱敏（AF2-WP1）：类型感知掩码——列名启发 + 值形态正则双检测。

纪律（04 §3.2）：原始敏感行留在授权域，画像产物只存统计与掩码样本；
落库 JSON 里不得出现敏感列原文（测试钉
``test_samples_mask_pii_by_name_and_value_patterns`` /
``test_profile_row_persisted_and_readable_via_model``）。

取向**保守**：列名命中敏感词即掩码（误掩比漏掩好——漏掩把 PII 泄进
产物，误掩只损失一点样本可读性）；``name`` 类宽词也算敏感。
"""
from __future__ import annotations

import re
from typing import Any

_PHONE = re.compile(r"1[3-9]\d{9}")
_IDCARD = re.compile(r"\d{17}[\dXx]")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

# 列名启发（子串匹配，小写化后比较）；中英双语词表
SENSITIVE_NAME_PATTERNS: tuple[str, ...] = (
    "phone", "mobile", "tel",
    "idcard", "id_card", "ssn", "passport",
    "email", "mail",
    "姓名", "手机", "电话", "身份证", "邮箱", "地址", "联系人",
    "name", "address",
)


def classify_column(name: str, values: list[str]) -> str | None:
    """列敏感类别：列名命中 → generic / 值形态主导 → 具体类别；不敏感 → None。

    值形态检测对全体非空值只要 ≥1 条命中即判敏感（保守取向）。
    """
    lowered = name.lower()
    by_name = any(pattern in lowered for pattern in SENSITIVE_NAME_PATTERNS)
    present = [value for value in values if value and value.strip()]
    if any(_IDCARD.fullmatch(value.strip()) for value in present):
        return "idcard"
    if any(_PHONE.fullmatch(value.strip()) for value in present):
        return "phone"
    if any(_EMAIL.fullmatch(value.strip()) for value in present):
        return "email"
    return "generic" if by_name else None


def mask_value(value: str, kind: str) -> str:
    """按类别掩码：phone 保留前 3 后 2；idcard 全掩；email 只留首字符与 @；
    generic 半掩（前 2 + ***）。空值原样返回。"""
    if not value:
        return value
    if kind == "idcard":
        return "*" * max(len(value), 6)
    if kind == "phone":
        stripped = value.strip()
        if _PHONE.fullmatch(stripped):
            return f"{stripped[:3]}****{stripped[-2:]}"
        return f"{stripped[:2]}***"
    if kind == "email":
        local, sep, domain = value.partition("@")
        if sep:
            return f"{local[:1]}***@{domain[:1]}***"
        return f"{value[:2]}***"
    # generic
    return f"{value[:2]}***"


def mask_sample_rows(
    column_types: dict[str, str],
    rows: list[dict[str, Any]],
    all_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """样本行脱敏：先按列定类别（值形态看全体行，列名启发兜底），再逐值掩码。

    非敏感列原值保留（授权域内产物的可读性）；敏感列任何形态都不放原文。
    """
    source = rows if all_rows is None else all_rows
    kinds: dict[str, str | None] = {}
    for name in column_types:
        values = [str(row.get(name, "")) for row in source]
        kinds[name] = classify_column(name, values)
    masked_rows: list[dict[str, Any]] = []
    for row in rows:
        masked: dict[str, Any] = {}
        for name, raw in row.items():
            value = str(raw)
            kind = kinds.get(name)
            masked[name] = mask_value(value, kind) if kind is not None else value
        masked_rows.append(masked)
    return masked_rows


def mask_transform_output(
    plan: dict[str, Any],
    tables: dict[str, list[dict[str, Any]]],
    rows: list[dict[str, Any]],
    step_order: list[str],
) -> list[dict[str, Any]]:
    """Reuse WP1 classification and carry sensitive columns through select, rename and join."""
    if not rows:
        return []

    def sensitive_columns(columns: set[str], source: list[dict[str, Any]]) -> set[str]:
        return {
            name for name in columns
            if classify_column(name, [str(row.get(name, "")) for row in source]) is not None
        }

    source = tables[plan["source"]["table"]]
    columns = {name for row in source for name in row}
    sensitive = sensitive_columns(columns, source)
    steps_by_id = {step["id"]: step for step in plan["steps"]}
    for step_id in step_order:
        step = steps_by_id[step_id]
        params = step["params"]
        if step["op"] == "select":
            sensitive.intersection_update(params["columns"])
        elif step["op"] == "rename":
            mapping = params["mapping"]
            sensitive = {mapping.get(name, name) for name in sensitive}
            sensitive.update(sensitive_columns(set(mapping.values()), []))
        elif step["op"] == "join":
            sensitive.update(sensitive_columns(set(params.get("right_columns") or []), tables[params["right_table"]]))

    output_columns = [column["name"] for column in plan["output"]["columns"]]
    sensitive.update(sensitive_columns(set(output_columns), rows))
    masked_rows = []
    for row in rows:
        masked = {}
        for name in output_columns:
            value = row.get(name)
            masked[name] = "***" if name in sensitive and value is not None and value != "" else value
        masked_rows.append(masked)
    return masked_rows
