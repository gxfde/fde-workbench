"""plans AI 起草管线（AI 原生化 N3b 本体轮，G-04 消解）。

把「AI 起草 → 人工审核 → 发布」两段式推进到 delivery plan 域（任务书 §15 序 3，
沿 N3a quality/draft.py 先例全量复用机制，零新发明）：

- **单一入口**（N2 纪律）：AI 调用走 ``execute_ai_prompt``（预算门＋审计＋
  提示词指纹/版本归因＋降级直连全在册，本模块不自造通道）；
- **契约失败整批零写入**（fail-closed 家族一致）：输出契约校验
  （``validate_plan_draft``）任一违规整批拒绝——概率性畸形输出即时重试一次
  （discovery/N3a 同裁），仍失败即 409；**DB 写入是全管线最后一步且在同一
  事务内**，此前零业务写入，失败路径零残留；
- **AI 是可选起草腿，不推翻确定性拼装**（任务书 N3b 范围）：``generate_plan``
  确定性生成器零改动＝缺省腿；本模块产出**同形状**的 draft 方案（版本行递增、
  历史不覆盖），发布语义仍由 ``review_plan``（approved 闸＋审核戳）→
  ``publish_plan`` 既有闸机械承载——「仅经 approved 闸发布」由既有闸钉死，
  AI 无任何旁路；
- **输入侧对齐确定性生成器同域**：已批准需求（每条 ≥1 条目引用＝覆盖先验）＋
  已接受事实＋待澄清事实（风险素材）＋confirmed 术语；requirement_key/
  fact_id 闭集＝项目在册值，AI 不得虚构（越界键整批拒绝）；
- **输出端兜底脱敏**（证据红线同族，克隆 discovery/N3a 第③层）：条目标题/
  详情字符串过 ``redact_text_detailed``——词典机制故障 fail-closed（不落库）、
  凭据串命中整批拒绝；替换留痕进 ``delivery_plan_redaction_review`` 事件；
- **溯源**（N2 纪律）：``prompt_version`` 经单一入口进审计账本，事件
  留痕带版本＋模型名——AI 起草可归因。

输入侧纪律：用户提示词只由已代号化的需求库/事实库/术语库数据拼装，无外部
文字进模型（外部文字禁入契约 P-4 同尺）。
"""
from __future__ import annotations

import json
import time
from typing import Any
from uuid import uuid4

from sqlalchemy import select

from fde_api.ai.prompt_registry import version_of

from fde_api.control.ai_server_client import DSHRuntimeError, execute_ai_prompt
from fde_api.extensions import db
from fde_api.guidance.enterprise_dict import DICT_FAILURE_CODE, RedactionConfigError
from fde_api.guidance.redaction import (
    SensitiveCredentialDetected,
    fingerprint_review_payload,
    redact_text_detailed,
)
from fde_api.plans.models import ITEM_TYPES, DeliveryPlan, DeliveryPlanItem
from fde_api.plans.service import PlansServiceError, _next_version, _require_project, serialize_plan
from fde_api.workbench.models import OperationEvent

__all__ = [
    "DELIVERY_PLAN_DRAFT_SYSTEM_PROMPT",
    "MAX_AI_ITEMS",
    "PLAN_DRAFT_PROMPT_VERSION",
    "PLAN_DRAFT_PURPOSE",
    "PlanDraftContractError",
    "build_plan_draft_user_prompt",
    "draft_ai_delivery_plan",
    "validate_plan_draft",
]

# 提示词版本（N2 归因纪律：审计账本按版本归因；提示词正文改动必须升版本）。
# N6/G-13：标签唯一权威＝ai/prompt_registry.py（正文改动必同步注册表升版本）。
PLAN_DRAFT_PROMPT_VERSION = version_of("fde_api.plans.draft_ai", "DELIVERY_PLAN_DRAFT_SYSTEM_PROMPT")
# 审计 purpose（ai_call_audits NOT NULL CHECK；≤60 字自由文本域）。
PLAN_DRAFT_PURPOSE = "delivery_plan_draft"

