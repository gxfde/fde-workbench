from __future__ import annotations

import pytest
import requests

from fde_api.control.dsh_runtime import DSHRuntimeClient, DSHRuntimeError, DSHRuntimePool


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self.payload = payload

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if self.error:
            raise self.error
        return self.response


def make_client(session, *, enabled=True, token="service-secret"):
    return DSHRuntimeClient(
        enabled=enabled,
        base_url="http://dsh.internal:8020",
        service_token=token,
        runtime_version="1.4.2",
        protocol_version="fde-dsh-v1",
        timeout_seconds=60,
        session=session,
    )


def test_execution_contract_pins_runtime_scope_tools_and_idempotency():
    session = FakeSession(FakeResponse(200, {
        "execution_id": "dsh-123",
        "status": "succeeded",
        "summary": "done",
        "output": {"task_id": "task-1"},
        "runtime_version": "1.4.2",
    }))

    result = make_client(session).execute(
        execution_id="run-1",
        idempotency_key="automation:run-1",
        actor_user_id="user-1",
        project_id="project-1",
        prompt="Summarize the project",
        allowed_tools=["project.read", "project.summarize"],
        context_refs=[{"kind": "project", "id": "project-1"}],
        agent_profile="fde-reader",
    )

    assert result.status == "succeeded"
    assert result.output == {"task_id": "task-1"}
    method, url, call = session.calls[0]
    assert (method, url) == ("POST", "http://dsh.internal:8020/v1/executions")
    assert call["headers"]["Authorization"] == "Bearer service-secret"
    assert call["headers"]["Idempotency-Key"] == "automation:run-1"
    assert call["json"]["runtime_version"] == "1.4.2"
    assert call["json"]["scope"] == {"project_id": "project-1"}
    assert call["json"]["allowed_tools"] == ["project.read", "project.summarize"]


def test_disabled_runtime_never_touches_the_network():
    session = FakeSession(FakeResponse(200, {}))
    with pytest.raises(DSHRuntimeError, match="DSH 服务尚未启用") as caught:
        make_client(session, enabled=False).health()
    assert caught.value.code == "dsh_not_enabled"
    assert session.calls == []


@pytest.mark.parametrize(
    ("status_code", "code", "retryable"),
    [(401, "dsh_authentication_failed", False), (429, "dsh_rate_limited", True), (503, "dsh_unavailable", True)],
)
def test_service_errors_do_not_leak_provider_payload(status_code, code, retryable):
    session = FakeSession(FakeResponse(status_code, {"private": "do-not-leak"}))
    with pytest.raises(DSHRuntimeError) as caught:
        make_client(session).health()
    assert caught.value.code == code
    assert caught.value.retryable is retryable
    assert "do-not-leak" not in caught.value.public_message


def test_invalid_or_timed_out_responses_have_stable_errors():
    invalid = FakeSession(FakeResponse(200, {"status": "unknown", "execution_id": "dsh-1"}))
    with pytest.raises(DSHRuntimeError) as caught:
        make_client(invalid).execute(
            execution_id="run-1",
            idempotency_key="run-1",
            actor_user_id="user-1",
            project_id=None,
            prompt="test",
            allowed_tools=[],
            context_refs=[],
            agent_profile="fde-reader",
        )
    assert caught.value.code == "dsh_response_invalid"

    timed_out = FakeSession(error=requests.Timeout("private timeout"))
    with pytest.raises(DSHRuntimeError) as timeout:
        make_client(timed_out).health()
    assert timeout.value.code == "dsh_timeout"
    assert "private timeout" not in timeout.value.public_message
