"""discovery 抽取契约校验器（V3.1 P0-1）。

克隆 guidance/ai_schema.py 纪律：精确键集、条数上限、枚举闭集、来源定位
闭合、整批失败不部分写入。任务书 §5 七组示例收敛为 ``{facts, requirements}``
两组（fact_type 十值覆盖 roles/systems/processes/business_rules/open_questions，
语义等同、存储归一——00-gap-register P0-1 裁决 1.5/1.7）。
"""

from __future__ import annotations

from typing import Any, TypeGuard

FACT_TYPES = {
    "process", "role", "system", "rule", "data_object",
    "metric", "constraint", "pain_point", "decision", "open_question",
}
REQUIREMENT_TYPES = {"functional", "non_functional", "data", "integration", "security", "operational"}
PRIORITIES = {"high", "medium", "low"}
LOCATOR_TYPES = {"line", "transcript_segment", "char_span"}

MAX_FACTS = 200
MAX_REQUIREMENTS = 50
MAX_ACCEPTANCE_ITEMS = 20
OBJECT_VALUE_MAX_BYTES = 4096


class DiscoveryContractError(ValueError):
    def __init__(self, code: str, path: str, message: str):
        super().__init__(message)
        self.code, self.path, self.message = code, path, message


def _check_locator(raw: object, path: str) -> dict[str, Any]:
    if not isinstance(raw, dict) or raw.get("type") not in LOCATOR_TYPES:
        raise DiscoveryContractError("invalid_locator", path, "来源定位格式不正确。")
    locator = dict(raw)
    kind = locator["type"]
    if kind == "line":
        line = locator.get("line")
        if not _is_line(line):
            raise DiscoveryContractError("invalid_locator", path, "行号定位必须是 ≥1 的整数。")
    elif kind == "transcript_segment":
        start_ms, end_ms = locator.get("start_ms"), locator.get("end_ms")
        if not _is_ms(start_ms) or not _is_ms(end_ms) or end_ms < start_ms:
            raise DiscoveryContractError("invalid_locator", path, "时间段定位必须是 0 起且 end≥start 的毫秒值。")
    else:  # char_span
        start, end = locator.get("start"), locator.get("end")
        if not _is_ms(start) or not _is_ms(end) or end <= start:
            raise DiscoveryContractError("invalid_locator", path, "字符区间必须是 start≥0 且 end>start。")
    # TypeGuard 收窄保证以上比较的操作数均为 int（mypy 双检）
    return locator


