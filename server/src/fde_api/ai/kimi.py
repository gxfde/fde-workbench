"""Kimi client for native document extraction followed by structured analysis."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, BinaryIO, Callable

import requests
from pydantic import SecretStr

logger = logging.getLogger(__name__)


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
        local_extract: bool = False,
        openai_compatible: bool = False,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._session = session or requests.Session()
        # local_extract=True：不走供应商的 /files 上传接口，改为本地解析 DOCX
        # 取文本后再交给 chat/completions。
        # MiniMax 官方 purpose 枚举中没有 file-extract（只有 voice_clone /
        # prompt_audio / t2a_async_input / video_understanding /
        # video_generation_input），所以它无法替代 Kimi 的文件解析能力，
        # 必须走本地提取这条路。
        self._local_extract = local_extract
        # openai_compatible=True：按通用 OpenAI 兼容端点发请求——用 max_tokens
        # 而非 max_completion_tokens，且不下发 reasoning_effort（那是 Kimi K3
        # 的专有参数，MiniMax 用 thinking 开关控制推理强度）。
        self._openai_compatible = openai_compatible

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
        # CR-006 统一预算门：kimi 此前全路径零预算零审计（goal-c 取证 E0）。
        # DSH 腿经 structured_completion → execute_ai_prompt 已统一闸+账；此处
        # 门守本地直连腿入口（含文件上传花费），审计见 _write_local_audit。
        self._enforce_monthly_budget(request_id=request_id)
        headers = {"Authorization": f"Bearer {api_key}", "X-Request-ID": request_id}
        file_id = ""
        try:
            if self._local_extract:
                file_content = self._extract_docx_locally(stream, filename)
            else:
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

            completion_payload: dict[str, Any] = {
                "model": self._model,
                "messages": build_messages(file_content),
                "response_format": {"type": "json_object"},
                "stream": True,
            }
            if self._openai_compatible:
                # 通用 OpenAI 兼容端点（MiniMax 等）：用 max_tokens，不发
                # reasoning_effort（那是 Kimi K3 专有参数，MiniMax 侧不识别）。
                completion_payload["max_tokens"] = 32768
            else:
                # Kimi K3 always reasons before returning the final answer. Keep
                # extraction-oriented jobs on low effort and leave enough room
                # for both its reasoning tokens and the structured JSON result.
                completion_payload["reasoning_effort"] = "low"
                completion_payload["max_completion_tokens"] = 32768

            leg_started = time.monotonic()
            completion = self._request(
                "post",
                f"{self._base_url}/chat/completions",
                headers={**headers, "Content-Type": "application/json"},
                json=completion_payload,
                stream=True,
            )
            try:
                content = self._read_streamed_content(completion, on_event=on_event)
                if not content.strip():
                    raise KimiError("ai_empty_response", "AI 未返回有效分析结果，请重试。", retryable=True)
                try:
                    parsed = json.loads(content)
                except json.JSONDecodeError as error:
                    raise KimiError("ai_output_invalid", "AI 返回的项目指引格式不正确，请重试。", retryable=True) from error
                if not isinstance(parsed, dict):
                    raise KimiError("ai_output_invalid", "AI 返回的项目指引格式不正确，请重试。", retryable=True)
            except Exception as error:  # noqa: BLE001 - 失败也记账（CR-006），原样上抛
                self._write_local_audit(
                    request_id=request_id, status="failed",
                    error_code=str(getattr(error, "code", "") or "ai_unavailable"),
                    duration_ms=int((time.monotonic() - leg_started) * 1000),
                )
                raise
            # 流式响应不回传 usage：token 记 None（账本记元数据，预算按可测
            # 口径汇总，不发明数字）——DSH 主路径有 provider_usage 精确入账。
            self._write_local_audit(
                request_id=request_id, status="succeeded", error_code=None,
                duration_ms=int((time.monotonic() - leg_started) * 1000),
            )
            return parsed
        finally:
            if file_id:
                try:
                    self._session.delete(f"{self._base_url}/files/{file_id}", headers=headers, timeout=15)
                except requests.RequestException:
                    pass

    def _enforce_monthly_budget(self, *, request_id: str) -> None:
        """CR-006 本地直连腿预算门（E7 统一口径）：超限先留痕再拒（retryable=False）。

        actor 取请求上下文当前用户；后台任务等无请求上下文场景 actor=None →
        放行（kimi 无显式 actor 参数，后台腿的限流缺口如实保留，账本仍记
        元数据）。预算设施故障 fail-open，不阻塞业务。
        """
        from flask import current_app, has_app_context

        if not has_app_context():
            return
        actor_id: str | None = None
        blocked = False
        try:
            from fde_api.ai.auditing import budget_exceeded, current_actor_id
            from fde_api.extensions import db

            actor_id = current_actor_id()
            budget = int(current_app.config["SETTINGS"].ai_monthly_token_budget or 0)
            with db.session() as session:
                blocked = budget_exceeded(session, actor_id, budget)
        except Exception:  # noqa: BLE001 - 预算设施故障不阻塞业务（fail-open）
            logger.warning("kimi budget gate failed open request_id=%s", request_id, exc_info=True)
            return
        if blocked:
            from fde_api.ai.auditing import audit_budget_blocked

            audit_budget_blocked(request_id=request_id, actor_id=actor_id,
                                 purpose="kimi_docx", model=self._model)
            raise KimiError("ai_budget_exceeded", "本月 AI 用量已达预算上限，请联系管理员调整或下月再试。", retryable=False)

    def _write_local_audit(self, *, request_id: str, status: str, error_code: str | None, duration_ms: int) -> None:
        """本地直连腿记账（CR-006）：kimi 此前零审计；尽力而为不打断业务。"""
        try:
            from fde_api.ai.auditing import current_actor_id, record_audit

            record_audit(
                request_id=request_id,
                actor_id=current_actor_id(),
                purpose="kimi_docx",
                model=self._model,
                used_fallback=False,
                duration_ms=int(duration_ms),
                input_tokens=None,
                output_tokens=None,
                status=status,
                error_code=error_code[:60] if error_code else None,
            )
        except Exception:  # noqa: BLE001 - 审计失败不阻塞业务
            logger.warning("kimi local audit dispatch failed request_id=%s", request_id, exc_info=True)

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
    def _extract_docx_locally(stream: BinaryIO, filename: str) -> str:
        """本地解析 DOCX 取全文（复用文档 QA 的提取实现，含表格/页眉页脚）。

        供应商不提供 file-extract 接口时走这条路：文件不出本机，只把提取出的
        文本交给对话模型。

        本地解析是字节的纯函数：同一份文件每次都得到同样的结果，所以解析
        失败（文件损坏/无有效文字）不可重试——重试只是把同一个错误再算一遍。
        供应商侧的提取失败是另一回事（见 analyze_docx_json），那是瞬时故障。
        存储读取本身出错（OSError）仍然是瞬时的，保持可重试。
        """
        from fde_api.documents.qa import extract_docx_xml_text
        try:
            content = extract_docx_xml_text(stream)
        except OSError as error:  # 存储读取抖动：瞬时故障，可重试
            raise KimiError(
                "kimi_file_extract_failed",
                f"AI 未能读取该 DOCX 文件（{filename}），请稍后重试。",
                retryable=True,
            ) from error
        except Exception as error:  # noqa: BLE001 - 解析失败是确定性故障，不可重试
            raise KimiError(
                "kimi_file_extract_failed",
                f"AI 未能解析该 DOCX 文件（{filename}），请检查文件后重试。",
                retryable=False,
            ) from error
        if not isinstance(content, str) or not content.strip():
            raise KimiError("kimi_file_extract_failed", "AI 未能从 DOCX 中提取有效内容，请检查文件后重试。", retryable=False)
        return content

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
