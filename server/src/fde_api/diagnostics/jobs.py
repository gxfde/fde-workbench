"""诊断报告异步生成（T-10b worker 腿）。

**为什么异步**：报告生成要调 AI（秒级到分钟级），公网免注册面**不能同步阻塞**
——同步会让访客在一个 HTTP 请求里等模型，队列一堵就整面不可用。故走本仓既有
的 outbox → background job → worker 三段（与 translator/discovery 同款）。

**AI 调用主体（匿名面没有账号）**：``execute_ai_prompt`` 要求一个真实的
``users`` 行（active + AI 权限）——预算闸与归因台账都要有主体。匿名访客没有
账号，故本域用**平台服务账号**：``FDE_DIAGNOSTICS_AI_ACTOR_USERNAME`` 指定一个
既有用户名，AI 用量与审计**如实记在它头上**（不伪造匿名用户，也不让预算无主）。
未配置 / 账号停用 / 无 AI 权限 ⇒ **fail-closed**（503 ``diagnostic_ai_unavailable``），
不静默降级成「没有报告」。

**诚实失败**：失败一律落 ``failure_code`` / ``failure_message``（访客能看到并
重试），**不吞错**；契约违规重试一次仍不过 ⇒ 落 ``report_contract_invalid``。
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fde_api.diagnostics.models import LeadDiagnosticSession
from fde_api.diagnostics.prompts import (
    DIAGNOSTIC_REPORT_SYSTEM_PROMPT,
    REPORT_PROMPT_VERSION,
    REPORT_PURPOSE,
    build_report_prompt,
)
from fde_api.diagnostics.questionnaire import SLOT_BY_KEY
from fde_api.diagnostics.report_contract import (
    ReportContractError,
    assemble_report,
    parse_report_json,
    sourced_number_tokens,
    validate_report_payload,
)
from fde_api.control.ai_server_client import execute_ai_prompt
from fde_api.extensions import db
from fde_api.guidance.enterprise_dict import RedactionConfigError
from fde_api.guidance.redaction import (
    SensitiveCredentialDetected,
    redact_text_detailed,
)
from fde_api.jobs.handlers import register_handler, register_job_failure_handler

logger = logging.getLogger(__name__)

# 作业类型＝outbox topic（同一把键：job 行与 outbox 行靠 (job_type, target_id) 对齐）
DIAGNOSTIC_REPORT_JOB_TYPE = "diagnostics.report"

# 契约失败的自动重试上限（不含首次）——同 guidance/translator 纪律：
# 契约违规是模型概率性问题，一次重试足以消化绝大多数；无上限会在模型持续吐
# 畸形输出时把 worker 拖死。
CONTRACT_RETRY_LIMIT = 1

# 报告输出预算（提示词＋答案的上下文已由服务端裁剪；这里只给正文留量）。
# 16000 是**标定值不是拍脑袋**（2026-11-11 curve 1 真机归因：6000 预算下思考
# 吃穿预算 ⇒ ai_output_truncated ×3 + 截断残 JSON 契约违规 ×3，6 卡全灭）：
# 推理模型（MiniMax-M3.1-Flash 级）的思考与正文**共用** max_tokens，6000 连
# 思考都不够；同端点同模型的 judge 通道实测 16000 双连过（输出 7.1k/8.2k，
# 思考占大头）、9000 采样到长思考仍截断——两路实测收敛同一值。上限依据
# V31-P1 实测：MiniMax-M3.1-Flash 硬顶 16384，请求超过硬顶换不来更多正文，
# 16000 贴顶而不过；「×2 预留」已被证伪（思考随预算增长），不再加码。
REPORT_MAX_TOKENS = 16000


class ReportGenerationError(Exception):
    """报告生成失败（code + 面向访客的文案）。"""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


def _fail_row(
    session: Any, row: LeadDiagnosticSession, code: str, message: str
) -> None:
    """落失败事实（不吞错；状态机留在 submitted，失败靠 failure_code 表达）。"""
    row.failure_code = code
    row.failure_message = message[:500]
    session.commit()


def _redact_report_text(value: Any) -> Any:
    """输出端兜底脱敏（T-A2 第③层同构）：命中词典/疑似名一律替换。

    输入侧已经脱敏过一遍，但**模型可能回显**——输出端必须再兜一层。
    词典机制性故障 ⇒ fail-closed（同码）；凭据串 ⇒ 拒收。
    """
    if isinstance(value, str):
        return redact_text_detailed(value).text
    if isinstance(value, list):
        return [_redact_report_text(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact_report_text(item) for key, item in value.items()}
    return value


def _slot_labels(answers: dict[str, Any]) -> dict[str, str]:
    return {key: SLOT_BY_KEY[key].label for key in answers if key in SLOT_BY_KEY}


def _diagnostic_model_override() -> dict[str, Any] | None:
    """诊断报告的**显式模型槽位**（opt-in，默认空＝零行为变更）。

    不设此键时报告模型沿用既有解析链（服务账号的模型偏好行 → system-default，
    system-default 借用的是行业模板槽位 ``FDE_DEEPSEEK_INDUSTRY_TEMPLATE_MODEL``
    ——curve 1 真机归因确认该链在单模型端点工作正常）。要给诊断报告独立模型
    （例如把行业模板槽挪作他用、或单模型端点换型）时设
    ``FDE_DEEPSEEK_DIAGNOSTIC_REPORT_MODEL`` 即整体接管模型选择——**单模型
    端点必须填端点实际在售的模型名**（deepseek-v4-pro 默认值在不售它的端点上
    会 400，curve 1 judge 侧同款教训）。
    """
    from flask import current_app

    model_name = str(
        current_app.config["SETTINGS"].deepseek_diagnostic_report_model or ""
    ).strip()
    if not model_name:
        return None
    from fde_api.control.model_preferences import _provider_for_base_url

    settings = current_app.config["SETTINGS"]
    key = settings.deepseek_api_key
    plaintext = (
        key.get_secret_value() if hasattr(key, "get_secret_value") else str(key or "")
    )
    base_url = str(settings.deepseek_base_url or "")
    if not base_url or not plaintext:
        # 显式接管却缺端点/密钥 ⇒ fail-closed：让调用按「模型未配置」失败，
        # 不静默回落偏好链（那会让「设了槽位却没生效」被掩盖）。
        raise ReportGenerationError(
            "report_model_slot_incomplete",
            "FDE_DEEPSEEK_DIAGNOSTIC_REPORT_MODEL 已设置但端点或密钥缺失。",
            retryable=False,
        )
    return {
        "model": model_name,
        "base_url": base_url,
        "api_key": plaintext,
        "provider": _provider_for_base_url(base_url),
    }


def _call_model(
    *,
    actor_user_id: str,
    row: LeadDiagnosticSession,
    repair_hint: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """调 AI（单一入口 ``execute_ai_prompt``）。

    ``repair_hint``：契约拒收原因（curve 3 断点 D3）——第一次尝试被拒后回灌，
    让第二次是**修复**而不是同提示词盲重抽。
    """
    prompt = build_report_prompt(
        answers=dict(row.answers or {}),
        assessment=dict(row.assessment or {}),
        slot_labels=_slot_labels(dict(row.answers or {})),
        repair_hint=repair_hint,
    )
    result = execute_ai_prompt(
        user_id=actor_user_id,
        prompt=prompt,
        system_prompt=DIAGNOSTIC_REPORT_SYSTEM_PROMPT,
        purpose=REPORT_PURPOSE,
        prompt_version=REPORT_PROMPT_VERSION,
        return_metadata=True,
        use_tools=False,
        max_tokens=REPORT_MAX_TOKENS,
        model_override=_diagnostic_model_override(),
    )
    text = ""
    model_info: dict[str, Any] = {}
    if isinstance(result, dict):
        text = str(result.get("text") or "")
        model = result.get("model") or {}
        if isinstance(model, dict):
            model_info = {
                "provider": str(model.get("provider") or ""),
                "name": str(model.get("name") or ""),
            }
    else:
        text = str(result or "")
    return text, model_info


def handle_diagnostic_report(job) -> None:
    """worker 处理器：生成并落库报告。"""
    from fde_api.diagnostics import service

    session = db.session()
    try:
        row = session.get(LeadDiagnosticSession, job.target_id)
        if row is None:
            return
        if service._enforce_retention(session, row):
            return
        # 终态直接跳过：重复投递不得二次调 AI 覆盖已有结论。
        if row.status in {"report_ready", "claimed", "expired"} or row.report:
            return

        try:
            actor = service.resolve_ai_actor(session)
        except service.DiagnosticsServiceError as error:
            _fail_row(session, row, error.code, error.message)
            return

        attempts = 0
        payload: dict[str, Any] | None = None
        model_info: dict[str, Any] = {}
        repair_hint: str | None = None
        while True:
            attempts += 1
            try:
                text, model_info = _call_model(
                    actor_user_id=actor.id, row=row, repair_hint=repair_hint
                )
                payload = validate_report_payload(
                    parse_report_json(text),
                    allowed_numbers=sourced_number_tokens(row.answers, row.assessment),
                )
                break
            except ReportContractError as error:
                if attempts > CONTRACT_RETRY_LIMIT:
                    _fail_row(session, row, error.code, error.message)
                    return
                # ★拒因回灌（curve 3 断点 D3）：第二次尝试必须看得见拒因，
                # 否则「可修的违规」（删一个数字／改写／标待澄清）会被盲重抽
                # 变成两次都不过 ⇒ 一个量词毙掉整份报告。
                repair_hint = error.message
                logger.warning(
                    "diagnostic report contract violation (attempt=%s code=%s)",
                    attempts,
                    error.code,
                )
            except Exception as error:  # noqa: BLE001 - AI 失败不得把作业卡死
                code = getattr(error, "code", "report_generation_failed")
                message = getattr(error, "public_message", None) or "报告生成失败，请稍后重试。"
                retryable = bool(getattr(error, "retryable", False))
                _fail_row(session, row, code, message)
                if retryable:
                    # 瞬时故障（限流/超时/服务不可用）交给 worker 的退避重投；
                    # 行上的失败码先落着，访客看得到「可重试」。
                    raise
                return

        try:
            report = assemble_report(
                payload=payload,
                assessment=dict(row.assessment or {}),
                model_info=model_info,
                generated_at=datetime.now(UTC).isoformat(),
                prompt_version=REPORT_PROMPT_VERSION,
            )
            report = _redact_report_text(report)
        except RedactionConfigError:
            _fail_row(
                session,
                row,
                "pseudonym_dict_unavailable",
                "暂时无法处理这份内容，请稍后再试。",
            )
            return
        except SensitiveCredentialDetected:
            _fail_row(
                session,
                row,
                "sensitive_credential_detected",
                "内容中疑似包含密码、密钥或令牌，请移除后重试。",
            )
            return

        row.report = report
        row.status = "report_ready"
        row.report_ready_at = datetime.now(UTC)
        row.failure_code = None
        row.failure_message = None
        session.commit()
    except Exception as error:  # noqa: BLE001 - 报告绝不能卡在 submitted 态
        logger.warning("diagnostic report unexpected failure (%s)", type(error).__name__)
        try:
            row = session.get(LeadDiagnosticSession, job.target_id)
            if row is not None:
                _fail_row(
                    session,
                    row,
                    "report_unexpected_error",
                    "报告生成出现未预期错误，请重试；若持续失败请联系系统运维员。",
                )
        except Exception:  # noqa: BLE001 - 兜底失败只记日志
            logger.warning("diagnostic report failure bookkeeping failed", exc_info=True)
    finally:
        session.close()


def fail_diagnostic_report_on_worker_lost(session, job) -> None:
    """worker 失联/放弃终失败 ⇒ 把失败事实落到会话行（访客看得到）。"""
    row = session.get(LeadDiagnosticSession, job.target_id)
    if row is None or row.report:
        return
    row.failure_code = "report_worker_lost"
    row.failure_message = "报告生成中断，请重试。"
    session.commit()


def register_diagnostic_report_handler() -> None:
    register_handler(DIAGNOSTIC_REPORT_JOB_TYPE, handle_diagnostic_report)
    register_job_failure_handler(
        DIAGNOSTIC_REPORT_JOB_TYPE, fail_diagnostic_report_on_worker_lost
    )