# 单批条目上限（全量方案 MAX_ITEMS=100 的一半；供应商输出预算下的保守配额——
# 宁缺毋滥，同 discovery/N3a 纪律）。
MAX_AI_ITEMS = 50
# 条目字段上限（对齐 delivery_plan_items 列形状：title 200；detail 保守 2000）。
_TITLE_MAX = 200
_DETAIL_MAX = 2000
_PRIORITIES = {"high", "medium", "low"}
# 引用清单上限（requirement_keys/fact_ids 数组——与确定性腿同量级的保守界）。
_MAX_REFS = 50

# 瞬时错误退避重试（discovery/N3a 同裁；同步路由面单次退避）。
_TRANSIENT_RETRY_CODES = frozenset({"ai_rate_limited", "ai_timeout", "ai_service_unavailable", "ai_unavailable"})
_RETRY_BACKOFF_SECONDS = 1.0
# 契约/JSON 失败即时重试上限（概率性畸形输出——discovery CONTRACT_RETRY_LIMIT 同值）。
_CONTRACT_RETRY_LIMIT = 1

DELIVERY_PLAN_DRAFT_SYSTEM_PROMPT = f"""你是制造业交付项目的交付方案起草器。输入是本项目当前已批准需求、\
已接受事实、待澄清事实与 confirmed 领域术语（结构化清单，已代号化），你只做忠实起草，不得虚构输入。

输出一个 JSON 对象，恰好包含一个键 items。

items 是数组（1–{MAX_AI_ITEMS} 条），每项恰好包含基础键：
- item_type：{ITEM_TYPES[0]}/{ITEM_TYPES[1]}/{ITEM_TYPES[2]}/{ITEM_TYPES[3]}/{ITEM_TYPES[4]}/{ITEM_TYPES[5]}（六值闭集）；
- title：条目标题（≤{_TITLE_MAX} 字）；
可选键：
- detail：条目详情（≤{_DETAIL_MAX} 字，可为空；requirement 条目建议写清实施口径）；
- priority：high|medium|low（默认 medium）；
- requirement_keys：字符串数组（每项必须逐字取自输入清单中的 requirement_key，不得虚构、不得改写）；
- fact_ids：字符串数组（每项必须逐字取自输入清单中的 fact id，不得虚构）。

硬性纪律：
1. 输入清单中的**每一条 requirement_key 至少被一个条目的 requirement_keys 引用**
（人工审核会复查，缺条即整批被拒）；requirement 类条目必须引用 ≥1 个 requirement_key；
2. 不得引用清单之外的键或 id；待澄清事实建议作为 risk 条目的 fact_ids 素材；
3. 只输出 JSON，不要输出任何其他文字；正文不得包含凭据（密码/密钥/令牌）。"""


class PlanDraftContractError(ValueError):
    """AI 起草输出契约违规（任一违规整批拒绝，不部分写入）。"""

    def __init__(self, code: str, path: str, message: str):
        super().__init__(message)
        self.code, self.path, self.message = code, path, message


def _bounded_text(raw: object, path: str, limit: int, *, field: str, allow_empty: bool = False) -> str | None:
    if raw is None:
        if allow_empty:
            return None
        raise PlanDraftContractError("invalid_text", path, f"{field} 缺失。")
    if not isinstance(raw, str) or len(raw) > limit or (not raw.strip() and not allow_empty):
        raise PlanDraftContractError("invalid_text", path, f"{field} 为空、超长或格式不正确（≤{limit} 字）。")
    return raw.strip() or None


