from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import shutil
import tempfile
import threading
import time
import uuid
import weakref
from pathlib import Path
from typing import BinaryIO, Callable, Mapping
from urllib.parse import urlencode

from fde_api.storage.base import (
    MultipartUpload,
    StorageError,
    StorageNotFoundError,
    StoredObject,
    UploadedPart,
    content_disposition,
    normalize_metadata,
    normalize_parts,
    validate_expiration,
    validate_object_key,
    validate_part_number,
)


_PROCESS_LOCKS_GUARD = threading.Lock()
_PROCESS_LOCKS: weakref.WeakValueDictionary[str, threading.RLock] = (
    weakref.WeakValueDictionary()
)


def _process_lock(identity: str) -> threading.RLock:
    with _PROCESS_LOCKS_GUARD:
        lock = _PROCESS_LOCKS.get(identity)
        if lock is None:
            lock = threading.RLock()
            _PROCESS_LOCKS[identity] = lock
        return lock


class _LockedBinaryStream:
    def __init__(self, stream: BinaryIO, lock: threading.RLock) -> None:
        self._stream = stream
        self._lock = lock
        self._closed = False

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)

    def close(self) -> None:
        if not self._closed:
            try:
                self._stream.close()
            finally:
                self._closed = True
                self._lock.release()

    @property
    def closed(self) -> bool:
        return self._closed

    def __enter__(self) -> "_LockedBinaryStream":
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    def __iter__(self):
        return iter(self._stream)

    def __getattr__(self, name: str):
        return getattr(self._stream, name)

    def __del__(self) -> None:
        self.close()


