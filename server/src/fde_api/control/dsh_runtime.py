"""Versioned client for the separately deployed DeepSeek Harness adapter."""

from __future__ import annotations

import logging
from hmac import compare_digest
from dataclasses import dataclass
from typing import Any

import requests
from flask import Flask, current_app
from pydantic import SecretStr

from fde_api.config import Settings


logger = logging.getLogger(__name__)
TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled"})
VALID_STATUSES = TERMINAL_STATUSES | {"accepted", "running", "waiting_approval"}


class DSHRuntimeError(Exception):
    def __init__(self, code: str, public_message: str, *, retryable: bool):
        super().__init__(public_message)
        self.code = code
        self.public_message = public_message
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class DSHExecutionResult:
    external_execution_id: str
    status: str
    summary: str
    output: dict[str, Any]
    runtime_version: str


class DSHRuntimeClient:
    """Keep FDE's control-plane contract stable while DSH itself is upgraded."""

    def __init__(
        self,
        *,
        enabled: bool,
        base_url: str,
        service_token: SecretStr | str | None,
        runtime_version: str,
        protocol_version: str,
        timeout_seconds: int,
        session: Any | None = None,
    ) -> None:
        self.enabled = enabled
        self.base_url = base_url.rstrip("/")
        self.service_token = service_token
        self.runtime_version = runtime_version
        self.protocol_version = protocol_version
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()

    def health(self) -> dict[str, Any]:
        response = self._request("GET", "/v1/health", timeout=min(self.timeout_seconds, 10))
        payload = self._json_object(response)
        if response.status_code >= 400:
            raise self._service_error(response.status_code)
        return {
            "status": payload.get("status", "unknown"),
            "runtime_version": payload.get("runtime_version", ""),
            "protocol_version": payload.get("protocol_version", ""),
        }

    def verify_service_token(self, candidate: str | None) -> bool:
        expected = self._token()
        return bool(expected and candidate and compare_digest(expected, candidate))

    def execute(
        self,
        *,
        execution_id: str,
        idempotency_key: str,
        actor_user_id: str,
        project_id: str | None,
        prompt: str,
        allowed_tools: list[str],
        context_refs: list[dict[str, str]],
        agent_profile: str,
    ) -> DSHExecutionResult:
        response = self._request(
            "POST",
            "/v1/executions",
            headers={"Idempotency-Key": idempotency_key},
            json={
                "schema_version": self.protocol_version,
                "execution_id": execution_id,
                "actor": {"user_id": actor_user_id},
                "scope": {"project_id": project_id},
                "agent_profile": agent_profile,
                "runtime_version": self.runtime_version,
                "prompt": prompt,
                "allowed_tools": allowed_tools,
                "context_refs": context_refs,
            },
            timeout=self.timeout_seconds,
        )

        payload = self._json_object(response)
        if response.status_code >= 400:
            raise self._service_error(response.status_code)
        status = payload.get("status")
        external_id = payload.get("execution_id")
        output = payload.get("output", {})
        if status not in VALID_STATUSES or not isinstance(external_id, str) or not external_id:
            raise DSHRuntimeError("dsh_response_invalid", "DSH 返回了无效结果。", retryable=True)
        if not isinstance(output, dict):
            raise DSHRuntimeError("dsh_response_invalid", "DSH 返回了无效结果。", retryable=True)
        summary = payload.get("summary", "")
        if not isinstance(summary, str):
            summary = ""
        returned_version = payload.get("runtime_version", self.runtime_version)
        if not isinstance(returned_version, str):
            returned_version = self.runtime_version
        return DSHExecutionResult(external_id, status, summary, output, returned_version)

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        token = self._token()
        if not self.enabled:
            raise DSHRuntimeError("dsh_not_enabled", "DSH 服务尚未启用。", retryable=False)
        if not token:
            raise DSHRuntimeError("dsh_not_configured", "DSH 服务尚未配置。", retryable=False)
        headers = {
            "Authorization": f"Bearer {token}",
            "X-FDE-Protocol-Version": self.protocol_version,
            **kwargs.pop("headers", {}),
        }
        try:
            return self.session.request(method, f"{self.base_url}{path}", headers=headers, **kwargs)
        except requests.Timeout as error:
            raise DSHRuntimeError("dsh_timeout", "DSH 执行超时，请稍后重试。", retryable=True) from error
        except requests.RequestException as error:
            logger.warning("DSH request failed error_type=%s", type(error).__name__)
            raise DSHRuntimeError("dsh_unavailable", "暂时无法连接 DSH 服务。", retryable=True) from error

    @staticmethod
    def _json_object(response: Any) -> dict[str, Any]:
        try:
            payload = response.json()
        except (TypeError, ValueError) as error:
            raise DSHRuntimeError("dsh_response_invalid", "DSH 返回了无效结果。", retryable=True) from error
        if not isinstance(payload, dict):
            raise DSHRuntimeError("dsh_response_invalid", "DSH 返回了无效结果。", retryable=True)
        return payload

    @staticmethod
    def _service_error(status_code: int) -> DSHRuntimeError:
        if status_code in {401, 403}:
            return DSHRuntimeError("dsh_authentication_failed", "DSH 服务认证失败。", retryable=False)
        if status_code == 409:
            return DSHRuntimeError("dsh_execution_conflict", "DSH 任务状态冲突。", retryable=False)
        if status_code == 429:
            return DSHRuntimeError("dsh_rate_limited", "DSH 任务过多，请稍后重试。", retryable=True)
        return DSHRuntimeError("dsh_unavailable", "DSH 服务暂时不可用。", retryable=status_code >= 500)

    def _token(self) -> str | None:
        if isinstance(self.service_token, SecretStr):
            return self.service_token.get_secret_value()
        return self.service_token


