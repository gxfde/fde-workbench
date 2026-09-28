from __future__ import annotations

import io
import socket
import struct

from fde_api.files.scanner import ClamAvScanner, detect_media_type, sniff_family


def _make_scanner(**kwargs) -> ClamAvScanner:
    return ClamAvScanner(host="127.0.0.1", port=3310, **kwargs)


class FakeSocket:
    def __init__(self, response: bytes, *, timeout_on_recv: bool = False):
        self.response = response
        self.timeout_on_recv = timeout_on_recv
        self.sent = bytearray()
        self._offset = 0

    def settimeout(self, seconds):
        pass

    def sendall(self, data):
        self.sent.extend(data)

    def recv(self, size):
        if self.timeout_on_recv:
            raise socket.timeout("timed out")
        remaining = self.response[self._offset:]
        if not remaining:
            return b""
        chunk = remaining[:size]
        self._offset += len(chunk)
        return chunk

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _patch_socket(monkeypatch, response: bytes, *, timeout_on_recv: bool = False):
    fake = FakeSocket(response, timeout_on_recv=timeout_on_recv)

    def fake_create_connection(address, timeout=None):
        return fake

    monkeypatch.setattr("socket.create_connection", fake_create_connection)
    return fake


def test_clamav_sends_instream_protocol(monkeypatch):
    payload = b"file-content-bytes"
    fake = _patch_socket(monkeypatch, b"stream: OK\x00")

    scanner = _make_scanner()
    result = scanner.scan(io.BytesIO(payload))

    assert result.clean is True
    assert result.status == "clean"
    sent = bytes(fake.sent)
    assert sent.startswith(b"zINSTREAM\x00")
    assert b"zINSTREAM\x00" in sent
    assert payload in sent
    assert sent.endswith(b"\x00\x00\x00\x00")
    # At least one length-prefixed chunk precedes the terminating zeros.
    expected_chunk = struct.pack(">I", len(payload)) + payload
    assert expected_chunk in sent


def test_clamav_marks_ok_as_clean(monkeypatch):
    _patch_socket(monkeypatch, b"stream: OK\x00")

    result = _make_scanner().scan(io.BytesIO(b"data"))

    assert result.clean is True
    assert result.status == "clean"
    assert result.signature is None


def test_clamav_marks_found_as_infected_with_signature(monkeypatch):
    _patch_socket(monkeypatch, b"stream: Eicar-Test-Signature FOUND\x00")

    result = _make_scanner().scan(io.BytesIO(b"data"))

    assert result.clean is False
    assert result.status == "infected"
    assert result.signature == "Eicar-Test-Signature"


def test_clamav_marks_empty_reply_as_error(monkeypatch):
    _patch_socket(monkeypatch, b"")

    result = _make_scanner().scan(io.BytesIO(b"data"))

    assert result.clean is False
    assert result.status == "error"
    assert result.signature is None


def test_clamav_marks_timeout_as_timeout(monkeypatch):
    _patch_socket(monkeypatch, b"", timeout_on_recv=True)

    result = _make_scanner().scan(io.BytesIO(b"data"))

    assert result.clean is False
    assert result.status == "timeout"
    assert result.signature is None


def test_clamav_never_raises_on_connection_error(monkeypatch):
    def bad_connect(address, timeout=None):
        raise OSError("connection refused")

    monkeypatch.setattr("socket.create_connection", bad_connect)

    result = _make_scanner().scan(io.BytesIO(b"data"))

    assert result.clean is False
    assert result.status == "error"


def test_detect_media_type_by_magic():
    assert detect_media_type(b"%PDF-1.7", "report.pdf") == "application/pdf"
    assert detect_media_type(b"\x89PNG\r\n\x1a\n", "photo.png") == "image/png"
    assert detect_media_type(b"\xff\xd8\xff\xe0", "photo.jpg") == "image/jpeg"
    assert detect_media_type(b"PK\x03\x04", "archive.zip") == "application/zip"
    assert (
        detect_media_type(b"PK\x03\x04", "文档.docx")
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert (
        detect_media_type(b"PK\x03\x04", "sheet.xlsx")
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


def test_detect_media_type_unknown_falls_back_to_octet_stream():
    assert detect_media_type(b"nobody-knows", "file.txt") == "application/octet-stream"
    assert detect_media_type(b"MZ", "report.pdf") == "application/x-msdownload"


def test_sniff_family_identifies_pe_headers():
    assert sniff_family(b"MZ\x00\x00") == "exe"
    assert sniff_family(b"not-a-known-type") == "unknown"