class LocalObjectStorage:
    """Filesystem-backed storage for local development and deterministic tests."""

    def __init__(
        self,
        root: str | Path,
        *,
        base_url_provider: Callable[[], str] | None = None,
        signing_key: bytes | None = None,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self._objects_root = self.root / "objects"
        self._metadata_root = self.root / ".metadata"
        self._multipart_root = self.root / ".multipart"
        self._signing_key = signing_key or secrets.token_bytes(32)
        self._base_url_provider = base_url_provider or (lambda: "http://127.0.0.1")
        for directory in (
            self._objects_root,
            self._metadata_root,
            self._multipart_root,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    def begin_multipart(self, key: str, content_type: str) -> MultipartUpload:
        validate_object_key(key)
        upload_id = uuid.uuid4().hex
        with self._upload_lock(upload_id):
            upload_root = self._multipart_root / upload_id
            upload_root.mkdir(mode=0o700)
            self._write_json_atomic(
                self._manifest_path(upload_id),
                {"key": key, "content_type": content_type},
            )
        return MultipartUpload(key=key, upload_id=upload_id)

    def sign_part(
        self,
        key: str,
        upload_id: str,
        part_number: int,
        expires_seconds: int = 300,
    ) -> str:
        with self._upload_lock(upload_id):
            manifest = self._load_upload(key, upload_id)
            del manifest
            validate_part_number(part_number)
            validate_expiration(expires_seconds)
            expires_at = int(time.time()) + expires_seconds
            signature = self._request_signature(
                method="PUT",
                key=key,
                upload_id=upload_id,
                part_number=part_number,
                expires_at=expires_at,
                filename="",
            )
        query = urlencode(
            {"key": key, "expires": str(expires_at), "signature": signature}
        )
        base_url = self._base_url_provider().rstrip("/")
        return (
            f"{base_url}/api/v1/local-storage/multipart/{upload_id}"
            f"/parts/{part_number}?{query}"
        )

    def complete_multipart(
        self, key: str, upload_id: str, parts: list[UploadedPart]
    ) -> StoredObject:
        with self._upload_lock(upload_id):
            manifest = self._load_upload(key, upload_id)
            normalized_parts = normalize_parts(parts)
            with self._object_lock(key):
                target = self._object_path(key)
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary_path: Path | None = None
                digest = hashlib.md5(usedforsecurity=False)
                size = 0
                try:
                    with tempfile.NamedTemporaryFile(
                        mode="wb", dir=target.parent, delete=False
                    ) as temporary:
                        temporary_path = Path(temporary.name)
                        for part in normalized_parts:
                            part_path = self._part_path(
                                upload_id, part.part_number
                            )
                            if not part_path.is_file():
                                raise StorageError("multipart_part_not_found")
                            part_digest = hashlib.md5(usedforsecurity=False)
                            with part_path.open("rb") as source:
                                while chunk := source.read(1024 * 1024):
                                    part_digest.update(chunk)
                                    digest.update(chunk)
                                    size += len(chunk)
                                    temporary.write(chunk)
                            if part_digest.hexdigest() != part.etag:
                                raise StorageError("multipart_etag_mismatch")
                        temporary.flush()
                        os.fsync(temporary.fileno())
                    temporary_path.replace(target)
                    temporary_path = None
                    self._write_object_metadata(
                        key,
                        etag=digest.hexdigest(),
                        content_type=manifest["content_type"],
                        metadata={},
                    )
                finally:
                    if temporary_path is not None:
                        temporary_path.unlink(missing_ok=True)

            self._remove_upload(upload_id)
            return StoredObject(
                key=key,
                size=size,
                etag=digest.hexdigest(),
                content_type=manifest["content_type"],
                metadata={},
            )

    def abort_multipart(self, key: str, upload_id: str) -> None:
        with self._upload_lock(upload_id):
            self._load_upload(key, upload_id)
            self._remove_upload(upload_id)

    def put_stream(
        self,
        key: str,
        stream: BinaryIO,
        content_type: str,
        metadata: Mapping[str, str],
    ) -> StoredObject:
        validate_object_key(key)
        normalized_metadata = normalize_metadata(metadata)
        with self._object_lock(key):
            return self._put_stream_unlocked(
                key, stream, content_type, normalized_metadata
            )

    def _put_stream_unlocked(
        self,
        key: str,
        stream: BinaryIO,
        content_type: str,
        metadata: Mapping[str, str],
    ) -> StoredObject:
        target = self._object_path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        digest = hashlib.md5(usedforsecurity=False)
        size = 0
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=target.parent, delete=False
            ) as temporary:
                temporary_path = Path(temporary.name)
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
                    size += len(chunk)
                    temporary.write(chunk)
                temporary.flush()
                os.fsync(temporary.fileno())
            temporary_path.replace(target)
            temporary_path = None
            self._write_object_metadata(
                key,
                etag=digest.hexdigest(),
                content_type=content_type,
                metadata=metadata,
            )
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

        return StoredObject(
            key=key,
            size=size,
            etag=digest.hexdigest(),
            content_type=content_type,
            metadata=dict(metadata),
        )

    def open_stream(self, key: str) -> BinaryIO:
        lock = self._object_lock(key)
        lock.acquire()
        try:
            stream = self._object_path(key).open("rb")
        except FileNotFoundError:
            lock.release()
            raise StorageNotFoundError("object_not_found") from None
        except Exception:
            lock.release()
            raise
        return _LockedBinaryStream(stream, lock)

    def head(self, key: str) -> StoredObject:
        with self._object_lock(key):
            return self._head_unlocked(key)

    def _head_unlocked(self, key: str) -> StoredObject:
        path = self._object_path(key)
        try:
            stat = path.stat()
            stored_metadata = json.loads(
                self._object_metadata_path(key).read_text(encoding="utf-8")
            )
        except FileNotFoundError:
            raise StorageNotFoundError("object_not_found") from None
        except (json.JSONDecodeError, KeyError, TypeError):
            raise StorageError("invalid_local_metadata") from None
        return StoredObject(
            key=key,
            size=stat.st_size,
            etag=stored_metadata["etag"],
            content_type=stored_metadata["content_type"],
            metadata=dict(stored_metadata["metadata"]),
        )

    def copy(self, source_key: str, target_key: str) -> StoredObject:
        validate_object_key(source_key)
        validate_object_key(target_key)
        locks = [
            self._object_lock(key)
            for key in sorted({source_key, target_key})
        ]
        for lock in locks:
            lock.acquire()
        try:
            source = self._head_unlocked(source_key)
            with self._object_path(source_key).open("rb") as stream:
                return self._put_stream_unlocked(
                    target_key, stream, source.content_type, source.metadata
                )
        except FileNotFoundError:
            raise StorageNotFoundError("object_not_found") from None
        finally:
            for lock in reversed(locks):
                lock.release()

    def sign_download(
        self, key: str, filename: str, expires_seconds: int = 300
    ) -> str:
        with self._object_lock(key):
            if not self._object_path(key).is_file():
                raise StorageNotFoundError("object_not_found")
            disposition = content_disposition(filename)
            del disposition
            validate_expiration(expires_seconds)
            expires_at = int(time.time()) + expires_seconds
            signature = self._request_signature(
                method="GET",
                key=key,
                upload_id="",
                part_number=0,
                expires_at=expires_at,
                filename=filename,
            )
        query = urlencode(
            {
                "key": key,
                "filename": filename,
                "expires": str(expires_at),
                "signature": signature,
            }
        )
        base_url = self._base_url_provider().rstrip("/")
        return f"{base_url}/api/v1/local-storage/download?{query}"

    def accept_signed_part(
        self,
        *,
        method: str,
        key: str,
        upload_id: str,
        part_number: int,
        expires: str,
        signature: str,
        stream: BinaryIO,
    ) -> str:
        expires_at = self._verify_request(
            method=method,
            key=key,
            upload_id=upload_id,
            part_number=part_number,
            expires=expires,
            filename="",
            signature=signature,
        )
        del expires_at
        with self._upload_lock(upload_id):
            self._load_upload(key, upload_id)
            part_path = self._part_path(upload_id, part_number)
            temporary_path: Path | None = None
            digest = hashlib.md5(usedforsecurity=False)
            try:
                with tempfile.NamedTemporaryFile(
                    mode="wb", dir=part_path.parent, delete=False
                ) as temporary:
                    temporary_path = Path(temporary.name)
                    while chunk := stream.read(1024 * 1024):
                        digest.update(chunk)
                        temporary.write(chunk)
                    temporary.flush()
                    os.fsync(temporary.fileno())
                temporary_path.replace(part_path)
                temporary_path = None
            finally:
                if temporary_path is not None:
                    temporary_path.unlink(missing_ok=True)
            return digest.hexdigest()

    def open_signed_download(
        self,
        *,
        method: str,
        key: str,
        filename: str,
        expires: str,
        signature: str,
    ) -> tuple[StoredObject, BinaryIO, str]:
        self._verify_request(
            method=method,
            key=key,
            upload_id="",
            part_number=0,
            expires=expires,
            filename=filename,
            signature=signature,
        )
        with self._object_lock(key):
            stored = self._head_unlocked(key)
            stream = self.open_stream(key)
            return stored, stream, content_disposition(filename)

    def delete(self, key: str) -> None:
        with self._object_lock(key):
            self._object_path(key).unlink(missing_ok=True)
            self._object_metadata_path(key).unlink(missing_ok=True)

    def _object_path(self, key: str) -> Path:
        validate_object_key(key)
        path = self._objects_root.joinpath(*key.split("/"))
        try:
            path.relative_to(self._objects_root)
        except ValueError:
            raise StorageError("invalid_object_key") from None
        return path

    def _object_lock(self, key: str) -> threading.RLock:
        validate_object_key(key)
        return _process_lock(f"object:{self.root}:{key}")

    def _upload_lock(self, upload_id: str) -> threading.RLock:
        self._manifest_path(upload_id)
        return _process_lock(f"upload:{self.root}:{upload_id}")

    def _object_metadata_path(self, key: str) -> Path:
        validate_object_key(key)
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self._metadata_root / f"{digest}.json"

    def _write_object_metadata(
        self,
        key: str,
        *,
        etag: str,
        content_type: str,
        metadata: Mapping[str, str],
    ) -> None:
        self._write_json_atomic(
            self._object_metadata_path(key),
            {
                "etag": etag,
                "content_type": content_type,
                "metadata": dict(metadata),
            },
        )

    def _manifest_path(self, upload_id: str) -> Path:
        if not upload_id or not upload_id.isalnum():
            raise StorageError("multipart_upload_not_found")
        return self._multipart_root / f"{upload_id}.json"

    def _part_path(self, upload_id: str, part_number: int) -> Path:
        validate_part_number(part_number)
        manifest_path = self._manifest_path(upload_id)
        if not manifest_path.is_file():
            raise StorageError("multipart_upload_not_found")
        return self._multipart_root / upload_id / f"part-{part_number:05d}"

    def _load_upload(self, key: str, upload_id: str) -> dict[str, str]:
        validate_object_key(key)
        try:
            manifest = json.loads(
                self._manifest_path(upload_id).read_text(encoding="utf-8")
            )
        except (FileNotFoundError, json.JSONDecodeError):
            raise StorageError("multipart_upload_not_found") from None
        if manifest.get("key") != key:
            raise StorageError("multipart_key_mismatch")
        return manifest

    def _remove_upload(self, upload_id: str) -> None:
        manifest_path = self._manifest_path(upload_id)
        shutil.rmtree(self._multipart_root / upload_id, ignore_errors=True)
        manifest_path.unlink(missing_ok=True)

    def _verify_request(
        self,
        *,
        method: str,
        key: str,
        upload_id: str,
        part_number: int,
        expires: str,
        filename: str,
        signature: str,
    ) -> int:
        validate_object_key(key)
        validate_part_number(part_number) if part_number else None
        try:
            expires_at = int(expires)
        except (TypeError, ValueError):
            raise StorageError("invalid_signature") from None
        now = int(time.time())
        if expires_at <= now:
            raise StorageError("signed_url_expired")
        if expires_at - now > 300:
            raise StorageError("invalid_signature")
        expected = self._request_signature(
            method=method,
            key=key,
            upload_id=upload_id,
            part_number=part_number,
            expires_at=expires_at,
            filename=filename,
        )
        if not hmac.compare_digest(expected, signature):
            raise StorageError("invalid_signature")
        return expires_at

    def _request_signature(
        self,
        *,
        method: str,
        key: str,
        upload_id: str,
        part_number: int,
        expires_at: int,
        filename: str,
    ) -> str:
        payload = json.dumps(
            {
                "expires": expires_at,
                "filename": filename,
                "key": key,
                "method": method,
                "part_number": part_number,
                "upload_id": upload_id,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hmac.new(
            self._signing_key, payload.encode("utf-8"), hashlib.sha256
        ).hexdigest()

    @staticmethod
    def _write_json_atomic(path: Path, value: Mapping[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                json.dump(value, temporary, ensure_ascii=False, sort_keys=True)
                temporary.flush()
                os.fsync(temporary.fileno())
            temporary_path.replace(path)
            temporary_path = None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
