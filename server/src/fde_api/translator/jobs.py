"""翻译器 AI 翻译管道（goal-d9，PRD §3.2 P3）。

沿预调研分析（guidance/jobs.py）的 job 重试语义：瞬时错误退避重试、契约
违反立即重试、重试耗尽落 failed（绝不卡在 running 让前端无限轮询）；worker
进程死亡由对账收尾钩子推终态。与预调研的差异：无文件流（原文=表单三段），
AI 客户端走文本 JSON 栈（goal-d13 拍板：kimi-k3 槽位，通用 OpenAI 兼容
complete_json 客户端承载，可注入），成功就绪点记 O-3 席位动作
（action_type="ai_chat"——PRD §7：翻译器在订阅额度内）。
"""
from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

from flask import current_app

from fde_api.ai.deepseek import DeepSeekClient, DeepSeekError
from fde_api.extensions import db
from fde_api.guidance.ai_schema import GuidanceContractError, validate_guidance_output
from fde_api.jobs.handlers import register_handler, register_job_failure_handler
from fde_api.translator.ai_prompt import build_translator_messages
from fde_api.translator.models import TranslatorTranslation

logger = logging.getLogger(__name__)

# 同一任务内的自动重试上限（不含首次尝试）；必须有测试钉住（guidance 同款纪律）。
TRANSLATOR_RETRY_LIMIT = 1

# 退避只对瞬时错误有意义；契约违反立即重试（概率性问题，退避白等）。
TRANSIENT_RETRY_CODES = frozenset({"ai_rate_limited", "ai_timeout", "ai_unavailable", "ai_service_unavailable"})
RETRY_BACKOFF_SECONDS = 1.0

UNEXPECTED_FAILURE_CODE = "translation_unexpected_error"
WORKER_LOST_CODE = "translation_worker_lost"

TRANSLATOR_JOB_TYPE = "translator.translate"


def handle_translator_translate(job) -> None:
    session = db.session()
    try:
        row = session.get(TranslatorTranslation, job.target_id)
        # 终态直接跳过：同一目标的重复投递不得二次调用 AI 覆盖已有结论。
        if row is None or row.status in {"ready", "failed"}:
            return
        row.status = "running"
        session.commit()
        settings = current_app.config["SETTINGS"]
        client = _client(settings)
        profile = row.profile_json or {}
        profile_text = (
            f"行业={profile.get('industry') or '未填写'}；规模={profile.get('scale') or '未填写'}；"
            f"地域={profile.get('region') or '未填写'}；访谈方式={profile.get('interview_mode') or '未填写'}"
        )
        messages = build_translator_messages(
            vision=row.customer_vision,
            phase_objective=row.phase_objective,
            profile_text=profile_text,
        )
        attempts = 0
        while True:
            attempts += 1
            try:
                payload = client.complete_json(
                    messages=messages,
                    # 每次尝试一个独立请求号：上游若按请求号去重，复用同一
                    # id 会让第二次拿回第一次的坏结果。
                    request_id=f"{job.id}:{attempts}",
                    max_tokens=12_000,
                )
                draft = validate_guidance_output(payload, source_refs=SOURCE_REFS)
                break
            except DeepSeekError as error:
                if not error.retryable or attempts > TRANSLATOR_RETRY_LIMIT:
                    _safe_fail(
                        session, job.target_id, error.code,
                        _exhausted_message(error.public_message, attempts, retryable=error.retryable),
                    )
                    return
                _backoff_before_retry(error)
            except GuidanceContractError as error:
                if attempts > TRANSLATOR_RETRY_LIMIT:
                    logger.warning(
                        "translator contract violation not recovered (%s at %s)",
                        error.code, error.path,
                    )
                    _safe_fail(
                        session, job.target_id, "ai_output_invalid",
                        _exhausted_message("AI 返回的项目指引格式不正确。", attempts, retryable=True),
                    )
                    return
                # 契约失败是概率性问题，立即重试。
        row.result_json = draft
        row.ai_model = settings.kimi_translator_model
        row.ai_generated_at = datetime.now(UTC)
        row.status = "ready"
        row.failure_code = ""
        row.failure_message = ""
        session.commit()
        # O-3 计费挂账：seat_action_ledger.project_id NOT NULL，翻译器无项目
        # 维度——额度计量随「采纳流/portal 绑项目」一并落（goal-d9 报告 §四）。
    except Exception as error:  # noqa: BLE001 - 翻译绝不能卡在 running 态
        logger.warning("translator unexpected failure (%s)", type(error).__name__)
        _safe_fail(
            session, job.target_id, UNEXPECTED_FAILURE_CODE,
            "翻译过程出现未预期错误，请重试；若持续失败请联系系统运维员。",
        )
    finally:
        session.close()


SOURCE_REFS = {"translator:vision", "translator:objective", "translator:profile"}  # set：validate 入参契约


def _client(settings) -> DeepSeekClient:
    injected = current_app.extensions.get("fde_api_translator_ai")
    if injected is not None:
        return injected
    # goal-d13 拍板：翻译管道走独立 kimi 槽位（Moonshot OpenAI 兼容端点）。
    # DeepSeekClient 本体是通用 OpenAI 兼容 JSON 客户端（model/json_object/
    # max_tokens 三参数无厂商专有字段），换 base_url/key/model 即换供应商；
    # 不配 fallback（kimi 槽位无备用模型，失败走本模块重试语义）。
    # base_url 取翻译槽位自己的（goal-d13 补正）：部署 env 可能把共享
    # kimi_base_url 指向另一家 OpenAI 兼容端点，共用会把 kimi-k3 打到
    # 没有该模型的端点上。
    return DeepSeekClient(
        base_url=settings.kimi_translator_base_url,
        api_key=settings.kimi_translator_api_key,
        model=settings.kimi_translator_model,
        timeout_seconds=settings.kimi_timeout_seconds,
    )


def _exhausted_message(public_message: str, attempts: int, *, retryable: bool = True) -> str:
    retries = attempts - 1
    if retries <= 0:
        return public_message
    if not retryable:
        return f"{public_message}（已自动重试 {retries} 次仍失败）"
    return f"{public_message}（已自动重试 {retries} 次仍失败，请重新发起翻译）"


def _backoff_before_retry(error: DeepSeekError) -> None:
    if error.code not in TRANSIENT_RETRY_CODES:
        return
    time.sleep(RETRY_BACKOFF_SECONDS)


def _safe_fail(session, translation_id: str, code: str, message: str) -> None:
    session.rollback()
    row = session.get(TranslatorTranslation, translation_id)
    if row is None or row.status in {"ready", "failed"}:
        return
    row.status = "failed"
    row.failure_code = code
    row.failure_message = message
    session.commit()


def fail_translation_on_worker_loss(session, job) -> None:
    """worker 进程死亡：翻译行推终态，否则前端永远轮询。"""
    row = session.get(TranslatorTranslation, job.target_id)
    if row is None or row.status in {"ready", "failed"}:
        return
    row.status = "failed"
    row.failure_code = WORKER_LOST_CODE
    row.failure_message = "翻译任务因服务重启中断，请重新发起。"


def register_translator_handler() -> None:
    register_handler(TRANSLATOR_JOB_TYPE, handle_translator_translate)


def register_translator_failure_handler() -> None:
    register_job_failure_handler(TRANSLATOR_JOB_TYPE, fail_translation_on_worker_loss)