def _bounded_refs(raw: object, path: str, *, field: str, valid: set[str], code: str) -> list[str]:
    """引用清单归一：字符串数组、闭集校验、去重保序（首现）。"""
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > _MAX_REFS or not all(isinstance(item, str) for item in raw):
        raise PlanDraftContractError("invalid_refs", path, f"{field} 须为字符串数组（≤{_MAX_REFS} 项）。")
    seen: list[str] = []
    for position, item in enumerate(raw):
        if item not in valid:
            raise PlanDraftContractError(
                code, f"{path}[{position}]",
                f"{field} 引用了清单之外的值：{item}（不得虚构）。",
            )
        if item not in seen:
            seen.append(item)
    return seen


def build_plan_draft_user_prompt(
    requirements: list[dict[str, Any]],
    facts: list[dict[str, Any]],
    open_facts: list[dict[str, Any]],
    terms: list[str],
) -> str:
    """拼装 AI 起草的用户提示词（确定性：需求按 key 字典序、事实按 (subject,predicate,id) 序）。

    输入面=已代号化的需求库/事实库/术语库数据——零外部文字进模型。
    """
    lines = ["【已批准需求清单】（requirement_key 必须逐字引用）", ""]
    for index, row in enumerate(sorted(requirements, key=lambda item: item["requirement_key"]), start=1):
        criteria = "；".join(row["acceptance_criteria"] or [])[:1500] or "（未附验收标准，按标题起草）"
        lines.append(
            f"{index}. key={row['requirement_key']}｜标题={str(row['title'])[:_TITLE_MAX]}"
            f"｜优先级={row['priority']}｜验收标准={criteria}"
        )
    lines += ["", "【已接受事实】（fact id 必须逐字引用）", ""]
    for row in sorted(facts, key=lambda item: (item["subject"], item["predicate"], item["id"])):
        lines.append(
            f"- id={row['id']}｜{str(row['subject'])[:120]}·{str(row['predicate'])[:120]}"
            f"·{str(row['object_value'])[:200]}"
        )
    if not facts:
        lines.append("（无）")
    if open_facts:
        lines += ["", "【待澄清事实】（建议作为 risk 条目的 fact_ids 素材）", ""]
        for row in sorted(open_facts, key=lambda item: (item["subject"], item["predicate"], item["id"])):
            lines.append(
                f"- id={row['id']}｜{str(row['subject'])[:120]}·{str(row['predicate'])[:120]}"
                f"·{str(row['object_value'])[:200]}"
            )
    if terms:
        lines += ["", f"【confirmed 领域术语】（方案范围快照）：{'、'.join(sorted(terms))[:1500]}"]
    lines += [
        "",
        "【任务】为以上输入起草交付方案条目（每条需求 key 至少被一个条目引用；"
        "待澄清事实建议聚合为 risk 条目），按系统指令输出的 JSON 契约返回。",
    ]
    return "\n".join(lines)


