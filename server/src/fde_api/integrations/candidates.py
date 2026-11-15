"""discovery 事实 → 本体候选（六件套强制）+ 逐字引文还原（WP4④ / D17）。

纪律（红线 11 + §13 验收 3/4）：
- 只接受**人工审阅定案**的事实（``review_status == "accepted"``）——未审阅事实直提本体
  ＝绕过人工审批面；
- ``evidence_quote`` 必须**逐字原文**：由 ``source_ref`` 定位源 + ``source_locator``
  切片还原；``transcript_segment`` 非文本定位无法还原引文 ⇒ 该事实不可直提
  （跳过并计数，**严禁用生成文本冒充原文引用**）；
- 冲突**跨抽取**判定（同 ``fact_type``+``subject``+``predicate`` 的不同取值——同一抽取内
  ``uq_business_facts_batch_identity`` 保证三元组唯一，不可能自相矛盾）；
- 未知项（``open_question`` / ``ai_inferred`` 事实）随候选贯通 ``unresolved_questions``；
- 严格对齐 ``ontology-service`` M2 ``validation.py`` 契约：
  * ``KEY_RE = [a-z0-9][a-z0-9_-]{0,79}``（分隔符用 ``_``/``-``，严禁含 ``.``）；
  * ``ObjectTypePayload`` 为 ``ConfigDict(extra="forbid")``，M2 工作集仅实装
    ``object_types`` / ``property_definitions`` / ``relation_types``（``property_definitions``
    与 ``relation_types`` 必填对象外键 ID，单条抽取事实无宿主对象时不可空悬生成；
    ``role``/``system``/``data_object``/``process`` 直映 ``object_types``，其余类型显式记入
    ``skipped`` 且 ``reason="fact_type_not_mapped_to_entity"``，绝不送出必然 422 的残缺条目）；
  * 同 change-set 内同一 ``display_name`` 多条事实追加编号后缀，避免撞 ``term_conflict``。

候选条目形状（冻结契约 ``ontology-api-spec.yaml`` §6.2/§6.3）：``proposed_json`` 元素 =
``{op, entity_type, entity_key, payload}``；``captured_from`` 非空的条目，``payload`` 必含
CandidatePayload 六件套（``source_location``/``evidence_quote``/``confidence``/
``fact_or_inference``），可选 ``conflicts``/``suggested_owner``/``unresolved_questions``。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

# fact_type → 本体工作集实体（M2 已实装且可由独立事实直接构建的对象类型，D17）
FACT_ENTITY_TYPES: dict[str, str] = {
    "role": "object_types",
    "system": "object_types",
    "data_object": "object_types",
    "process": "object_types",
}

# 实体 → 建议审批角色（冻结契约 §5：business_owner / data_owner）
ENTITY_SUGGESTED_OWNER: dict[str, str] = {
    "object_types": "business_owner",
}

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    """实体键用的稳定 slug（ASCII 化；非 ASCII 主体用内容指纹，避免中文主体键碰撞）。"""
    slug = _SLUG_RE.sub("-", value.strip().lower()).strip("-")
    if slug:
        return slug[:56]
    return "f" + hashlib.sha256(value.strip().encode("utf-8")).hexdigest()[:10]


@dataclass
class CandidateBuild:
    """一次候选构建的结果（条目 + 跳过清单 + 未知项）。"""

    items: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    unresolved_questions: list[str] = field(default_factory=list)


def _render_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _quote_from_locator(content: str, locator: Any) -> str | None:
    """按 locator 从原文切出逐字引文；无法还原 ⇒ None（该事实不可直提）。"""
    if not isinstance(locator, dict):
        return None
    kind = locator.get("type")
    if kind == "line":
        line = locator.get("line")
        if not isinstance(line, int) or isinstance(line, bool) or line < 1:
            return None
        lines = content.splitlines()
        if line > len(lines):
            return None
        return lines[line - 1].strip() or None
    if kind == "char_span":
        start = locator.get("start")
        end = locator.get("end")
        if (
            not isinstance(start, int)
            or isinstance(start, bool)
            or not isinstance(end, int)
            or isinstance(end, bool)
            or end <= start
        ):
            return None
        if start < 0 or end > len(content):
            return None
        return content[start:end].strip() or None
    # transcript_segment：毫秒区间，无文本定位 ⇒ 不还原引文（严禁生成文本冒充原文引用）
    return None


def _source_pointer(source_ref: str, locator: Any) -> str:
    """来源定位指针（只存指针+指纹，不存客户原文——I7）。"""
    if isinstance(locator, dict):
        tail = "&".join(f"{key}={value}" for key, value in sorted(locator.items()))
        return f"{source_ref}#{tail}" if tail else source_ref
    return source_ref


def build_candidates(
    *, facts: list[Any], source_texts: dict[str, str]
) -> CandidateBuild:
    """把 discovery 事实构建成本体候选条目。

    ``facts``：BusinessFact ORM 列表（同一项目，含已审阅与未审阅）。
    ``source_texts``：``source_ref`` → 原文正文（InterviewMinutes/TranscriptDraft.content）。
    """
    build = CandidateBuild()

    accepted = [fact for fact in facts if getattr(fact, "review_status", None) == "accepted"]
    accepted_ids = {id(fact) for fact in accepted}
    for fact in facts:
        if id(fact) not in accepted_ids:
            build.skipped.append(
                {
                    "fact_id": getattr(fact, "id", None),
                    "reason": "not_accepted",
                    "classification": getattr(fact, "classification", None),
                }
            )

    # 未知项：open_question / ai_inferred 事实（任意审阅态）——禁 LLM 补造业务事实（S-20）
    questions: list[str] = []
    for fact in facts:
        classification = getattr(fact, "classification", None)
        if classification in {"open_question", "ai_inferred"}:
            subject = _render_value(getattr(fact, "subject", ""))
            predicate = _render_value(getattr(fact, "predicate", ""))
            questions.append(f"{subject}｜{predicate}".strip("｜"))
    build.unresolved_questions = sorted(set(q for q in questions if q))

    # 冲突：同 (fact_type, subject, predicate) 的不同取值（跨抽取）
    grouped: dict[tuple[str, str, str], list[Any]] = {}
    for fact in accepted:
        group_key = (
            _render_value(getattr(fact, "fact_type", "")),
            _render_value(getattr(fact, "subject", "")),
            _render_value(getattr(fact, "predicate", "")),
        )
        grouped.setdefault(group_key, []).append(fact)

    used_keys: set[str] = set()
    used_names: set[str] = set()
    for fact in accepted:
        fact_type = _render_value(getattr(fact, "fact_type", ""))
        subject = _render_value(getattr(fact, "subject", "")).strip()
        predicate = _render_value(getattr(fact, "predicate", "")).strip()
        value = getattr(fact, "object_value", None)

        entity_type = FACT_ENTITY_TYPES.get(fact_type)
        if entity_type is None:
            build.skipped.append(
                {
                    "fact_id": getattr(fact, "id", None),
                    "reason": "fact_type_not_mapped_to_entity",
                    "fact_type": fact_type,
                }
            )
            continue

        if not subject:
            build.skipped.append(
                {
                    "fact_id": getattr(fact, "id", None),
                    "reason": "empty_subject",
                }
            )
            continue

        source_ref = _render_value(getattr(fact, "source_ref", ""))
        content = source_texts.get(source_ref)
        if content is None:
            build.skipped.append(
                {
                    "fact_id": getattr(fact, "id", None),
                    "reason": "source_content_unavailable",
                    "source_ref": source_ref,
                }
            )
            continue

        quote = _quote_from_locator(content, getattr(fact, "source_locator", None))
        if not quote:
            build.skipped.append(
                {
                    "fact_id": getattr(fact, "id", None),
                    "reason": "evidence_quote_not_restorable",
                    "source_ref": source_ref,
                }
            )
            continue

        # KEY_RE = [a-z0-9][a-z0-9_-]{0,79}（严禁用 '.'）
        base_key = f"{slugify(fact_type)}_{slugify(subject)}"[:72]
        key = base_key
        suffix = 1
        while key in used_keys:
            suffix += 1
            key = f"{base_key}-{suffix}"[:80]
        used_keys.add(key)

        # ObjectTypePayload.display_name 在同 change-set 内须唯一（避撞 term_conflict）
        base_name = subject[:150]
        display_name = base_name
        name_suffix = 1
        while display_name in used_names:
            name_suffix += 1
            display_name = f"{base_name}-{name_suffix}"[:160]
        used_names.add(display_name)

        conflicts: list[str] = []
        for sibling in grouped.get((fact_type, subject, predicate), []):
            if sibling is fact:
                continue
            other = _render_value(getattr(sibling, "object_value", None))
            if other != _render_value(value):
                conflicts.append(f"其他抽取取值：{other}")
        conflicts = sorted(set(conflicts))

        fact_or_inf = (
            "inference"
            if getattr(fact, "classification", None) in {"ai_inferred", "ai_synthesized"}
            else "fact"
        )
        confidence = getattr(fact, "confidence", None)
        confidence_value = float(confidence) if confidence is not None else 0.5
        confidence_value = max(0.0, min(1.0, confidence_value))

        # 注意：ObjectTypePayload 设为 ConfigDict(extra="forbid")，不含 "status" 字段
        payload: dict[str, Any] = {
            "display_name": display_name,
            "description": f"{predicate}：{_render_value(value)}".strip("："),
            "source_location": _source_pointer(
                source_ref, getattr(fact, "source_locator", None)
            ),
            "evidence_quote": quote,
            "confidence": confidence_value,
            "fact_or_inference": fact_or_inf,
            "suggested_owner": ENTITY_SUGGESTED_OWNER[entity_type],
        }
        if conflicts:
            payload["conflicts"] = conflicts
        if build.unresolved_questions:
            payload["unresolved_questions"] = list(build.unresolved_questions)

        build.items.append(
            {
                "op": "create",
                "entity_type": entity_type,
                "entity_key": key,
                "payload": payload,
            }
        )

    return build
