"""quality AI 起草管线（AI 原生化 N3a，G-05 消解）。

把「AI 起草 → 人工审核 → 发布」两段式推进到 quality 域（试点首发位 D-4）：

- **单一入口**（DoD①）：AI 调用走 ``execute_ai_prompt``（预算门＋审计＋
  提示词指纹/版本归因＋降级直连全在册——N2 G-09 已落，本模块不自造通道）；
- **契约失败整批零写入**（DoD②，fail-closed 家族一致）：输出契约校验
  （``validate_testcase_draft``）任一违规整批拒绝——概率性畸形输出即时重试
  一次（discovery 同裁），仍失败即 409；**DB 写入是全管线最后一步且在同一
  事务内**，此前零业务写入，失败路径零残留；
- **草稿态不可被下游消费**（DoD③）：产出落 draft 计划＋draft 用例，执行
  （``execute_test_plan`` 仅 approved）与发布（``review_test_plan`` 审核闸＋
  需求覆盖闸）均不动——「不自动批准、不跳需求覆盖闸、不动 production 硬闸」
  的任务书边界由既有闸机械承载；AI 侧先验覆盖完整性（每条 accepted 需求
  ≥1 条用例，缺项 409 整批拒）是**第一道**，审核时的覆盖闸是**第二道**；
- **输出端兜底脱敏**（证据红线同族，克隆 discovery 第③层）：用例字符串
  字段过 ``redact_text_detailed``——词典机制故障 fail-closed（不落库）、
  凭据串命中整批拒绝；替换留痕进 ``quality.redaction_review`` 事件；
- **溯源**（N2 纪律）：``prompt_version`` 经单一入口进审计账本，事件
  留痕带版本＋模型名——AI 起草可归因。

输入侧纪律：用户提示词只由**已批准需求行**（已代号化的需求库数据）拼装，
无外部文字进模型（外部文字禁入契约 P-4 同尺）；requirement_key 闭集=
本项目 accepted 键集，AI 不得虚构键（越界键整批拒绝）。
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
from fde_api.quality.models import TestCase, TestPlan
from fde_api.quality.service import QualityServiceError, _require_project, serialize_plan
from fde_api.workbench.models import OperationEvent, ProjectTask

__all__ = [
    "DRAFT_PURPOSE",
    "DRAFT_PROMPT_VERSION",
    "MAX_AI_CASES",
    "QUALITY_TESTCASE_DRAFT_SYSTEM_PROMPT",
    "QualityDraftContractError",
    "build_draft_user_prompt",
    "draft_ai_test_plan",
    "validate_testcase_draft",
]

# 提示词版本（N2 归因纪律：审计账本按版本归因；提示词正文改动必须升版本）。
# N6/G-13：标签唯一权威＝ai/prompt_registry.py（正文改动必同步注册表升版本）。
DRAFT_PROMPT_VERSION = version_of("fde_api.quality.draft", "QUALITY_TESTCASE_DRAFT_SYSTEM_PROMPT")
# 审计 purpose（ai_call_audits NOT NULL CHECK；≤60 字自由文本域）。
DRAFT_PURPOSE = "quality_testcase_draft"

# 单批用例上限（供应商输出预算下的保守配额——宁缺毋滥，同 discovery 纪律）。
MAX_AI_CASES = 50
# 单用例字段上限（对齐 test_cases 列形状：title 200；steps/expected 保守 2000）。
_TITLE_MAX = 200
_TEXT_MAX = 2000
_STEP_MAX = 500
_MAX_STEPS = 20
_RISK_LEVELS = {1, 2, 3}
_ACCEPTANCE_MODES = {"test", "manual"}

# 瞬时错误退避重试（discovery 同裁；同步路由面单次退避）。
_TRANSIENT_RETRY_CODES = frozenset({"ai_rate_limited", "ai_timeout", "ai_service_unavailable", "ai_unavailable"})
_RETRY_BACKOFF_SECONDS = 1.0
# 契约/JSON 失败即时重试上限（概率性畸形输出——discovery CONTRACT_RETRY_LIMIT 同值）。
_CONTRACT_RETRY_LIMIT = 1

QUALITY_TESTCASE_DRAFT_SYSTEM_PROMPT = f"""你是制造业交付项目的测试用例起草器。输入是本项目当前全部已批准需求（结构化清单），\
你只做忠实起草，不得虚构需求。

