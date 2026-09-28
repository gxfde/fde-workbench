from __future__ import annotations

import logging
from typing import BinaryIO, Mapping
from urllib.parse import quote, unquote

import oss2
from pydantic import SecretStr

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


def _configure_safe_oss_logging() -> None:
    """Keep SDK request headers and signed URLs out of application logs."""

    parent = logging.getLogger("oss2")
    parent.handlers.clear()
    parent.addHandler(logging.NullHandler())
    parent.propagate = False
    parent.setLevel(logging.WARNING)
    for name, candidate in logging.Logger.manager.loggerDict.items():
        if name.startswith("oss2.") and isinstance(candidate, logging.Logger):
            candidate.handlers.clear()
            candidate.setLevel(logging.NOTSET)
            candidate.propagate = True


_configure_safe_oss_logging()


class _CountingStream:
    def __init__(self, stream: BinaryIO) -> None:
        self._stream = stream
        self.bytes_read = 0

    def read(self, size: int = -1) -> bytes:
        chunk = self._stream.read(size)
        self.bytes_read += len(chunk)
        return chunk

    def __getattr__(self, name: str):
        return getattr(self._stream, name)


class AliyunOssStorage:
    def __init__(
        self,
        *,
        bucket_name: str,
        endpoint: str | None = None,
        access_key_id: SecretStr | str | None = None,
        access_key_secret: SecretStr | str | None = None,
        client=None,
    ) -> None:
        _configure_safe_oss_logging()
        self.bucket_name = bucket_name
        self.endpoint = endpoint
        if client is None:
            if not endpoint or access_key_id is None or access_key_secret is None:
                raise StorageError("missing_oss_configuration")
            auth = oss2.Auth(
                self._secret_value(access_key_id),
                self._secret_value(access_key_secret),
            )
            client = oss2.Bucket(auth, endpoint, bucket_name)
        self._client = client

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(bucket_name={self.bucket_name!r}, "
            f"endpoint={self.endpoint!r})"
        )

    def begin_multipart(self, key: str, content_type: str) -> MultipartUpload:
        validate_object_key(key)
        result = self._oss_call(
            self._client.init_multipart_upload,
            key,
            headers={"Content-Type": content_type},
        )
        return MultipartUpload(key=key, upload_id=result.upload_id)

    def sign_part(
        self,
        key: str,
        upload_id: str,
        part_number: int,
        expires_seconds: int = 300,
    ) -> str:
        validate_object_key(key)
        validate_part_number(part_number)
        validate_expiration(expires_seconds)
        return self._oss_call(
            self._client.sign_url,
            "PUT",
            key,
            expires_seconds,
            params={"uploadId": upload_id, "partNumber": str(part_number)},
        )

    def complete_multipart(
        self, key: str, upload_id: str, parts: list[UploadedPart]
    ) -> StoredObject:
        validate_object_key(key)
        normalized_parts = normalize_parts(parts)
        oss_parts = [
            oss2.models.PartInfo(part.part_number, part.etag)
            for part in normalized_parts
        ]
        self._oss_call(
            self._client.complete_multipart_upload,
            key,
            upload_id,
            oss_parts,
            not_found_code="multipart_upload_not_found",
        )
        return self.head(key)

    def abort_multipart(self, key: str, upload_id: str) -> None:
        validate_object_key(key)
        self._oss_call(
            self._client.abort_multipart_upload,
            key,
            upload_id,
            not_found_code="multipart_upload_not_found",
        )

    def put_stream(
        self,
        key: str,
        stream: BinaryIO,
        content_type: str,
        metadata: Mapping[str, str],
    ) -> StoredObject:
        validate_object_key(key)
        normalized_metadata = normalize_metadata(metadata)
        headers = {"Content-Type": content_type}
        headers.update(
            {
                f"x-oss-meta-{name}": quote(value, safe="")
                for name, value in normalized_metadata.items()
            }
        )
        counted = _CountingStream(stream)
        result = self._oss_call(
            self._client.put_object, key, counted, headers=headers
        )
        return StoredObject(
            key=key,
            size=counted.bytes_read,
            etag=self._etag(result.etag),
            content_type=content_type,
            metadata=normalized_metadata,
        )

    def open_stream(self, key: str) -> BinaryIO:
        validate_object_key(key)
        return self._oss_call(self._client.get_object, key)

    def head(self, key: str) -> StoredObject:
        validate_object_key(key)
        result = self._oss_call(self._client.head_object, key)
        headers = dict(result.headers or {})
        metadata = {
            name[len("x-oss-meta-") :].lower(): unquote(value)
            for name, value in headers.items()
            if name.lower().startswith("x-oss-meta-")
        }
        content_type = result.content_type or headers.get(
            "Content-Type", "application/octet-stream"
        )
        return StoredObject(
            key=key,
            size=int(result.content_length),
            etag=self._etag(result.etag),
            content_type=content_type,
            metadata=metadata,
        )

    def copy(self, source_key: str, target_key: str) -> StoredObject:
        validate_object_key(source_key)
        validate_object_key(target_key)
        self._oss_call(
            self._client.copy_object,
            self.bucket_name,
            source_key,
            target_key,
            headers=None,
        )
        return self.head(target_key)

    def sign_download(
        self, key: str, filename: str, expires_seconds: int = 300
    ) -> str:
        validate_object_key(key)
        validate_expiration(expires_seconds)
        return self._oss_call(
            self._client.sign_url,
            "GET",
            key,
            expires_seconds,
            params={"response-content-disposition": content_disposition(filename)},
        )

    def delete(self, key: str) -> None:
        validate_object_key(key)
        self._oss_call(self._client.delete_object, key)

    @staticmethod
    def _secret_value(value: SecretStr | str) -> str:
        if isinstance(value, SecretStr):
            return value.get_secret_value()
        return value

    @staticmethod
    def _etag(value: str) -> str:
        return value.strip('"')

    @staticmethod
    def _oss_call(
        callable_, *args, not_found_code: str = "object_not_found", **kwargs
    ):
        try:
            return callable_(*args, **kwargs)
        except oss2.exceptions.NotFound:
            raise StorageNotFoundError(not_found_code) from None
        except oss2.exceptions.OssError as error:
            if error.status == 404:
                raise StorageNotFoundError(not_found_code) from None
            raise StorageError("storage_backend_error") from None
