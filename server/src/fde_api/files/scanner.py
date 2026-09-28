"""Content sniffing and ClamAV INSTREAM scanning helpers for the file subsystem.

This module is dependency-free (no ``filetype`` package): the magic-byte
detector recognizes common document and archive signatures when available.
"""

from __future__ import annotations

import socket
import struct
from dataclasses import dataclass
from typing import BinaryIO, Protocol, runtime_checkable

from fde_api.files.names import extension_of

#: Number of leading bytes read to sniff a magic-byte signature.
HEAD_BYTES = 16


@dataclass
class ScanResult:
    """Outcome of a single ClamAV scan as seen by the caller."""

    clean: bool
    status: str  # one of "clean", "infected", "error", "timeout", "not_checked"
    signature: str | None = None


@runtime_checkable
class FileScanner(Protocol):
    """Any object able to scan a binary stream for malware."""

    def scan(self, stream: BinaryIO) -> ScanResult: ...


# ---------------------------------------------------------------------------
# Magic-byte sniffing
# ---------------------------------------------------------------------------

#: Office formats are ZIP containers; map their extension to the canonical mime.
_OFFICE_MIME = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}

#: Allowed extensions that carry an expected magic-byte family.
_EXT_FAMILY = {
    ".pdf": "pdf",
    ".png": "png",
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".zip": "zip",
    ".docx": "zip",
    ".xlsx": "zip",
    ".pptx": "zip",
}


def sniff_family(head: bytes) -> str:
    """Return the detected magic-byte family for ``head``.

    Families: ``pdf``, ``png``, ``jpeg``, ``zip``, ``exe``, or ``unknown``.
    """
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if head.startswith(b"PK\x03\x04"):
        return "zip"
    if head.startswith(b"MZ"):
        return "exe"
    return "unknown"


def detect_media_type(head: bytes, filename: str) -> str:
    """Return a mime string for the first ``head`` bytes of a file.

    Magic bytes win for PDF/PNG/JPEG. ZIP containers are distinguished by the
    extension, so ``.docx``/``.xlsx``/``.pptx`` resolve to their office mime
    while a bare ZIP stays ``application/zip``. Unknown content falls back to
    ``application/octet-stream``.
    """
    family = sniff_family(head)
    extension = extension_of(filename)
    if family == "pdf":
        return "application/pdf"
    if family == "png":
        return "image/png"
    if family == "jpeg":
        return "image/jpeg"
    if family == "zip":
        return _OFFICE_MIME.get(extension, "application/zip")
    if family == "exe":
        return "application/x-msdownload"
    return "application/octet-stream"


# ---------------------------------------------------------------------------
# ClamAV INSTREAM protocol scanner
# ---------------------------------------------------------------------------


class ClamAvScanner:
    """Scan a binary stream against a live ClamAV daemon via INSTREAM.

    The protocol sends ``zINSTREAM\\0`` followed by length-prefixed chunks and
    a final four-byte zero terminator. The daemon replies with a text line of
    the form ``<name>: OK`` or ``<name>: <signature> FOUND``.
    """

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 3310,
        timeout_seconds: int = 10,
        socket_timeout_seconds: int = 5,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout_seconds = timeout_seconds
        self.socket_timeout_seconds = socket_timeout_seconds

    def scan(self, stream: BinaryIO) -> ScanResult:
        """Scan ``stream`` and never raise; failures degrade to an error result."""
        try:
            with socket.create_connection(
                (self.host, self.port), timeout=self.timeout_seconds
            ) as sock:
                sock.settimeout(self.socket_timeout_seconds)
                sock.sendall(b"zINSTREAM\x00")
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    sock.sendall(struct.pack(">I", len(chunk)) + chunk)
                sock.sendall(b"\x00\x00\x00\x00")
                response = self._read_response(sock)
        except socket.timeout:
            return ScanResult(clean=False, status="timeout", signature=None)
        except (OSError, struct.error, ValueError):
            return ScanResult(clean=False, status="error", signature=None)
        return _parse_clam_response(response)

    @staticmethod
    def _read_response(sock: socket.socket) -> bytes:
        response = bytearray()
        while True:
            data = sock.recv(4096)
            if not data:
                break
            response.extend(data)
        return bytes(response)


def _parse_clam_response(response: bytes) -> ScanResult:
    text = response.decode("utf-8", "replace").strip("\x00\r\n\t ")
    if not text:
        return ScanResult(clean=False, status="error", signature=None)
    if "FOUND" in text:
        return ScanResult(
            clean=False,
            status="infected",
            signature=_extract_signature(text),
        )
    if "OK" in text:
        return ScanResult(clean=True, status="clean", signature=None)
    return ScanResult(clean=False, status="error", signature=None)


def _extract_signature(text: str) -> str | None:
    before_found = text.split("FOUND", 1)[0]
    parts = before_found.split(":")
    candidate = parts[-1] if parts else before_found
    signature = candidate.strip("\x00\r\n\t ")
    return signature or None
