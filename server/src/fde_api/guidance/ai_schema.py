from __future__ import annotations

from typing import Any, Literal, TypedDict, cast


CLASSIFICATIONS = {"customer_stated", "ai_synthesized", "ai_inferred", "open_question", "human_added"}
LIST_FIELDS = (
    "key_business_problems", "priority_departments", "priority_roles", "priority_processes",
    "success_criteria", "out_of_scope", "data_security_redlines",
    "systems_and_deployment_constraints", "assumptions", "open_questions", "next_actions",
)


class GuidanceItem(TypedDict):
    text: str
    classification: Literal["customer_stated", "ai_synthesized", "ai_inferred", "open_question", "human_added"]
    source_refs: list[str]
    confirmed: bool


class GuidanceDraft(TypedDict):
    customer_vision: str
    current_phase_objective: str
    executive_summary: str
    evidence: dict[str, str]


class GuidanceContractError(ValueError):
    def __init__(self, code: str, path: str, message: str):
        super().__init__(message)
        self.code, self.path, self.message = code, path, message


def validate_guidance_output(value: object, *, source_refs: set[str]) -> dict[str, Any]:
    required = {"customer_vision", "current_phase_objective", "executive_summary", "evidence", *LIST_FIELDS}
    if not isinstance(value, dict) or set(value) != required:
        raise GuidanceContractError("invalid_guidance", "", "AI 返回的项目指引字段不完整。")
    result: dict[str, Any] = {}
    for field in ("customer_vision", "current_phase_objective", "executive_summary"):
        text = value.get(field)
        if not isinstance(text, str) or not text.strip() or len(text) > 10_000:
            raise GuidanceContractError("invalid_text", field, f"{field} 内容为空或过长。")
        result[field] = text.strip()
    evidence = value.get("evidence")
    if not isinstance(evidence, dict) or any(ref not in source_refs for ref in evidence):
        raise GuidanceContractError("unknown_source_ref", "evidence", "引用了不存在的原文位置。")
    result["evidence"] = {str(k): str(v)[:1000] for k, v in evidence.items()}
    for field in LIST_FIELDS:
        raw_items = value.get(field)
        if not isinstance(raw_items, list) or len(raw_items) > 100:
            raise GuidanceContractError("invalid_items", field, f"{field} 格式不正确。")
        items: list[GuidanceItem] = []
        for index, raw in enumerate(raw_items):
            path = f"{field}[{index}]"
            if not isinstance(raw, dict) or set(raw) != {"text", "classification", "source_refs", "confirmed"}:
                raise GuidanceContractError("invalid_item", path, "项目指引条目格式不正确。")
            text, classification, refs, confirmed = raw["text"], raw["classification"], raw["source_refs"], raw["confirmed"]
            if not isinstance(text, str) or not text.strip() or len(text) > 2000:
                raise GuidanceContractError("invalid_text", f"{path}.text", "条目内容为空或过长。")
            if classification not in CLASSIFICATIONS or type(confirmed) is not bool:
                raise GuidanceContractError("invalid_classification", path, "条目分类或确认状态无效。")
            if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
                raise GuidanceContractError("invalid_source_ref", path, "原文引用格式不正确。")
            if any(ref not in source_refs for ref in refs):
                raise GuidanceContractError("unknown_source_ref", path, "引用了不存在的原文位置。")
            if classification not in {"open_question", "human_added"} and not refs:
                raise GuidanceContractError("missing_source_ref", path, "事实和 AI 判断必须引用原文。")
            items.append(cast(GuidanceItem, {"text": text.strip(), "classification": classification, "source_refs": refs, "confirmed": confirmed}))
        result[field] = items
    return result
