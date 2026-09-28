"""Kimi client for native document extraction followed by structured analysis."""

from __future__ import annotations

import json
from typing import Any, BinaryIO, Callable

import requests
from pydantic import SecretStr


class KimiError(Exception):
    def __init__(self, code: str, public_message: str, *, retryable: bool):
        super().__init__(public_message)
        self.code = code
        self.public_message = public_message
        self.retryable = retryable


class KimiFileClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: SecretStr | str | None,
        model: str,
        timeout_seconds: int,
        session: Any | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._session = session or requests.Session()

    def analyze_docx_json(
        self,
        *,
        stream: BinaryIO,
        filename: str,
        request_id: str,
        build_messages: Any,
        on_event: Callable[[dict[str, str]], None] | None = None,
    ) -> dict[str, Any]:
        api_key = self._secret_value()
        if not api_key:
            raise KimiError("ai_service_not_configured", "AI 服务尚未配置，请联系管理员。", retryable=False)
        headers = {"Authorization": f"Bearer {api_key}", "X-Request-ID": request_id}
        file_id = ""
        try:
            upload = self._request(
                "post",
                f"{self._base_url}/files",
                headers=headers,
                files={"file": (filename, stream, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
                data={"purpose": "file-extract"},
            )
            upload_payload = self._json(upload, "kimi_file_upload_failed", "AI 无法接收该 DOCX 文件，请稍后重试。")
            file_id = upload_payload.get("id", "") if isinstance(upload_payload, dict) else ""
            if not file_id or upload_payload.get("status") not in {None, "ready", "ok"}:
                raise KimiError("kimi_file_upload_failed", "AI 无法接收该 DOCX 文件，请稍后重试。", retryable=True)

            content_response = self._request("get", f"{self._base_url}/files/{file_id}/content", headers=headers)
            file_content = self._utf8_text(content_response)
            if not isinstance(file_content, str) or not file_content.strip():
                raise KimiError("kimi_file_extract_failed", "AI 未能从 DOCX 中提取有效内容，请检查文件后重试。", retryable=True)

            from flask import current_app, has_app_context
            if has_app_context() and current_app.config["SETTINGS"].dsh_enabled:
                from fde_api.control.ai_server_client import structured_completion
                from fde_api.control.dsh_runtime import DSHRuntimeError
                try:
                    return structured_completion(messages=build_messages(file_content), model=self._model,
                        base_url=self._base_url, api_key=self._api_key, max_tokens=32768, on_event=on_event)
                except DSHRuntimeError as error:
                    raise KimiError(error.code, error.public_message, retryable=error.retryable) from error

            completion = self._request(
                "post",
                f"{self._base_url}/chat/completions",
                headers={**headers, "Content-Type": "application/json"},
                json={
                    "model": self._model,
                    "messages": build_messages(file_content),
                    "response_format": {"type": "json_object"},
                    # Kimi K3 always reasons before returning the final answer. Keep
                    # extraction-oriented jobs on low effort and leave enough room
                    # for both its reasoning tokens and the structured JSON result.
                    "reasoning_effort": "low",
                    "max_completion_tokens": 32768,
                    "stream": True,
                },
                stream=True,
            )
            content = self._read_streamed_content(completion, on_event=on_event)
            if not content.strip():
                raise KimiError("ai_empty_response", "AI 未返回有效分析结果，请重试。", retryable=True)
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError as error:
                raise KimiError("ai_output_invalid", "AI 返回的项目指引格式不正确，请重试。", retryable=True) from error
            if not isinstance(parsed, dict):
                raise KimiError("ai_output_invalid", "AI 返回的项目指引格式不正确，请重试。", retryable=True)
            return parsed
        finally:
            if file_id:
                try:
                    self._session.delete(f"{self._base_url}/files/{file_id}", headers=headers, timeout=15)
                except requests.RequestException:
                    pass

    def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        kwargs["timeout"] = self._timeout_seconds
        try:
            response = getattr(self._session, method)(url, **kwargs)
        except requests.Timeout as error:
            raise KimiError("ai_timeout", "AI 分析超时，请稍后重试。", retryable=True) from error
        except requests.RequestException as error:
            raise KimiError("ai_service_unavailable", "暂时无法连接 AI 服务，请稍后重试。", retryable=True) from error
        if response.status_code in {401, 403}:
            raise KimiError("ai_authentication_failed", "AI 服务认证失败，请检查服务端配置。", retryable=False)
        if response.status_code == 429:
            raise KimiError("ai_rate_limited", "AI 请求过于频繁，请稍后重试。", retryable=True)
        if response.status_code >= 400:
            raise KimiError("ai_service_unavailable", "AI 服务暂时不可用，请稍后重试。", retryable=True)
        return response

    @staticmethod
    def _json(response: Any, code: str, message: str) -> Any:
        try:
            return response.json()
        except (TypeError, ValueError) as error:
            raise KimiError(code, message, retryable=True) from error

    @staticmethod
    def _read_streamed_content(response: Any, on_event: Callable[[dict[str, str]], None] | None = None) -> str:
        parts: list[str] = []
        try:
            # Kimi's SSE response may not carry an explicit charset. Requests
            # otherwise falls back to ISO-8859-1 and turns Chinese into mojibake.
            for raw_line in response.iter_lines(decode_unicode=False):
                if not raw_line:
                    continue
                line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    payload = json.loads(data)
                    delta = payload["choices"][0]["delta"]
                    value = delta.get("content")
                except (json.JSONDecodeError, KeyError, IndexError, TypeError, AttributeError):
                    continue
                if isinstance(value, str):
                    parts.append(value)
                    if on_event is not None:
                        on_event({"type": "content_delta", "text": value})
                reasoning = delta.get("reasoning_content")
                if isinstance(reasoning, str) and reasoning and on_event is not None:
                    on_event({"type": "reasoning_delta", "text": reasoning})
        except requests.Timeout as error:
            raise KimiError("ai_timeout", "AI 分析超时，请稍后重试。", retryable=True) from error
        except requests.RequestException as error:
            raise KimiError("ai_service_unavailable", "暂时无法连接 AI 服务，请稍后重试。", retryable=True) from error
        return "".join(parts)

    @staticmethod
    def _utf8_text(response: Any) -> str:
        raw = getattr(response, "content", None)
        if isinstance(raw, bytes):
            try:
                return raw.decode("utf-8")
            except UnicodeDecodeError as error:
                raise KimiError(
                    "kimi_file_extract_failed",
                    "AI 返回的 DOCX 解析内容编码异常，请稍后重试。",
                    retryable=True,
                ) from error
        text = getattr(response, "text", "")
        return text if isinstance(text, str) else ""

    def _secret_value(self) -> str | None:
        if isinstance(self._api_key, SecretStr):
            return self._api_key.get_secret_value()
        return self._api_key