class DSHRuntimePool:
    """Expose one active DSH runtime behind the stable control-plane contract."""

    def __init__(self, *, primary: DSHRuntimeClient) -> None:
        self.primary = primary

    @property
    def runtime_version(self) -> str:
        return self.primary.runtime_version

    @property
    def enabled(self) -> bool:
        return self.primary.enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self.primary.enabled = value

    @property
    def service_token(self) -> SecretStr | str | None:
        return self.primary.service_token

    @service_token.setter
    def service_token(self, value: SecretStr | str | None) -> None:
        self.primary.service_token = value

    def health(self) -> dict[str, Any]:
        return self.primary.health()

    def verify_service_token(self, candidate: str | None) -> bool:
        return self.primary.verify_service_token(candidate)

    def execute(self, *, execution_id: str, **kwargs: Any) -> DSHExecutionResult:
        from flask import has_app_context
        if has_app_context() and self.enabled:
            from fde_api.control.ai_server_client import execute_ai_prompt
            answer = execute_ai_prompt(user_id=kwargs["actor_user_id"], prompt=kwargs["prompt"],
                execution_id=execution_id, project_id=kwargs.get("project_id"),
                capabilities=kwargs.get("allowed_tools"))
            return DSHExecutionResult(execution_id, "succeeded", answer[:1000], {"text": answer}, self.runtime_version)
        return self.primary.execute(execution_id=execution_id, **kwargs)

    def selected_runtime_version(self, execution_id: str) -> str:
        return self.primary.runtime_version


class DSHRuntimeExtension:
    extension_key = "fde_api_dsh_runtime"

    def init_app(self, app: Flask, settings: Settings) -> None:
        primary = DSHRuntimeClient(
            enabled=settings.dsh_enabled,
            base_url=settings.dsh_base_url,
            service_token=settings.dsh_service_token,
            runtime_version=settings.dsh_runtime_version,
            protocol_version=settings.dsh_protocol_version,
            timeout_seconds=settings.dsh_timeout_seconds,
        )
        app.extensions[self.extension_key] = DSHRuntimePool(primary=primary)

    @property
    def current(self) -> DSHRuntimePool:
        return current_app.extensions[self.extension_key]


dsh_runtime = DSHRuntimeExtension()
