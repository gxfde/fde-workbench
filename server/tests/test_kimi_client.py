import io
import json

import pytest
import requests

from fde_api.ai.kimi import KimiError, KimiFileClient


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text="", content=None, stream_lines=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.content = text.encode("utf-8") if content is None else content
        self._stream_lines = stream_lines or []

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload

    def iter_lines(self, decode_unicode=False):
        return iter(self._stream_lines)


class FakeSession:
    def __init__(self, *, upload=None, content=None, completion=None, error=None):
        self.upload = upload
        self.content = content
        self.completion = completion
        self.error = error
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append(("post", url, kwargs))
        if self.error:
            raise self.error
        return self.upload if url.endswith("/files") else self.completion

    def get(self, url, **kwargs):
        self.calls.append(("get", url, kwargs))
        return self.content

    def delete(self, url, **kwargs):
        self.calls.append(("delete", url, kwargs))
        return FakeResponse(payload={"deleted": True})


def make_client(session, api_key="secret"):
    return KimiFileClient(base_url="https://api.moonshot.example/v1", api_key=api_key, model="kimi-k3", timeout_seconds=30, session=session)


def test_uploads_docx_uses_kimi_content_and_cleans_up_file():
    result = {"customer_vision": "长期目标"}
    session = FakeSession(
        upload=FakeResponse(payload={"id": "file-1", "status": "ready"}),
        content=FakeResponse(text="Kimi 原生提取的文档内容"),
        completion=FakeResponse(stream_lines=[
            ("data: " + json.dumps({"choices": [{"delta": {"content": json.dumps(result, ensure_ascii=False)}}]}, ensure_ascii=False)).encode("utf-8"),
            b"data: [DONE]",
        ]),
    )
    messages_seen = []

    parsed = make_client(session).analyze_docx_json(
        stream=io.BytesIO(b"docx"), filename="预调研表.docx", request_id="job-1",
        build_messages=lambda content: messages_seen.append(content) or [{"role": "system", "content": content}],
    )

    assert parsed == result
    assert messages_seen == ["Kimi 原生提取的文档内容"]
    upload = session.calls[0]
    assert upload[2]["data"] == {"purpose": "file-extract"}
    assert upload[2]["files"]["file"][0] == "预调研表.docx"
    chat = next(call for call in session.calls if call[1].endswith("/chat/completions"))
    assert chat[2]["json"]["model"] == "kimi-k3"
    assert chat[2]["json"]["response_format"] == {"type": "json_object"}
    assert chat[2]["json"]["reasoning_effort"] == "low"
    assert chat[2]["json"]["max_completion_tokens"] == 32768
    assert chat[2]["json"]["stream"] is True
    assert chat[2]["stream"] is True
    assert "temperature" not in chat[2]["json"]
    assert session.calls[-1][0:2] == ("delete", "https://api.moonshot.example/v1/files/file-1")


def test_missing_key_stops_before_upload():
    session = FakeSession()
    with pytest.raises(KimiError) as caught:
        make_client(session, api_key=None).analyze_docx_json(stream=io.BytesIO(), filename="a.docx", request_id="job", build_messages=lambda _: [])
    assert caught.value.code == "ai_service_not_configured"
    assert session.calls == []


def test_timeout_has_chinese_public_error():
    session = FakeSession(error=requests.Timeout("private timeout"))
    with pytest.raises(KimiError) as caught:
        make_client(session).analyze_docx_json(stream=io.BytesIO(), filename="a.docx", request_id="job", build_messages=lambda _: [])
    assert caught.value.code == "ai_timeout"
    assert caught.value.public_message == "AI 分析超时，请稍后重试。"


def test_invalid_completion_is_reported_and_remote_file_is_removed():
    session = FakeSession(
        upload=FakeResponse(payload={"id": "file-2", "status": "ready"}),
        content=FakeResponse(text="content"),
        completion=FakeResponse(stream_lines=["data: [DONE]"]),
    )
    with pytest.raises(KimiError) as caught:
        make_client(session).analyze_docx_json(stream=io.BytesIO(), filename="a.docx", request_id="job", build_messages=lambda _: [])
    assert caught.value.code == "ai_empty_response"
    assert session.calls[-1][0] == "delete"
