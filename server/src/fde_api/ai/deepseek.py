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
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
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
    ) -> dict[str, Any]:
        from flask import current_app, has_app_context
        if has_app_context() and current_app.config["SETTINGS"].dsh_enabled:
            from fde_api.control.ai_server_client import structured_completion
            from fde_api.control.dsh_runtime import DSHRuntimeError
            try:
                return structured_completion(messages=messages, model=self._model, base_url=self._base_url,
                    api_key=self._api_key, max_tokens=max_tokens, on_event=on_event, deep_thinking=deep_thinking)
            except DSHRuntimeError as error:
                raise DeepSeekError(error.code, error.public_message, retryable=error.retryable) from error
        api_key = self._secret_value()
        if not api_key:
            raise DeepSeekError(
                "ai_service_not_configured",
                "AI 服务尚未配置，请联系管理员。",
                retryable=False,
            )
        response = self._post_with_connection_retry(
            api_key=api_key,
            messages=messages,
            request_id=request_id,
            max_tokens=max_tokens,
            stream=on_event is not None,
        )
        logger.info(
            "DeepSeek request completed request_id=%s status=%s model=%s",
            request_id,
            response.status_code,
            self._model,
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
                self._model,
            )
            raise DeepSeekError(
                "ai_service_unavailable",
                "AI 服务暂时不可用，请稍后重试。",
                retryable=True,
            )

        try:
            if on_event is not None:
                content = self._read_stream(response, on_event)
            else:
                payload = response.json()
                content = payload["choices"][0]["message"]["content"]
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
                "model": self._model,
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
                return self._session.post(
                    f"{self._base_url}/chat/completions", **request_kwargs
                )
            except requests.Timeout as error:
                logger.warning(
                    "DeepSeek request timed out request_id=%s error_type=%s",
                    request_id,
                    type(error).__name__,
                )
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
        raise AssertionError("unreachable")

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