def _is_ms(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_line(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _bounded_text(raw: object, path: str, limit: int, *, field: str) -> str:
    if not isinstance(raw, str) or not raw.strip() or len(raw) > limit:
        raise DiscoveryContractError("invalid_text", path, f"{field} 为空或超过 {limit} 字。")
    return raw.strip()


def _object_size_ok(value: object) -> bool:
    import json

    try:
        return len(json.dumps(value, ensure_ascii=False, default=str)) <= OBJECT_VALUE_MAX_BYTES
    except (TypeError, ValueError):
        return False


def validate_extraction_output(value: object) -> dict[str, Any]:
    """校验 AI 抽取输出；任一违规整批拒绝（不部分写入）。"""
    if not isinstance(value, dict) or set(value) != {"facts", "requirements"}:
        raise DiscoveryContractError("invalid_extraction", "", "AI 返回的抽取结果字段不完整。")
    raw_facts, raw_requirements = value["facts"], value["requirements"]
    if not isinstance(raw_facts, list) or len(raw_facts) > MAX_FACTS:
        raise DiscoveryContractError("invalid_facts", "facts", f"事实条目格式不正确（至多 {MAX_FACTS} 条）。")
    if not isinstance(raw_requirements, list) or len(raw_requirements) > MAX_REQUIREMENTS:
        raise DiscoveryContractError("invalid_requirements", "requirements", f"需求条目格式不正确（至多 {MAX_REQUIREMENTS} 条）。")

    facts: list[dict[str, Any]] = []
    seen_identities: set[tuple[str, str, str]] = set()
    for index, raw in enumerate(raw_facts):
        path = f"facts[{index}]"
        base_keys = {"fact_type", "subject", "predicate", "object_value", "source_locator"}
        allowed_keys = base_keys | {"confidence", "inference", "needs_clarification"}
        if not isinstance(raw, dict) or not base_keys <= set(raw) <= allowed_keys:
            raise DiscoveryContractError("invalid_fact", path, "事实条目格式不正确。")
        fact_type = raw["fact_type"]
        if fact_type not in FACT_TYPES:
            raise DiscoveryContractError("invalid_fact_type", path, "事实类型不在十值闭集内。")
        subject = _bounded_text(raw["subject"], f"{path}.subject", 200, field="subject")
        predicate = _bounded_text(raw["predicate"], f"{path}.predicate", 200, field="predicate")
        object_value = raw["object_value"]
        if not _object_size_ok(object_value):
            raise DiscoveryContractError("invalid_object_value", f"{path}.object_value", "事实取值缺失或超过 4KB。")
        locator = _check_locator(raw["source_locator"], f"{path}.source_locator")
        confidence = raw.get("confidence")
        if confidence is not None and (not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= float(confidence) <= 1):
            raise DiscoveryContractError("invalid_confidence", f"{path}.confidence", "置信度必须是 0–1 的数值。")
        inference = _flag(raw.get("inference"), f"{path}.inference")
        needs_clarification = _flag(raw.get("needs_clarification"), f"{path}.needs_clarification")
        identity = (fact_type, subject, predicate)
        if identity in seen_identities:
            raise DiscoveryContractError("duplicate_fact", path, "同一批次内事实重复（类型+主体+谓词）。")
        seen_identities.add(identity)
        facts.append({
            "fact_type": fact_type,
            "subject": subject,
            "predicate": predicate,
            "object_value": object_value,
            "confidence": None if confidence is None else round(float(confidence), 2),
            "source_locator": locator,
            "inference": inference,
            "needs_clarification": needs_clarification,
        })

    requirements: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_requirements):
        path = f"requirements[{index}]"
        base_keys = {"title", "requirement_type", "acceptance_criteria"}
        allowed_keys = base_keys | {"description", "priority", "source_fact_indexes"}
        if not isinstance(raw, dict) or not base_keys <= set(raw) <= allowed_keys:
            raise DiscoveryContractError("invalid_requirement", path, "需求条目格式不正确。")
        title = _bounded_text(raw["title"], f"{path}.title", 200, field="title")
        requirement_type = raw["requirement_type"]
        if requirement_type not in REQUIREMENT_TYPES:
            raise DiscoveryContractError("invalid_requirement_type", path, "需求类型不在六值闭集内。")
        priority = raw.get("priority", "medium")
        if priority not in PRIORITIES:
            raise DiscoveryContractError("invalid_priority", path, "优先级仅可为 high/medium/low。")
        description = raw.get("description")
        if description is not None:
            description = _bounded_text(description, f"{path}.description", 8000, field="description")
        criteria = raw["acceptance_criteria"]
        if not isinstance(criteria, list) or not criteria or len(criteria) > MAX_ACCEPTANCE_ITEMS:
            raise DiscoveryContractError("invalid_acceptance", f"{path}.acceptance_criteria", "验收标准必须为 1–20 条。")
        criteria = [_bounded_text(item, f"{path}.acceptance_criteria[{i}]", 500, field="验收标准") for i, item in enumerate(criteria)]
        indexes = raw.get("source_fact_indexes", [])
        if not isinstance(indexes, list) or any(not isinstance(i, int) or isinstance(i, bool) for i in indexes):
            raise DiscoveryContractError("invalid_source_fact_indexes", f"{path}.source_fact_indexes", "来源事实索引格式不正确。")
        if len(set(indexes)) != len(indexes):
            raise DiscoveryContractError("duplicate_source_fact", path, "来源事实索引重复。")
        for i in indexes:
            if i < 0 or i >= len(facts):
                raise DiscoveryContractError("unknown_source_fact", f"{path}.source_fact_indexes", "引用了不存在的事实条目。")
        requirements.append({
            "title": title,
            "description": description,
            "requirement_type": requirement_type,
            "priority": priority,
            "acceptance_criteria": criteria,
            "source_fact_indexes": indexes,
        })

    return {"facts": facts, "requirements": requirements}


def _flag(raw: object, path: str) -> bool:
    if raw is None:
        return False
    if not isinstance(raw, bool):
        raise DiscoveryContractError("invalid_flag", path, "布尔标记格式不正确。")
    return raw