def validate_plan_draft(
    payload: object, accepted_keys: set[str], valid_fact_ids: set[str]
) -> list[dict[str, Any]]:
    """校验 AI 起草输出；任一违规整批拒绝（不部分写入）。

    归一化产出：条目保持模型给出顺序（同 payload 恒同归一结果——确定性），
    requirement_keys/fact_ids 去重保序。覆盖完整性（每条 accepted 需求 ≥1 条
    条目引用）在此先验——缺项整批拒绝（第二道=审阅闸既有需求覆盖语义同族）。
    """
    if not isinstance(payload, dict) or set(payload) != {"items"}:
        raise PlanDraftContractError("invalid_draft", "", "AI 返回的起草结果字段不完整（须为 {items}）。")
    raw_items = payload["items"]
    if not isinstance(raw_items, list) or not raw_items or len(raw_items) > MAX_AI_ITEMS:
        raise PlanDraftContractError(
            "invalid_items", "items", f"条目数组格式不正确（1–{MAX_AI_ITEMS} 条）。"
        )
    base_keys = {"item_type", "title"}
    allowed_keys = base_keys | {"detail", "priority", "requirement_keys", "fact_ids"}
    normalized: list[dict[str, Any]] = []
    covered: set[str] = set()
    for index, raw in enumerate(raw_items):
        path = f"items[{index}]"
        if not isinstance(raw, dict) or not base_keys <= set(raw) <= allowed_keys:
            raise PlanDraftContractError("invalid_item", path, "条目格式不正确。")
        item_type = raw["item_type"]
        if item_type not in ITEM_TYPES:
            raise PlanDraftContractError(
                "invalid_item_type", f"{path}.item_type",
                f"item_type 须为 {'/'.join(ITEM_TYPES)}。",
            )
        title = _bounded_text(raw["title"], f"{path}.title", _TITLE_MAX, field="title")
        detail = _bounded_text(raw.get("detail"), f"{path}.detail", _DETAIL_MAX, field="detail", allow_empty=True)
        priority = raw.get("priority", "medium")
        if priority not in _PRIORITIES:
            raise PlanDraftContractError("invalid_priority", f"{path}.priority", "priority 须为 high/medium/low。")
        requirement_keys = _bounded_refs(
            raw.get("requirement_keys"), f"{path}.requirement_keys",
            field="requirement_keys", valid=accepted_keys, code="unknown_requirement_key",
        )
        if item_type == "requirement" and not requirement_keys:
            raise PlanDraftContractError(
                "requirement_key_required", f"{path}.requirement_keys",
                "requirement 条目必须引用 ≥1 个 requirement_key。",
            )
        fact_ids = _bounded_refs(
            raw.get("fact_ids"), f"{path}.fact_ids",
            field="fact_ids", valid=valid_fact_ids, code="unknown_fact_id",
        )
        covered.update(requirement_keys)
        normalized.append({
            "item_type": item_type,
            "title": title,
            "detail": detail,
            "priority": priority,
            "requirement_keys": requirement_keys,
            "fact_ids": fact_ids,
        })
    missing = sorted(accepted_keys - covered)
    if missing:
        raise PlanDraftContractError(
            "coverage_incomplete", "items",
            f"以下已批准需求未被任何条目引用：{missing}（每条需求 key 至少被一个条目引用）。",
        )
    return normalized


def _run_plan_draft_ai(
    *, user_id: str, project_id: str, prompt: str, execution_id: str,
    accepted_keys: set[str], valid_fact_ids: set[str],
) -> tuple[list[dict[str, Any]], str | None]:
    """完整起草调用（克隆 N3a ``_run_draft_ai`` 纪律）。

    概率性契约/JSON 失败即时重试一次；瞬时错误退避重试一次。成功返回
    （归一化条目, 模型名）；不可恢复失败上抛 ``PlanDraftContractError`` /
    ``json.JSONDecodeError`` / ``DSHRuntimeError``（由路由面映射 HTTP）。
    """
    attempts = 0
    while True:
        attempts += 1
        try:
            answer: Any = execute_ai_prompt(
                user_id=user_id,
                prompt=prompt,
                system_prompt=DELIVERY_PLAN_DRAFT_SYSTEM_PROMPT,
                use_tools=False,
                project_id=project_id,
                execution_id=execution_id,
                purpose=PLAN_DRAFT_PURPOSE,
                prompt_version=PLAN_DRAFT_PROMPT_VERSION,
                return_metadata=True,
            )
            if not isinstance(answer, dict):
                answer = dict(text=answer, model={})
            text = answer.get("text")
            payload = json.loads(text) if isinstance(text, str) else text
            items = validate_plan_draft(payload, accepted_keys, valid_fact_ids)
            model_name = str(((answer.get("model") or {}).get("name") or "")) or None
            return items, model_name
        except (json.JSONDecodeError, PlanDraftContractError):
            if attempts > _CONTRACT_RETRY_LIMIT:
                raise
            # 概率性契约/JSON 失败：立即重试（discovery 同裁，留痕走异常冒泡）
        except DSHRuntimeError as error:
            if error.code not in _TRANSIENT_RETRY_CODES or attempts > _CONTRACT_RETRY_LIMIT:
                raise
            time.sleep(_RETRY_BACKOFF_SECONDS)


