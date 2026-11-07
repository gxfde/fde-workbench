"""场景内容校验（V3.2 G2，G1 §4.5 规则的实现）。

纯函数：只读入参与返回值，**不碰数据库**。返回错误码列表（空 = 通过），
错误码 → 中文文案的映射在 ``ERROR_MESSAGES``，供 API 层回显。

纪律：错误码是**稳定的机器可读契约**（前端与测试按码断言），文案可改、码不改。
"""
from __future__ import annotations

from typing import Any

from fde_api.simulation.schemas import (
    CONTENT_REQUIRED_KEYS,
    DISCLOSURE_STAGES,
    FAULT_ERRORS,
    HIDDEN_FACT_REQUIRED_KEYS,
    HIDDEN_REQUIRED_KEYS,
    REFERENCE_REQUIRED_KEYS,
    RUBRIC_REQUIRED_KEYS,
    VISIBLE_REQUIRED_KEYS,
)

# 变体覆盖允许的键（G1 §4.2 variant_overrides）
VARIANT_OVERRIDE_KEYS = (
    "extra_constraints",
    "budget",
    "timeline",
    "probe_tolerance",
    "conflicts",
    "change_events",
    "suppress_facts",
    "extra_known_systems",
)

# 允许在 variant_overrides 内出现的变体名（normal 即基线，无需覆盖）
VARIANT_OVERRIDE_VARIANTS = ("vague", "complex")

ERROR_MESSAGES: dict[str, str] = {
    "scenario_empty": "场景内容缺少必需字段。",
    "scenario_key_mismatch": "场景 case_code 与 scenario_key 不一致。",
    "invalid_disclosure_stage": "隐藏事实的 disclosure_stage 不合法。",
    "invalid_variant_override": "变体覆盖包含非法键或非法变体名。",
    "rubric_incomplete": "评分 Rubric 不完整（must_identify/must_avoid/must_produce 均须非空）。",
    "missing_reference": "参考答案缺失或不完整。",
    "invalid_fault_injection": "故障注入定义不合法。",
    "invalid_tags": "标签必须是字符串列表。",
}


def _is_nonempty_str_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(
        isinstance(item, str) and item.strip() for item in value
    )


def validate_scenario(
    content: Any,
    reference: Any,
    *,
    scenario_key: str,
    variant: str = "normal",
    split: str = "train",
) -> list[str]:
    """校验场景内容，返回错误码列表（空列表 = 通过）。

    规则编号与 G1 §4.5 一一对应；新增规则只追加、不改既有码语义。
    """
    errors: list[str] = []

    if not isinstance(content, dict):
        return ["scenario_empty"]

    # 规则 1：content 必需键
    for key in CONTENT_REQUIRED_KEYS:
        if key not in content:
            errors.append("scenario_empty")
            break

    # 规则 2：case_code 与业务键一致
    case_code = content.get("case_code")
    if not isinstance(case_code, str) or case_code != scenario_key:
        errors.append("scenario_key_mismatch")

    # 规则 3：visible 段
    visible = content.get("visible")
    if not isinstance(visible, dict):
        errors.append("scenario_empty")
    else:
        for key in VISIBLE_REQUIRED_KEYS:
            if key not in visible:
                errors.append("scenario_empty")
                break
        brief = visible.get("initial_brief")
        if not _is_nonempty_str_list(brief):
            errors.append("scenario_empty")
        known = visible.get("known_systems")
        if not isinstance(known, list):
            errors.append("scenario_empty")
        constraints = visible.get("constraints")
        if not isinstance(constraints, dict):
            errors.append("scenario_empty")

    # 规则 4：hidden 段与事实项
    hidden = content.get("hidden")
    if not isinstance(hidden, dict):
        errors.append("scenario_empty")
    else:
        for key in HIDDEN_REQUIRED_KEYS:
            if key not in hidden:
                errors.append("scenario_empty")
                break
        facts = hidden.get("facts")
        if not isinstance(facts, list) or not facts:
            errors.append("scenario_empty")
        else:
            seen_ids: set[str] = set()
            for fact in facts:
                if not isinstance(fact, dict):
                    errors.append("scenario_empty")
                    continue
                for key in HIDDEN_FACT_REQUIRED_KEYS:
                    if key not in fact:
                        errors.append("scenario_empty")
                        break
                stage = fact.get("disclosure_stage")
                if stage not in DISCLOSURE_STAGES:
                    errors.append("invalid_disclosure_stage")
                fact_id = fact.get("fact_id")
                if isinstance(fact_id, str):
                    if fact_id in seen_ids:
                        errors.append("scenario_empty")
                    seen_ids.add(fact_id)

    # 规则 5：误导性诉求（客户初始诉求）非空
    misleading = content.get("misleading_request")
    if not isinstance(misleading, str) or not misleading.strip():
        errors.append("scenario_empty")

    # 规则 6：变体覆盖合法
    overrides = content.get("variant_overrides")
    if overrides is not None:
        if not isinstance(overrides, dict):
            errors.append("invalid_variant_override")
        else:
            for name, override in overrides.items():
                if name not in VARIANT_OVERRIDE_VARIANTS:
                    errors.append("invalid_variant_override")
                    continue
                if not isinstance(override, dict):
                    errors.append("invalid_variant_override")
                    continue
                for key in override:
                    if key not in VARIANT_OVERRIDE_KEYS:
                        errors.append("invalid_variant_override")

    # 规则 7：故障注入定义合法
    faults = content.get("fault_injection")
    if faults is not None:
        if not isinstance(faults, list):
            errors.append("invalid_fault_injection")
        else:
            for fault in faults:
                if not isinstance(fault, dict):
                    errors.append("invalid_fault_injection")
                    continue
                error_code = fault.get("error")
                if error_code not in FAULT_ERRORS:
                    errors.append("invalid_fault_injection")
                if not isinstance(fault.get("match"), dict):
                    errors.append("invalid_fault_injection")

    # 规则 8：参考答案与 Rubric（blind 集强制）
    if reference is not None and not isinstance(reference, dict):
        errors.append("missing_reference")
    elif reference is None:
        if split == "blind":
            errors.append("missing_reference")
    else:
        for key in REFERENCE_REQUIRED_KEYS:
            if key not in reference:
                errors.append("missing_reference")
                break
        outcomes = reference.get("expected_outcomes")
        if not _is_nonempty_str_list(outcomes):
            errors.append("missing_reference")
        criteria = reference.get("acceptance_criteria")
        if not _is_nonempty_str_list(criteria):
            errors.append("missing_reference")
        rubric = reference.get("rubric")
        if not isinstance(rubric, dict):
            errors.append("rubric_incomplete")
        else:
            for key in RUBRIC_REQUIRED_KEYS:
                bucket = rubric.get(key)
                if not _is_nonempty_str_list(bucket):
                    errors.append("rubric_incomplete")
                    break

    # 变体自身的合法值
    if variant not in ("normal", "vague", "complex"):
        errors.append("invalid_variant_override")

    # 去重保序
    return list(dict.fromkeys(errors))
