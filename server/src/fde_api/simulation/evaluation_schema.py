"""模型评估输出的严格契约（V3.2 G9 接线轮）。

沿用仓库既有范式（``ai/industry_template_schema.py``）：**键集闭合**、**条数上限**、
**枚举封闭**、**证据强制**——模型输出不合规即整条丢弃（不「尽力修复」，
避免把模型的胡话当成评分）。

**纪律**：本层**只**产出模型的分项评分与证据引用；终局结论与硬性失败由
L-A 规则层判定。模型即便在输出里写「hard_fail」也不作数。
"""
from __future__ import annotations

from typing import Any

# 顶层键集（闭合）
TOP_LEVEL_KEYS = {"criteria", "summary"}
# 单条判据键集（闭合）
CRITERION_KEYS = {"key", "dimension", "title", "score", "verdict", "evidence_refs", "reason"}
# 证据条目键集（闭合）
EVIDENCE_KEYS = {"kind", "text"}
# 分项结论枚举
CRITERION_VERDICTS = ("pass", "partial", "fail")
# 判据条数上限（防模型灌水）
MAX_CRITERIA = 24
# 证据条数上限（单条判据）
MAX_EVIDENCE_PER_CRITERION = 8
# 证据正文最大长度（引用原文，不接受整篇搬运）
MAX_EVIDENCE_CHARS = 600
# 维度键白名单
DIMENSIONS = ("D1", "D2", "D3", "D4", "D5", "D6", "D7")


class EvaluationContractError(ValueError):
    """模型输出不合契约。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _is_str_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def parse_model_evaluation(raw: Any) -> dict[str, Any]:
    """校验并归一模型输出。

    返回 ``{"criteria": [...], "summary": str}``；不合契约抛
    ``EvaluationContractError``。
    """
    if not isinstance(raw, dict):
        raise EvaluationContractError("not_object", "模型输出必须是对象。")
    keys = set(raw)
    unknown = keys - TOP_LEVEL_KEYS
    if unknown:
        raise EvaluationContractError(
            "unknown_keys", f"模型输出含未知顶层键：{sorted(unknown)}"
        )
    missing = TOP_LEVEL_KEYS - keys
    if missing:
        raise EvaluationContractError(
            "missing_keys", f"模型输出缺顶层键：{sorted(missing)}"
        )
    criteria = raw.get("criteria")
    if not isinstance(criteria, list):
        raise EvaluationContractError("invalid_criteria", "criteria 必须是数组。")
    if len(criteria) > MAX_CRITERIA:
        raise EvaluationContractError(
            "too_many_criteria", f"判据条数超过上限 {MAX_CRITERIA}。"
        )
    summary = raw.get("summary")
    if not isinstance(summary, str):
        raise EvaluationContractError("invalid_summary", "summary 必须是字符串。")

    normalized: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for item in criteria:
        if not isinstance(item, dict):
            raise EvaluationContractError("invalid_criterion", "criteria 元素必须是对象。")
        item_keys = set(item)
        if item_keys - CRITERION_KEYS:
            raise EvaluationContractError(
                "unknown_criterion_keys",
                f"判据含未知键：{sorted(item_keys - CRITERION_KEYS)}",
            )
        if CRITERION_KEYS - item_keys:
            raise EvaluationContractError(
                "missing_criterion_keys",
                f"判据缺键：{sorted(CRITERION_KEYS - item_keys)}",
            )
        key = item["key"]
        if not isinstance(key, str) or not key.strip():
            raise EvaluationContractError("invalid_criterion_key", "判据 key 必须是非空字符串。")
        if key in seen_keys:
            raise EvaluationContractError("duplicate_criterion_key", f"判据 key 重复：{key}")
        seen_keys.add(key)
        dimension = item["dimension"]
        if dimension not in DIMENSIONS:
            raise EvaluationContractError(
                "invalid_dimension", f"dimension 取值非法：{dimension}"
            )
        title = item["title"]
        if not isinstance(title, str) or not title.strip():
            raise EvaluationContractError("invalid_criterion_title", "title 必须是非空字符串。")
        score = item["score"]
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise EvaluationContractError("invalid_score", "score 必须是数字。")
        if not 0.0 <= float(score) <= 1.0:
            raise EvaluationContractError("invalid_score", "score 必须在 0–1 之间。")
        verdict = item["verdict"]
        if verdict not in CRITERION_VERDICTS:
            raise EvaluationContractError("invalid_verdict", f"verdict 取值非法：{verdict}")
        reason = item["reason"]
        if not isinstance(reason, str):
            raise EvaluationContractError("invalid_reason", "reason 必须是字符串。")
        evidence = item["evidence_refs"]
        if not isinstance(evidence, list) or not evidence:
            # 无证据的评分一律丢弃（宁缺毋滥）——不是整份输出作废。
            continue
        if len(evidence) > MAX_EVIDENCE_PER_CRITERION:
            raise EvaluationContractError(
                "too_many_evidence", f"单条判据证据超过上限 {MAX_EVIDENCE_PER_CRITERION}。"
            )
        normalized_evidence: list[dict[str, Any]] = []
        for ref in evidence:
            if not isinstance(ref, dict):
                raise EvaluationContractError("invalid_evidence", "证据条目必须是对象。")
            ref_keys = set(ref)
            if ref_keys - EVIDENCE_KEYS:
                raise EvaluationContractError(
                    "unknown_evidence_keys",
                    f"证据含未知键：{sorted(ref_keys - EVIDENCE_KEYS)}",
                )
            if EVIDENCE_KEYS - ref_keys:
                raise EvaluationContractError(
                    "missing_evidence_keys",
                    f"证据缺键：{sorted(EVIDENCE_KEYS - ref_keys)}",
                )
            text = ref["text"]
            if not isinstance(text, str) or not text.strip():
                raise EvaluationContractError("invalid_evidence_text", "证据正文必须非空。")
            kind = ref["kind"]
            if not isinstance(kind, str) or not kind.strip():
                raise EvaluationContractError("invalid_evidence_kind", "证据 kind 必须非空。")
            normalized_evidence.append(
                {"kind": kind.strip(), "text": text.strip()[:MAX_EVIDENCE_CHARS]}
            )
        normalized.append(
            {
                "key": key.strip(),
                "dimension": dimension,
                "title": title.strip(),
                "score": round(float(score), 4),
                "verdict": verdict,
                "evidence_refs": normalized_evidence,
                "reason": reason.strip(),
            }
        )

    if not normalized:
        raise EvaluationContractError(
            "no_evidence_backed_criteria", "模型输出没有任何带证据的判据。"
        )
    return {"criteria": normalized, "summary": summary.strip()}