输出一个 JSON 对象，恰好包含一个键 cases。

cases 是数组（至多 {MAX_AI_CASES} 条），每项恰好包含基础键：
- requirement_key：该用例追溯的需求键，必须逐字取自输入清单中的 requirement_key（不得虚构、不得改写）；
- title：用例标题（≤{_TITLE_MAX} 字）；
- steps：操作步骤数组（0–{_MAX_STEPS} 步，每步 ≤{_STEP_MAX} 字，字符串）；
- expected：预期结果（非空，≤{_TEXT_MAX} 字，可验证、不写空话）；
- risk_level：1|2|3（整数；3=高影响）；
- acceptance_mode：test|manual（test=可自动/脚本验证；manual=明确人工验收方式，须写清验收人动作与判定标准）；
可选键：
- preconditions（≤{_TEXT_MAX} 字，可为空）；
- automated（布尔，是否已可自动执行，默认 false）。

硬性纪律：
1. 输入清单中的**每一条 requirement_key 至少有一条用例**（人工审核时的需求覆盖闸会复查，缺条即整批被拒）；
2. 用例必须可追溯到具体需求键；不得引用清单之外的键；
3. 只输出 JSON，不要输出任何其他文字；正文不得包含凭据（密码/密钥/令牌）。"""


class QualityDraftContractError(ValueError):
    """AI 起草输出契约违规（任一违规整批拒绝，不部分写入）。"""

    def __init__(self, code: str, path: str, message: str):
        super().__init__(message)
        self.code, self.path, self.message = code, path, message


def _bounded_text(raw: object, path: str, limit: int, *, field: str, allow_empty: bool = False) -> str | None:
    if raw is None:
        if allow_empty:
            return None
        raise QualityDraftContractError("invalid_text", path, f"{field} 缺失。")
    if not isinstance(raw, str) or len(raw) > limit or (not raw.strip() and not allow_empty):
        raise QualityDraftContractError("invalid_text", path, f"{field} 为空、超长或格式不正确（≤{limit} 字）。")
    return raw.strip() or None


def build_draft_user_prompt(requirements: list[dict[str, Any]]) -> str:
    """拼装 AI 起草的用户提示词（确定性：按 requirement_key 字典序，#209 教训）。

    输入面=已批准需求行（已代号化的需求库数据）——零外部文字进模型。
    """
    ordered = sorted(requirements, key=lambda item: item["requirement_key"])
    lines = ["【已批准需求清单】（requirement_key 必须逐字引用）", ""]
    for index, row in enumerate(ordered, start=1):
        criteria = "；".join(row["acceptance_criteria"] or [])[:1500] or "（未附验收标准，按标题起草）"
        lines.append(
            f"{index}. key={row['requirement_key']}｜标题={str(row['title'])[:_TITLE_MAX]}"
            f"｜类型={row['requirement_type']}｜优先级={row['priority']}"
            f"｜验收标准={criteria}"
        )
    lines += [
        "",
        "【任务】为以上全部需求起草测试用例（每条需求 ≥1 条；manual 模式写清人工验收动作与判定标准），"
        "按系统指令输出的 JSON 契约返回。",
    ]
    return "\n".join(lines)


def validate_testcase_draft(payload: object, accepted_keys: set[str]) -> list[dict[str, Any]]:
    """校验 AI 起草输出；任一违规整批拒绝（不部分写入）。

    归一化产出：用例按 (requirement_key, 原下标) 全序排定 sort_order
    （确定性——同 discovery #209 组序教训：uuid4 无内在序，插入序不可依赖）。
    覆盖完整性（每条 accepted 需求 ≥1 条用例）在此先验——缺项整批拒绝。
    """
    if not isinstance(payload, dict) or set(payload) != {"cases"}:
        raise QualityDraftContractError("invalid_draft", "", "AI 返回的起草结果字段不完整（须为 {cases}）。")
    raw_cases = payload["cases"]
    if not isinstance(raw_cases, list) or not raw_cases or len(raw_cases) > MAX_AI_CASES:
        raise QualityDraftContractError(
            "invalid_cases", "cases", f"用例数组格式不正确（1–{MAX_AI_CASES} 条）。"
        )
    base_keys = {"requirement_key", "title", "steps", "expected", "risk_level", "acceptance_mode"}
    allowed_keys = base_keys | {"preconditions", "automated"}
    normalized: list[tuple[str, int, dict[str, Any]]] = []
    for index, raw in enumerate(raw_cases):
        path = f"cases[{index}]"
        if not isinstance(raw, dict) or not base_keys <= set(raw) <= allowed_keys:
            raise QualityDraftContractError("invalid_case", path, "用例条目格式不正确。")
        key = raw["requirement_key"]
        if not isinstance(key, str) or key not in accepted_keys:
            raise QualityDraftContractError(
                "unknown_requirement_key", f"{path}.requirement_key",
                "用例引用了清单之外的需求键（不得虚构）。",
            )
        title = _bounded_text(raw["title"], f"{path}.title", _TITLE_MAX, field="title")
        steps = raw["steps"]
        if not isinstance(steps, list) or len(steps) > _MAX_STEPS or not all(
            isinstance(step, str) and len(step) <= _STEP_MAX for step in steps
        ):
            raise QualityDraftContractError(
                "invalid_steps", f"{path}.steps", f"步骤须为字符串数组（0–{_MAX_STEPS} 步，每步 ≤{_STEP_MAX} 字）。"
            )
        expected = _bounded_text(raw["expected"], f"{path}.expected", _TEXT_MAX, field="expected")
        risk_level = raw["risk_level"]
        if not isinstance(risk_level, int) or isinstance(risk_level, bool) or risk_level not in _RISK_LEVELS:
            raise QualityDraftContractError("invalid_risk_level", f"{path}.risk_level", "risk_level 须为 1/2/3 整数。")
        acceptance_mode = raw["acceptance_mode"]
        if acceptance_mode not in _ACCEPTANCE_MODES:
            raise QualityDraftContractError(
                "invalid_acceptance_mode", f"{path}.acceptance_mode", "acceptance_mode 须为 test/manual。"
            )
        preconditions = _bounded_text(
            raw.get("preconditions"), f"{path}.preconditions", _TEXT_MAX, field="preconditions", allow_empty=True
        )
        automated = raw.get("automated", False)
        if not isinstance(automated, bool):
            raise QualityDraftContractError("invalid_automated", f"{path}.automated", "automated 须为布尔值。")
        normalized.append((key, index, {
            "requirement_key": key,
            "title": title,
            "preconditions": preconditions,
            "steps": [step.strip() for step in steps],
            "expected": expected,
            "risk_level": risk_level,
            "acceptance_mode": acceptance_mode,
            "automated": automated,
        }))
    covered = {key for key, _, _ in normalized}
    missing = sorted(accepted_keys - covered)
    if missing:
        raise QualityDraftContractError(
            "coverage_incomplete", "cases",
            f"以下已批准需求未被任何用例覆盖：{missing}（每条批准需求至少一条用例）。",
        )
    # 确定性全序：(requirement_key, 原下标)——同需求键内保持模型给出的相对序
    normalized.sort(key=lambda item: (item[0], item[1]))
    return [case for _, _, case in normalized]


def _run_draft_ai(
    *, user_id: str, project_id: str, prompt: str, execution_id: str, accepted_keys: set[str],
) -> tuple[list[dict[str, Any]], str | None]:
    """完整起草调用（克隆 discovery ``_extract_chunk_once`` 纪律）。

    概率性契约/JSON 失败即时重试一次；瞬时错误退避重试一次。成功返回
    （归一化用例, 模型名）；不可恢复失败上抛 ``QualityDraftContractError`` /
    ``json.JSONDecodeError`` / ``DSHRuntimeError``（由路由面映射 HTTP）。
    """
    attempts = 0
    while True:
        attempts += 1
        try:
            answer: Any = execute_ai_prompt(
                user_id=user_id,
                prompt=prompt,
                system_prompt=QUALITY_TESTCASE_DRAFT_SYSTEM_PROMPT,
                use_tools=False,
                project_id=project_id,
                execution_id=execution_id,
                purpose=DRAFT_PURPOSE,
                prompt_version=DRAFT_PROMPT_VERSION,
                return_metadata=True,
            )
            if not isinstance(answer, dict):
                answer = dict(text=answer, model={})
            text = answer.get("text")
            payload = json.loads(text) if isinstance(text, str) else text
            cases = validate_testcase_draft(payload, accepted_keys)
            model_name = str(((answer.get("model") or {}).get("name") or "")) or None
            return cases, model_name
        except (json.JSONDecodeError, QualityDraftContractError):
            if attempts > _CONTRACT_RETRY_LIMIT:
                raise
            # 概率性契约/JSON 失败：立即重试（discovery 同裁，留痕走异常冒泡）
        except DSHRuntimeError as error:
            if error.code not in _TRANSIENT_RETRY_CODES or attempts > _CONTRACT_RETRY_LIMIT:
                raise
            time.sleep(_RETRY_BACKOFF_SECONDS)


def _redact_value(value: Any, *, project_code: str, sink: list[dict[str, Any]]) -> Any:
    """输出端兜底脱敏（discovery 第③层同构）：命中词典/疑似均替换并记复核。"""
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


def draft_ai_test_plan(*, actor, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """AI 起草测试用例草稿（can_manage；产出 draft 计划，人工审核闸承载发布语义）。

    失败语义（fail-closed 家族一致，**全管线最后一步才是写入**）：
    - 无已批准需求 ⇒ 409 no_approved_requirements（AI 调用前即拒，与确定性生成同码）；
    - AI 通道/预算/权限类故障 ⇒ ``DSHRuntimeError`` 原样上抛（路由面 503/409 映射）；
    - 契约违规（整批）⇒ 重试一次仍违 ⇒ 409 ai_draft_contract_failed（**零写入**）；
    - 词典机制故障 ⇒ 422 pseudonym_dict_unavailable（fail-closed，零写入）；
    - 用例正文命中凭据串 ⇒ 422 sensitive_credential_detected（零写入）。
    成功 ⇒ 201：draft 计划（版本递增、历史不覆盖）＋用例全 draft 态＋
    test_plan_ai_drafted 事件（prompt_version/model 归因留痕）＋脱敏复核事件。
    产物恒为 draft——执行/发布语义由 ``execute_test_plan``/``review_test_plan``
    既有闸机械承载（草稿态不可被下游消费）。
    """
    from fde_api.discovery.models import Requirement

    session = db.session()
    try:
        with session.begin():
            project = _require_project(session, actor, project_id, manage=True)
            source_task_id = payload.get("source_task_id")
            if source_task_id is not None:
                if not isinstance(source_task_id, str):
                    raise QualityServiceError("invalid_request", "source_task_id 须为字符串。", 400)
                task = session.get(ProjectTask, source_task_id)
                if task is None or task.project_module is None or task.project_module.project_id != project.id:
                    raise QualityServiceError("task_not_found", "来源任务不存在。", 404)
            requirements = session.scalars(
                select(Requirement)
                .where(Requirement.project_id == project.id, Requirement.status == "accepted")
                .order_by(Requirement.requirement_key)
            ).all()
            if not requirements:
                raise QualityServiceError(
                    "no_approved_requirements",
                    "尚无已批准需求：先完成需求审阅再生成测试计划。",
                    409,
                )
            accepted_keys = {row.requirement_key for row in requirements}
            prompt = build_draft_user_prompt([
                {
                    "requirement_key": row.requirement_key,
                    "title": row.title,
                    "requirement_type": row.requirement_type,
                    "priority": row.priority or "medium",
                    "acceptance_criteria": row.acceptance_criteria or [],
                }
                for row in requirements
            ])
            execution_id = f"quality-draft:{project.id}:{uuid4().hex[:8]}"
            # ── AI 调用（契约/JSON 失败整批拒；瞬时退避；失败零写入）──
            try:
                cases, model_name = _run_draft_ai(
                    user_id=actor.id, project_id=project.id, prompt=prompt,
                    execution_id=execution_id, accepted_keys=accepted_keys,
                )
            except (QualityDraftContractError, json.JSONDecodeError) as error:
                detail = getattr(error, "code", None) or "invalid_json"
                raise QualityServiceError(
                    "ai_draft_contract_failed",
                    f"AI 起草结果未通过契约校验（已自动重试仍失败：{detail}），请重跑或更换模型。",
                    409,
                ) from error
            # ── 输出端兜底脱敏（凭据命中 fail-closed；词典故障 fail-closed）──
            redaction_entries: list[dict[str, Any]] = []
            redacted = []
            for case in cases:
                redacted.append({
                    **case,
                    "title": _redact_value(case["title"], project_code=project.enterprise_code, sink=redaction_entries),
                    "preconditions": _redact_value(case["preconditions"], project_code=project.enterprise_code, sink=redaction_entries),
                    "steps": _redact_value(case["steps"], project_code=project.enterprise_code, sink=redaction_entries),
                    "expected": _redact_value(case["expected"], project_code=project.enterprise_code, sink=redaction_entries),
                })
            # ── 整批写入（管线最后一步；此前零业务写入——失败路径无残留）──
            previous_version = session.scalar(
                select(TestPlan.version)
                .where(TestPlan.project_id == project.id)
                .order_by(TestPlan.version.desc())
                .limit(1)
            )
            plan = TestPlan(
                project_id=project.id,
                source_task_id=source_task_id,
                created_by_user_id=actor.id,
                title=f"测试计划（AI 起草）v{(previous_version or 0) + 1}",
                version=(previous_version or 0) + 1,
                status="draft",
            )
            session.add(plan)
            session.flush()
            for sort_order, case in enumerate(redacted):
                session.add(TestCase(
                    plan_id=plan.id,
                    project_id=project.id,
                    created_by_user_id=actor.id,
                    case_key=f"TC-{uuid4().hex[:8]}",
                    title=case["title"],
                    preconditions=case["preconditions"],
                    steps=case["steps"],
                    expected=case["expected"],
                    risk_level=case["risk_level"],
                    automated=case["automated"],
                    acceptance_mode=case["acceptance_mode"],
                    requirement_key=case["requirement_key"],
                    sort_order=sort_order,
                ))
            session.add(OperationEvent(
                actor_user_id=actor.id,
                project_id=project.id,
                target_type="test_plan",
                target_id=plan.id,
                event_type="test_plan_ai_drafted",
                changes={
                    "version": plan.version,
                    "case_count": len(redacted),
                    "prompt_version": DRAFT_PROMPT_VERSION,
                    "model": model_name,
                },
            ))
            if redaction_entries:
                session.add(OperationEvent(
                    actor_user_id=actor.id,
                    project_id=project.id,
                    target_type="test_plan",
                    target_id=plan.id,
                    event_type="quality.redaction_review",
                    changes={"entries": fingerprint_review_payload(redaction_entries)},
                ))
            session.flush()
            return {
                "plan": serialize_plan(session, plan),
                "created": True,
                "model": model_name,
                "prompt_version": DRAFT_PROMPT_VERSION,
            }
    except SensitiveCredentialDetected:
        raise QualityServiceError(
            "sensitive_credential_detected",
            "AI 起草的用例正文疑似包含凭据，为守住「凭据不落库」红线已整批拒绝。请重跑。",
            422,
        ) from None
    except RedactionConfigError:
        raise QualityServiceError(
            DICT_FAILURE_CODE,
            "词典机制性故障导致 AI 起草失败（fail-closed 已阻断落库）。请联系管理员修复词典配置后重跑。",
            422,
        ) from None
    finally:
        session.close()
