import json

import pytest
import requests

from fde_api.ai.deepseek import DeepSeekClient, DeepSeekError


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class StreamResponse(FakeResponse):
    def __init__(self, lines):
        super().__init__(200, {})
        self._lines = lines

    def iter_lines(self, decode_unicode=False):
        return iter(self._lines)


class FakeSession:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        return self.response


class SequencedSession:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def make_client(session, api_key="secret-value"):
    return DeepSeekClient(
        base_url="https://api.deepseek.example",
        api_key=api_key,
        model="deepseek-v4-pro",
        timeout_seconds=30,
        session=session,
        sleep=lambda _: None,
    )


def test_complete_json_parses_content_and_sets_json_mode():
    session = FakeSession(
        FakeResponse(
            200,
            {"choices": [{"message": {"content": json.dumps({"status": "ready"})}}]},
        )
    )

    result = make_client(session).complete_json(
        messages=[{"role": "user", "content": "hello"}], request_id="req-1"
    )

    assert result == {"status": "ready"}
    _, call = session.calls[0]
    assert call["json"]["response_format"] == {"type": "json_object"}
    assert call["headers"]["Authorization"] == "Bearer secret-value"
    assert call["headers"]["X-Request-ID"] == "req-1"


def test_complete_json_accepts_a_fenced_json_object():
    session = FakeSession(
        FakeResponse(
            200,
            {"choices": [{"message": {"content": "```json\n{\"status\": \"ready\"}\n```"}}]},
        )
    )

    result = make_client(session).complete_json(messages=[], request_id="req-fenced")

    assert result == {"status": "ready"}


def test_complete_json_streams_reasoning_and_content_before_parsing_result():
    response = StreamResponse([
        b'data: {"choices":[{"delta":{"reasoning_content":"checking context"}}]}',
        b'data: {"choices":[{"delta":{"content":"{\\"status\\":"}}]}',
        b'data: {"choices":[{"delta":{"content":"\\"ready\\"}"}}]}',
        b'data: [DONE]',
    ])
    session = FakeSession(response)
    events = []

    result = make_client(session).complete_json(
        messages=[{"role": "user", "content": "hello"}],
        request_id="req-stream",
        on_event=events.append,
    )

    assert result == {"status": "ready"}
    assert events == [
        {"type": "reasoning_delta", "text": "checking context"},
        {"type": "content_delta", "text": '{"status":'},
        {"type": "content_delta", "text": '"ready"}'},
    ]
    _, call = session.calls[0]
    assert call["json"]["stream"] is True
    assert call["stream"] is True


@pytest.mark.parametrize(
    ("status", "code", "retryable"),
    [
        (401, "ai_authentication_failed", False),
        (429, "ai_rate_limited", True),
        (500, "ai_service_unavailable", True),
    ],
)
def test_provider_errors_are_mapped_without_leaking_body(status, code, retryable):
    session = FakeSession(FakeResponse(status, {"error": {"message": "private provider detail"}}))

    with pytest.raises(DeepSeekError) as caught:
        make_client(session).complete_json(messages=[], request_id="req-2")

    assert caught.value.code == code
    assert caught.value.retryable is retryable
    assert "private provider detail" not in caught.value.public_message


def test_empty_or_invalid_content_is_a_stable_public_error():
    session = FakeSession(FakeResponse(200, {"choices": [{"message": {"content": ""}}]}))

    with pytest.raises(DeepSeekError) as caught:
        make_client(session).complete_json(messages=[], request_id="req-3")

    assert caught.value.code == "ai_empty_response"


def test_missing_key_is_rejected_before_network_call():
    session = FakeSession(FakeResponse(200, {}))

    with pytest.raises(DeepSeekError) as caught:
        make_client(session, api_key=None).complete_json(messages=[], request_id="req-4")

    assert caught.value.code == "ai_service_not_configured"
    assert session.calls == []


def test_transient_connection_error_is_retried_once():
    session = SequencedSession(
        [
            requests.ConnectionError("temporary disconnect"),
            FakeResponse(
                200,
                {"choices": [{"message": {"content": json.dumps({"ok": True})}}]},
            ),
        ]
    )

    result = make_client(session).complete_json(messages=[], request_id="req-retry")

    assert result == {"ok": True}
    assert len(session.calls) == 2


def test_connection_error_is_retried_with_a_strict_limit():
    session = SequencedSession(
        [
            requests.ConnectionError("first disconnect"),
            requests.ConnectionError("second disconnect"),
            requests.ConnectionError("third disconnect"),
        ]
    )

    with pytest.raises(DeepSeekError) as caught:
        make_client(session).complete_json(messages=[], request_id="req-retry-failed")

    assert caught.value.code == "ai_service_unavailable"
    assert len(session.calls) == 3
