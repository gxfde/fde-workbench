"""Small, injectable DeepSeek JSON client with safe public errors."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable

import requests
from pydantic import SecretStr


logger = logging.getLogger(__name__)


class DeepSeekError(Exception):
    def __init__(self, code: str, public_message: str, *, retryable: bool):
        super().__init__(public_message)
        self.code = code
        self.public_message = public_message
        self.retryable = retryable


class _Timer:
    """最小耗时计时器（毫秒）。"""

    def __init__(self) -> None:
        import time

        self._start = time.monotonic()

    def elapsed_ms(self) -> int:
        import time

        return int((time.monotonic() - self._start) * 1000)


def _budget_session() -> Any:
    """预算汇总用的独立会话；无应用上下文时返回 None（预算门放行）。"""
    from flask import has_app_context

    if not has_app_context():
        return None
    from fde_api.extensions import db

    return db.session()


def _audit(
    request_id: str,
    actor_id: str | None,
    purpose: str,
    *,
    model: str,
    used_fallback: bool,
    duration_ms: int,
    usage: dict[str, int] | None,
    status: str,
    error_code: str | None,
    prompt_version: str | None = None,
    prompt_fingerprint: str | None = None,
) -> None:
    """E7 审计入口；只传元数据，绝不携带密钥或消息内容。"""
    try:
        from fde_api.ai.auditing import record_audit

        record_audit(
            request_id=request_id,
            actor_id=actor_id,
            purpose=purpose,
            model=model,
            used_fallback=used_fallback,
            duration_ms=duration_ms,
            input_tokens=(usage or {}).get("input"),
            output_tokens=(usage or {}).get("output"),
            status=status,
            error_code=error_code,
            prompt_version=prompt_version,
            prompt_fingerprint=prompt_fingerprint,
        )
    except Exception:  # noqa: BLE001 - 审计失败不阻塞业务
        logger.warning("AI audit dispatch failed request_id=%s", request_id, exc_info=True)


class DeepSeekClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: SecretStr | str | None,
        model: str,
        timeout_seconds: int,
        session: Any | None = None,
        sleep: Any | None = None,
        fallback_model: str | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        # E5 降级链第一级：主模型不可用时切备用模型（SOP：主模型 → 备用模型
        # → 规则引擎 → 转人工）。备用模型同样失败时抛 ai_manual_handoff，
        # 由调用方进入明确的人工处理状态，不空转。
        self._fallback_model = fallback_model or None
        self._timeout_seconds = timeout_seconds
        self._session = session or requests.Session()
        self._sleep = sleep or time.sleep

    def complete_json(
        self,
        *,
        messages: list[dict[str, str]],
        request_id: str,
        max_tokens: int = 8192,
        on_event: Callable[[dict[str, str]], None] | None = None,
        deep_thinking: bool | None = None,
        purpose: str,
        prompt_version: str | None = None,
    ) -> dict[str, Any]:
        from flask import current_app, has_app_context

        # N2 仪表化（G-09）：指纹＝指令源文本 sha256（模板身份），正文不入库。
        from fde_api.ai.auditing import compute_prompt_fingerprint

        fingerprint = compute_prompt_fingerprint(messages=messages)

        # E7 预算门：月度 token 预算用尽时拒绝调用，且不发起任何供应商请求。
        # 预算设施自身故障时放行（fail-open），不阻塞业务。
        actor_id: str | None = None
        try:
            from fde_api.ai.auditing import budget_exceeded, current_actor_id

            actor_id = current_actor_id()
            budget = 0
            if has_app_context():
                budget = int(current_app.config["SETTINGS"].ai_monthly_token_budget or 0)
            if budget_exceeded(_budget_session(), actor_id, budget):
                _audit(
                    request_id,
                    actor_id,
                    purpose,
                    model=self._model,
                    used_fallback=False,
                    duration_ms=0,
                    usage=None,
                    status="budget_blocked",
                    error_code="ai_budget_exceeded",
                    prompt_version=prompt_version,
                    prompt_fingerprint=fingerprint,
                )
                raise DeepSeekError(
                    "ai_budget_exceeded",
                    "本月 AI 用量已达预算上限，请联系管理员调整或下月再试。",
                    retryable=False,
                )
        except DeepSeekError:
            raise
        except Exception:  # noqa: BLE001 - 预算/审计设施故障不阻塞业务
            logger.warning("AI budget gate failed open request_id=%s", request_id, exc_info=True)

        if has_app_context() and current_app.config["SETTINGS"].dsh_enabled:
            from fde_api.control.ai_server_client import structured_completion
            from fde_api.control.dsh_runtime import DSHRuntimeError
            try:
                return structured_completion(messages=messages, model=self._model, base_url=self._base_url,
                    api_key=self._api_key, max_tokens=max_tokens, on_event=on_event, deep_thinking=deep_thinking,
                    purpose=purpose, prompt_version=prompt_version)
            except DSHRuntimeError as error:
                raise DeepSeekError(error.code, error.public_message, retryable=error.retryable) from error
        timer = _Timer()
        try:
            result = self._complete_json_with_model(
                model=self._model,
                messages=messages,
                request_id=request_id,
                max_tokens=max_tokens,
                on_event=on_event,
                deep_thinking=deep_thinking,
            )
        except DeepSeekError as error:
            if not self._fallback_model or self._fallback_model == self._model or not error.retryable:
                _audit(
                    request_id, actor_id, purpose,
                    model=self._model, used_fallback=False,
                    duration_ms=timer.elapsed_ms(),
                    usage=getattr(self, "_last_usage", None),
                    status="failed", error_code=error.code,
                    prompt_version=prompt_version,
                    prompt_fingerprint=fingerprint,
                )
                raise
            # 主模型失败 → 备用模型（只对瞬时故障降级；配置/认证错误不降级）
            logger.warning(
                "DeepSeek primary model failed, falling back request_id=%s primary=%s fallback=%s code=%s",
                request_id,
                self._model,
                self._fallback_model,
                error.code,
            )
            try:
                result = self._complete_json_with_model(
                    model=self._fallback_model,
                    messages=messages,
                    request_id=f"{request_id}-fallback",
                    max_tokens=max_tokens,
                    on_event=on_event,
                    deep_thinking=deep_thinking,
                )
            except DeepSeekError as fallback_error:
                # 备用也失败 → 转人工（明确的人工处理状态，不是无限重试）
                _audit(
                    request_id, actor_id, purpose,
                    model=self._fallback_model, used_fallback=True,
                    duration_ms=timer.elapsed_ms(),
                    usage=getattr(self, "_last_usage", None),
                    status="failed", error_code=fallback_error.code,
                    prompt_version=prompt_version,
                    prompt_fingerprint=fingerprint,
                )
                raise DeepSeekError(
                    "ai_manual_handoff",
                    "AI 服务主备模型均不可用，已转人工处理；请稍后在控制台查看。",
                    retryable=False,
                ) from fallback_error
            _audit(
                request_id, actor_id, purpose,
                model=self._fallback_model, used_fallback=True,
                duration_ms=timer.elapsed_ms(),
                usage=getattr(self, "_last_usage", None),
                status="succeeded", error_code=None,
                prompt_version=prompt_version,
                prompt_fingerprint=fingerprint,
            )
            return result
        _audit(
            request_id, actor_id, purpose,
            model=self._model, used_fallback=False,
            duration_ms=timer.elapsed_ms(),
            usage=getattr(self, "_last_usage", None),
            status="succeeded", error_code=None,
            prompt_version=prompt_version,
            prompt_fingerprint=fingerprint,
        )
        return result

    def _complete_json_with_model(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        request_id: str,
        max_tokens: int,
        on_event: Callable[[dict[str, str]], None] | None = None,
        deep_thinking: bool | None = None,
    ) -> dict[str, Any]:
        # E7：每次尝试重置用量（主备模型各自的 usage 不串）
        self._last_usage: dict[str, int] | None = None
        api_key = self._secret_value()
        if not api_key:
            raise DeepSeekError(
                "ai_service_not_configured",
                "AI 服务尚未配置，请联系管理员。",
                retryable=False,
            )
        response = self._post_with_connection_retry(
            api_key=api_key,
            model=model,
            messages=messages,
            request_id=request_id,
            max_tokens=max_tokens,
            stream=on_event is not None,
        )
        logger.info(
            "DeepSeek request completed request_id=%s status=%s model=%s",
            request_id,
            response.status_code,
            model,
        )

        if response.status_code in {401, 403}:
            raise DeepSeekError(
                "ai_authentication_failed",
                "AI 服务认证失败，请检查服务端配置。",
                retryable=False,
            )
        if response.status_code == 429:
            raise DeepSeekError(
                "ai_rate_limited", "请求过于频繁，请稍后重试。", retryable=True
            )
        if response.status_code >= 400:
            logger.warning(
                "DeepSeek service error request_id=%s status=%s model=%s",
                request_id,
                response.status_code,
                model,
            )
            raise DeepSeekError(
                "ai_service_unavailable",
                "AI 服务暂时不可用，请稍后重试。",
                retryable=True,
            )

        try:
            if on_event is not None:
                content = self._read_stream(response, on_event)
                self._last_usage = _usage_from_stream(response)
            else:
                payload = response.json()
                content = payload["choices"][0]["message"]["content"]
                self._last_usage = _usage_from_payload(payload)
        except (KeyError, IndexError, TypeError, ValueError) as error:
            logger.warning(
                "DeepSeek empty response request_id=%s error_type=%s",
                request_id,
                type(error).__name__,
            )
            raise DeepSeekError(
                "ai_empty_response", "AI 未返回有效内容，请重试。", retryable=True
            ) from error
        if not isinstance(content, str) or not content.strip():
            raise DeepSeekError(
                "ai_empty_response", "AI 未返回有效内容，请重试。", retryable=True
            )
        try:
            parsed = _parse_json_object(content)
        except json.JSONDecodeError as error:
            logger.warning(
                "DeepSeek invalid JSON request_id=%s line=%s column=%s",
                request_id,
                error.lineno,
                error.colno,
            )
            raise DeepSeekError(
                "ai_output_invalid",
                "AI 返回内容格式不正确，请重试。",
                retryable=True,
            ) from error
        if not isinstance(parsed, dict):
            raise DeepSeekError(
                "ai_output_invalid",
                "AI 返回内容格式不正确，请重试。",
                retryable=True,
            )
        return parsed

    @staticmethod
    def _read_stream(
        response: Any,
        on_event: Callable[[dict[str, str]], None],
    ) -> str:
        content_parts: list[str] = []
        for raw_line in response.iter_lines(decode_unicode=False):
            if not raw_line:
                continue
            line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
            if not isinstance(line, str) or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                delta = json.loads(data)["choices"][0]["delta"]
            except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                continue
            reasoning = delta.get("reasoning_content")
            if isinstance(reasoning, str) and reasoning:
                on_event({"type": "reasoning_delta", "text": reasoning})
            content = delta.get("content")
            if isinstance(content, str) and content:
                content_parts.append(content)
                on_event({"type": "content_delta", "text": content})
        return "".join(content_parts)

    def _post_with_connection_retry(
        self,
        *,
        api_key: str,
        model: str,
        messages: list[dict[str, str]],
        request_id: str,
        max_tokens: int,
        stream: bool = False,
    ) -> Any:
        request_kwargs = {
            "headers": {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "X-Request-ID": request_id,
            },
            "json": {
                "model": model,
                "messages": messages,
                "response_format": {"type": "json_object"},
                "max_tokens": max_tokens,
                "stream": stream,
            },
            "timeout": self._timeout_seconds,
            "stream": stream,
        }
        retry_delays = (1.0, 3.0)
        for attempt in range(3):
            try:
                response = self._session.post(
                    f"{self._base_url}/chat/completions", **request_kwargs
                )
            except requests.Timeout as error:
                # E6 超时退避：超时是可重试的瞬时故障，按有界指数退避重试，
                # 而不是第一次就抛给用户。
                logger.warning(
                    "DeepSeek request timed out request_id=%s attempt=%s error_type=%s",
                    request_id,
                    attempt + 1,
                    type(error).__name__,
                )
                if attempt < len(retry_delays):
                    self._sleep(retry_delays[attempt])
                    continue
                raise DeepSeekError(
                    "ai_timeout", "AI 请求超时，请稍后重试。", retryable=True
                ) from error
            except requests.ConnectionError as error:
                logger.warning(
                    "DeepSeek connection failed request_id=%s attempt=%s error_type=%s",
                    request_id,
                    attempt + 1,
                    type(error).__name__,
                )
                if attempt < len(retry_delays):
                    self._sleep(retry_delays[attempt])
                    continue
                raise DeepSeekError(
                    "ai_service_unavailable",
                    "暂时无法连接 AI 服务，请稍后重试。",
                    retryable=True,
                ) from error
            except requests.RequestException as error:
                logger.warning(
                    "DeepSeek request failed request_id=%s error_type=%s",
                    request_id,
                    type(error).__name__,
                )
                raise DeepSeekError(
                    "ai_service_unavailable",
                    "暂时无法连接 AI 服务，请稍后重试。",
                    retryable=True,
                ) from error
            # E6 429 退避：按供应商语义读 Retry-After（秒），无该头时用有界
            # 指数退避；401/403 等配置错误不重试（由调用方按状态码处理）。
            if response.status_code == 429 and attempt < len(retry_delays):
                delay = self._retry_after_seconds(response) or retry_delays[attempt]
                logger.warning(
                    "DeepSeek rate limited request_id=%s attempt=%s delay=%s",
                    request_id,
                    attempt + 1,
                    delay,
                )
                self._sleep(delay)
                continue
            return response

    def _retry_after_seconds(self, response: Any) -> float | None:
        """读 Retry-After（秒数形式）；非法或缺失时返回 None。"""
        headers = getattr(response, "headers", None) or {}
        raw = headers.get("Retry-After") or headers.get("retry-after")
        if raw is None:
            return None
        try:
            value = float(str(raw).strip())
        except (TypeError, ValueError):
            return None
        if value < 0:
            return None
        # 上限 30s：供应商给的超长等待不该把请求线程钉住。
        return min(value, 30.0)

    def _secret_value(self) -> str | None:
        if isinstance(self._api_key, SecretStr):
            return self._api_key.get_secret_value()
        return self._api_key


def _parse_json_object(content: str) -> dict[str, Any]:
    """Parse JSON mode output while tolerating harmless Markdown fences."""
    candidate = content.strip()
    if candidate.startswith("```") and candidate.endswith("```"):
        first_newline = candidate.find("\n")
        if first_newline >= 0:
            candidate = candidate[first_newline + 1 : -3].strip()
    parsed = json.loads(candidate)
    if not isinstance(parsed, dict):
        raise json.JSONDecodeError("AI response must be a JSON object", candidate, 0)
    return parsed


def _usage_from_payload(payload: Any) -> dict[str, int] | None:
    """从非流式响应体取 token 用量；缺失或非整数时不记录。"""
    try:
        usage = payload["usage"]
        input_tokens = int(usage["prompt_tokens"])
        output_tokens = int(usage["completion_tokens"])
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    return {"input": input_tokens, "output": output_tokens}


def _usage_from_stream(response: Any) -> dict[str, int] | None:
    """流式响应的用量挂在末端 chunk 的 usage 字段（OpenAI 兼容）。"""
    try:
        usage = response.json().get("usage")
        input_tokens = int(usage["prompt_tokens"])
        output_tokens = int(usage["completion_tokens"])
    except (AttributeError, KeyError, TypeError, ValueError):
        return None
    return {"input": input_tokens, "output": output_tokens}
