"""翻译器 AI 翻译管道（goal-d9，PRD §3.2 P3）。

沿预调研分析（guidance/jobs.py）的 job 重试语义：瞬时错误退避重试、契约
违反立即重试、重试耗尽落 failed（绝不卡在 running 让前端无限轮询）；worker
进程死亡由对账收尾钩子推终态。与预调研的差异：无文件流（原文=表单三段），
AI 客户端走文本 JSON 栈（goal-d14 拍板：**与 AI 聊天同源解析模型**——模型
偏好表优先，回落系统默认槽位；env 可选覆盖 kimi 翻译槽位），成功就绪点记
O-3 席位动作（action_type="ai_chat"——PRD §7：翻译器在订阅额度内）。
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
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
    actor_token = None
    try:
        row = session.get(TranslatorTranslation, job.target_id)
        # 终态直接跳过：同一目标的重复投递不得二次调用 AI 覆盖已有结论。
        if row is None or row.status in {"ready", "failed"}:
            return
        row.status = "running"
        session.commit()
        settings = current_app.config["SETTINGS"]
        # 后台任务没有请求上下文：显式把 actor 设为翻译提交人——启用 AI Server
        # 时，structured_completion 会按这个人解析模型偏好（与他的 AI 聊天
        # 同款），而不是回落到任意管理员。用完复位（worker 线程复用，
        # 残留会串到同线程的下一个任务）。
        from fde_api.control.ai_server_client import ai_actor_id
        actor_token = ai_actor_id.set(row.created_by_user_id)
        target = _resolve_ai_target(session, settings, row.created_by_user_id)
        client = _client(settings, target)
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
        row.ai_model = target.model
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
        if actor_token is not None:
            # 复位 ContextVar：worker 线程会被复用，残留的 actor 会串到下一个
            # 任务（让别人的 AI 调用按错的人解析模型偏好）。
            from fde_api.control.ai_server_client import ai_actor_id
            ai_actor_id.reset(actor_token)


SOURCE_REFS = {"translator:vision", "translator:objective", "translator:profile"}  # set：validate 入参契约


@dataclass(frozen=True, slots=True)
class _AiTarget:
    """翻译管道实际要用的模型落点（端点 + 密钥 + 模型名 + 超时 + 来源标记）。"""

    base_url: str
    api_key: str | None
    model: str
    timeout_seconds: int
    source: str


def _secret_value(value) -> str | None:
    """SecretStr / str / None → 明文密钥（None 或空串都当没配）。"""
    if value is None:
        return None
    if hasattr(value, "get_secret_value"):
        value = value.get_secret_value()
    text = str(value).strip()
    return text or None


def _resolve_ai_target(session, settings, user_id: str | None) -> _AiTarget:
    """翻译用哪个模型（goal-d14 拍板：与 AI 聊天同源解析）。

    优先级：
    1) **env 覆盖**：kimi 翻译槽位三件配齐 → 强制走 kimi-k3（留给将来拿到
       kimi key 的口子；蔡工当前没有 kimi key，故默认不配）。
    2) **同源解析**：与 AI 聊天完全同一套模型解析（模型偏好表 → 系统默认
       槽位），即 AI 聊天里配好的那个模型，翻译就用那个。
    3) **兜底系统默认槽位**：个人偏好不可用（无 AI 权限 / 密钥不可解 /
       未配置）时回落系统默认槽位——翻译是工作台基础能力，不该因为某个
       人的偏好问题整体停摆；系统默认也没配 key 时由客户端分类失败
       （ai_service_not_configured，不裸 500）。
    """
    override_key = _secret_value(settings.kimi_translator_api_key)
    if override_key:
        return _AiTarget(
            base_url=settings.kimi_translator_base_url,
            api_key=override_key,
            model=settings.kimi_translator_model,
            timeout_seconds=settings.kimi_timeout_seconds,
            source="env_override",
        )
    resolved = _resolve_preference(session, user_id)
    if resolved is not None:
        return _AiTarget(
            base_url=resolved["base_url"],
            api_key=resolved["api_key"],
            model=resolved["model"],
            timeout_seconds=settings.dsh_timeout_seconds,
            source=resolved["source"],
        )
    return _AiTarget(
        base_url=settings.deepseek_base_url,
        api_key=_secret_value(settings.deepseek_api_key),
        model=settings.deepseek_industry_template_model,
        timeout_seconds=settings.deepseek_timeout_seconds,
        source="system_default",
    )


def _resolve_preference(session, user_id: str | None) -> dict | None:
    """与 AI 聊天同源的模型解析（模型偏好表 → 系统默认槽位）。

    解析不可用时返回 None（调用方回落系统默认槽位），不抛错——翻译不该
    因为个人偏好缺失而失败。
    """
    if not user_id:
        return None
    from fde_api.control.model_preferences import resolve_model_preference
    from fde_api.control.service import ControlServiceError
    try:
        resolved = resolve_model_preference(session, user_id)
    except ControlServiceError as error:
        logger.warning("translator model preference unavailable (%s)", error.code)
        return None
    api_key = _secret_value(resolved.get("api_key"))
    base_url = str(resolved.get("base_url") or "").rstrip("/")
    model = str(resolved.get("model") or "")
    if not base_url or not model:
        return None
    return {
        "base_url": base_url,
        "api_key": api_key,
        "model": model,
        # "system-default" = 解析器自己落的系统默认槽位；其余是偏好表里的模型。
        "source": "system_default" if resolved.get("id") == "system-default" else "model_preference",
    }


def _client(settings, target: _AiTarget) -> DeepSeekClient:
    injected = current_app.extensions.get("fde_api_translator_ai")
    if injected is not None:
        return injected
    # goal-d14 拍板：翻译与 AI 聊天同源——用「就地解析出的模型落点」构造
    # 通用 OpenAI 兼容客户端。DeepSeekClient 本体是通用 OpenAI 兼容 JSON
    # 客户端（model/json_object/max_tokens 三参数无厂商专有字段），换
    # base_url/key/model 即换供应商；DSH 启用时它内部自动改走 AI Server
    # （与 AI 聊天同一条路），不配 fallback（失败走本模块重试语义）。
    return DeepSeekClient(
        base_url=target.base_url,
        api_key=target.api_key,
        model=target.model,
        timeout_seconds=target.timeout_seconds,
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