def _redact_value(value: Any, *, project_code: str, sink: list[dict[str, Any]]) -> Any:
    """输出端兜底脱敏（discovery/N3a 第③层同构）：命中词典/疑似均替换并记复核。"""
    if isinstance(value, str):
        result = redact_text_detailed(value, project_code=project_code)
        for suspect in result.suspects:
            sink.append({"name": suspect.name, "occurrences": suspect.occurrences, "matched_dict": False})
        for name in result.replaced:
            sink.append({"name": name, "occurrences": 1, "matched_dict": True})
        return result.text
    if isinstance(value, list):
        return [_redact_value(item, project_code=project_code, sink=sink) for item in value]
    if isinstance(value, dict):
        return {key: _redact_value(item, project_code=project_code, sink=sink) for key, item in value.items()}
    return value


def draft_ai_delivery_plan(*, actor, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """AI 起草交付方案草稿（can_manage；产出 draft 方案，人工审核闸承载发布语义）。

    失败语义（fail-closed 家族一致，**全管线最后一步才是写入**）：
    - 无已批准需求且无已接受事实 ⇒ 409 no_approved_inputs（AI 调用前即拒，
      与确定性生成器同码，零烧费）；
    - AI 通道/预算/权限类故障 ⇒ ``DSHRuntimeError`` 原样上抛（路由面 503/409 映射）；
    - 契约违规（整批）⇒ 重试一次仍违 ⇒ 409 ai_draft_contract_failed（**零写入**）；
    - 词典机制故障 ⇒ 422 pseudonym_dict_unavailable（fail-closed，零写入）；
    - 条目正文命中凭据串 ⇒ 422 sensitive_credential_detected（零写入）。
    成功 ⇒ 201：draft 方案（版本递增、历史不覆盖）＋条目＋
    delivery_plan_ai_drafted 事件（prompt_version/model 归因留痕）＋脱敏复核事件。
    产物恒为 draft——发布语义由 ``review_plan``（approved 闸）→``publish_plan``
    既有闸机械承载（G-04 判据「仅经 approved 闸发布」＝既有闸钉死，AI 无旁路）。
    """
    from fde_api.discovery.models import BusinessFact, Requirement
    from fde_api.ontology.models import OntologyTerm

    session = db.session()
    try:
        with session.begin():
            project = _require_project(session, actor, project_id, manage=True)
            requirements = session.scalars(
                select(Requirement)
                .where(Requirement.project_id == project.id, Requirement.status == "accepted")
                .order_by(Requirement.requirement_key)
            ).all()
            facts = session.scalars(
                select(BusinessFact)
                .where(BusinessFact.project_id == project.id, BusinessFact.review_status == "accepted")
                .order_by(BusinessFact.created_at)
            ).all()
            open_facts = session.scalars(
                select(BusinessFact)
                .where(
                    BusinessFact.project_id == project.id,
                    BusinessFact.review_status == "needs_clarification",
                )
                .order_by(BusinessFact.created_at)
            ).all()
            terms = session.scalars(
                select(OntologyTerm.term).where(
                    OntologyTerm.project_id == project.id, OntologyTerm.status == "confirmed"
                )
            ).all()
            if not requirements and not facts:
                raise PlansServiceError(
                    "no_approved_inputs",
                    "尚无已批准需求或已接受事实：先完成访谈事实/需求审阅再生成方案。",
                    409,
                )
            accepted_keys = {row.requirement_key for row in requirements}
            valid_fact_ids = {row.id for row in facts} | {row.id for row in open_facts}
            prompt = build_plan_draft_user_prompt(
                [
                    {
                        "requirement_key": row.requirement_key,
                        "title": row.title,
                        "priority": row.priority or "medium",
                        "acceptance_criteria": row.acceptance_criteria or [],
                    }
                    for row in requirements
                ],
                [
                    {"id": row.id, "subject": row.subject, "predicate": row.predicate, "object_value": row.object_value}
                    for row in facts
                ],
                [
                    {"id": row.id, "subject": row.subject, "predicate": row.predicate, "object_value": row.object_value}
                    for row in open_facts
                ],
                list(terms),
            )
            execution_id = f"plan-draft:{project.id}:{uuid4().hex[:8]}"
            # ── AI 调用（契约/JSON 失败整批拒；瞬时退避；失败零写入）──
            try:
                items, model_name = _run_plan_draft_ai(
                    user_id=actor.id, project_id=project.id, prompt=prompt,
                    execution_id=execution_id, accepted_keys=accepted_keys,
                    valid_fact_ids=valid_fact_ids,
                )
            except (PlanDraftContractError, json.JSONDecodeError) as error:
                detail = getattr(error, "code", None) or "invalid_json"
                raise PlansServiceError(
                    "ai_draft_contract_failed",
                    f"AI 起草结果未通过契约校验（已自动重试仍失败：{detail}），请重跑或更换模型。",
                    409,
                ) from error
            # ── 输出端兜底脱敏（凭据命中 fail-closed；词典故障 fail-closed）──
            redaction_entries: list[dict[str, Any]] = []
            redacted = []
            for item in items:
                redacted.append({
                    **item,
                    "title": _redact_value(item["title"], project_code=project.enterprise_code, sink=redaction_entries),
                    "detail": _redact_value(item["detail"], project_code=project.enterprise_code, sink=redaction_entries),
                })
            # ── 整批写入（管线最后一步；此前零业务写入——失败路径无残留）──
            version = _next_version(session, project.id)
            plan = DeliveryPlan(
                project_id=project.id,
                created_by_user_id=actor.id,
                title=f"交付方案（AI 起草）v{version}",
                summary=f"AI 起草：需求 {len(requirements)} 条 · 事实 {len(facts)} 条 · 术语 {len(terms)} 个",
                status="draft",
                version=version,
            )
            session.add(plan)
            session.flush()
            for order, spec in enumerate(redacted):
                session.add(DeliveryPlanItem(
                    plan_id=plan.id,
                    project_id=project.id,
                    item_type=spec["item_type"],
                    title=spec["title"][:200],
                    detail=spec.get("detail"),
                    priority=spec.get("priority", "medium"),
                    requirement_keys=spec.get("requirement_keys") or None,
                    fact_ids=spec.get("fact_ids") or None,
                    sort_order=order,
                ))
            session.add(OperationEvent(
                actor_user_id=actor.id,
                project_id=project.id,
                target_type="delivery_plan",
                target_id=plan.id,
                event_type="delivery_plan_ai_drafted",
                changes={
                    "version": plan.version,
                    "item_count": len(redacted),
                    "prompt_version": PLAN_DRAFT_PROMPT_VERSION,
                    "model": model_name,
                },
            ))
            if redaction_entries:
                session.add(OperationEvent(
                    actor_user_id=actor.id,
                    project_id=project.id,
                    target_type="delivery_plan",
                    target_id=plan.id,
                    event_type="delivery_plan_redaction_review",
                    changes={"entries": fingerprint_review_payload(redaction_entries)},
                ))
            session.flush()
            return {
                "plan": serialize_plan(session, plan),
                "created": True,
                "model": model_name,
                "prompt_version": PLAN_DRAFT_PROMPT_VERSION,
            }
    except SensitiveCredentialDetected:
        raise PlansServiceError(
            "sensitive_credential_detected",
            "AI 起草的条目正文疑似包含凭据，为守住「凭据不落库」红线已整批拒绝。请重跑。",
            422,
        ) from None
    except RedactionConfigError:
        raise PlansServiceError(
            DICT_FAILURE_CODE,
            "词典机制性故障导致 AI 起草失败（fail-closed 已阻断落库）。请联系管理员修复词典配置后重跑。",
            422,
        ) from None
    finally:
        session.close()
