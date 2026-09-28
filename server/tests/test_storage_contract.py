from __future__ import annotations

import hashlib
import logging
import threading
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
import oss2

from fde_api.app import create_app
from fde_api.config import Settings
from fde_api.extensions import object_storage
from fde_api.storage import (
    AliyunOssStorage,
    LocalObjectStorage,
    StorageError,
    StorageNotFoundError,
    UploadedPart,
    validate_object_key,
    validate_project_key,
)


OBJECT_KEY = "projects/p1/attachments/f1/versions/v1/需求 文档.txt"


class FakeOssBucket:
    def __init__(self) -> None:
        self.bucket_name = "fde-test-bucket"
        self.objects: dict[str, tuple[bytes, dict[str, str], str]] = {}
        self.uploads: dict[str, tuple[str, dict[int, tuple[bytes, str]]]] = {}
        self.calls: list[tuple] = []

    def init_multipart_upload(self, key, headers=None):
        self.calls.append(("init_multipart_upload", key, headers))
        upload_id = "upload-1"
        self.uploads[upload_id] = (key, {})
        return SimpleNamespace(upload_id=upload_id)

    def sign_url(self, method, key, expires, headers=None, params=None):
        self.calls.append(("sign_url", method, key, expires, headers, params))
        return f"https://signed.invalid/{key}"

    def complete_multipart_upload(self, key, upload_id, parts):
        normalized = [(part.part_number, part.etag) for part in parts]
        self.calls.append(
            ("complete_multipart_upload", key, upload_id, normalized)
        )
        content = b"".join(
            self.uploads[upload_id][1][number][0] for number, _ in normalized
        )
        headers = {"Content-Type": "application/octet-stream"}
        etag = hashlib.md5(content).hexdigest()
        self.objects[key] = (content, headers, etag)
        return SimpleNamespace(etag=etag)

    def abort_multipart_upload(self, key, upload_id):
        self.calls.append(("abort_multipart_upload", key, upload_id))
        self.uploads.pop(upload_id, None)
        return SimpleNamespace()

    def put_object(self, key, stream, headers=None):
        content = stream.read()
        normalized_headers = dict(headers or {})
        etag = hashlib.md5(content).hexdigest()
        self.calls.append(("put_object", key, normalized_headers, content))
        self.objects[key] = (content, normalized_headers, etag)
        return SimpleNamespace(etag=etag)

    def get_object(self, key):
        self.calls.append(("get_object", key))
        if key not in self.objects:
            raise KeyError(key)
        return BytesIO(self.objects[key][0])

    def head_object(self, key):
        self.calls.append(("head_object", key))
        if key not in self.objects:
            raise KeyError(key)
        content, headers, etag = self.objects[key]
        return SimpleNamespace(
            content_length=len(content),
            etag=etag,
            content_type=headers.get("Content-Type"),
            headers=headers,
        )

    def copy_object(self, source_bucket, source_key, target_key, headers=None):
        self.calls.append(
            ("copy_object", source_bucket, source_key, target_key, headers)
        )
        content, source_headers, etag = self.objects[source_key]
        self.objects[target_key] = (content, dict(source_headers), etag)
        return SimpleNamespace(etag=etag)

    def delete_object(self, key):
        self.calls.append(("delete_object", key))
        self.objects.pop(key, None)
        return SimpleNamespace()


@pytest.fixture
def fake_oss_bucket():
    return FakeOssBucket()


@pytest.fixture
def oss_storage(fake_oss_bucket):
    return AliyunOssStorage(bucket_name="fde-test-bucket", client=fake_oss_bucket)


@pytest.mark.parametrize(
    "key",
    [
        "/projects/p1/a.txt",
        "projects/p1/../p2/a.txt",
        "projects/p1\\a.txt",
        "projects/p1/a\x00.txt",
        "projects/p1/a\u0085.txt",
        "projects/p1//a.txt",
        "outside/p1/a.txt",
        "projects//a.txt",
        "projects/p1/",
    ],
)
def test_object_key_validation_rejects_unsafe_or_unscoped_keys(key):
    with pytest.raises(StorageError, match="invalid_object_key"):
        validate_object_key(key)


def test_object_key_validation_accepts_project_scoped_chinese_filename():
    assert validate_object_key(OBJECT_KEY) == OBJECT_KEY


def test_object_key_validation_accepts_system_document_template_scope():
    key = "document-templates/template-1/sow/versions/2/sow-v2.docx"
    assert validate_object_key(key) == key


@pytest.mark.parametrize(
    "key",
    [
        "projects/p1/%2e%2e/a.txt",
        "projects/p1/100%.txt",
        "projects/p1/Ａ.txt",
        "projects/p1/a／b.txt",
        "projects/p1/a∕b.txt",
        "projects/p1/a⁄b.txt",
        "projects/p1/a\u2028b.txt",
        "projects/p1/a\u2029b.txt",
        "projects/p1/a\u202eb.txt",
        "projectsx/p1/a.txt",
    ],
)
def test_object_key_validation_rejects_encoded_noncanonical_and_confusable_keys(
    key,
):
    with pytest.raises(StorageError, match="invalid_object_key"):
        validate_object_key(key)


@pytest.mark.parametrize(
    "project_id",
    ["..", "p1/other", "p1%2fother", "p１", "p1\u202e", "p1∕other"],
)
def test_project_key_validation_rejects_unsafe_project_identifiers(project_id):
    with pytest.raises(StorageError, match="invalid_object_key"):
        validate_project_key(project_id, f"projects/{project_id}/a.txt")


def test_project_key_validation_accepts_exact_normal_chinese_project_scope():
    key = "projects/项目一/attachments/需求.txt"
    assert validate_project_key("项目一", key) == key


def test_local_storage_round_trip_copy_head_and_delete(tmp_path):
    storage = LocalObjectStorage(tmp_path)
    metadata = {"project-name": "测试", "source": "api"}

    stored = storage.put_stream(
        OBJECT_KEY, BytesIO(b"hello"), "text/plain", metadata
    )

    assert stored.key == OBJECT_KEY
    assert stored.size == 5
    assert stored.content_type == "text/plain"
    assert stored.metadata == metadata
    assert storage.open_stream(OBJECT_KEY).read() == b"hello"
    assert storage.head(OBJECT_KEY) == stored

    copied_key = "projects/p1/attachments/f1/versions/v2/副本.txt"
    copied = storage.copy(OBJECT_KEY, copied_key)
    assert copied.key == copied_key
    assert copied.metadata == metadata
    assert storage.open_stream(copied_key).read() == b"hello"

    storage.delete(OBJECT_KEY)
    with pytest.raises(StorageNotFoundError, match="object_not_found"):
        storage.open_stream(OBJECT_KEY)
    storage.delete(OBJECT_KEY)


def test_local_storage_completes_real_multipart_in_part_number_order(tmp_path):
    app = create_app(local_settings(tmp_path))
    client = app.test_client()
    with app.test_request_context(base_url="http://127.0.0.1:8010"):
        storage = object_storage.current
        upload = storage.begin_multipart(OBJECT_KEY, "text/plain")
        second_url = storage.sign_part(OBJECT_KEY, upload.upload_id, 2, 300)
        first_url = storage.sign_part(OBJECT_KEY, upload.upload_id, 1, 300)
    second = client.put(request_target(second_url), data=b"world")
    first = client.put(request_target(first_url), data=b"hello ")

    completed = storage.complete_multipart(
        OBJECT_KEY,
        upload.upload_id,
        [
            UploadedPart(2, second.headers["ETag"]),
            UploadedPart(1, first.headers["ETag"]),
        ],
    )

    assert completed.size == 11
    assert completed.content_type == "text/plain"
    assert storage.open_stream(OBJECT_KEY).read() == b"hello world"


def test_local_storage_abort_removes_multipart_parts(tmp_path):
    app = create_app(local_settings(tmp_path))
    client = app.test_client()
    with app.test_request_context(base_url="http://127.0.0.1:8010"):
        storage = object_storage.current
        upload = storage.begin_multipart(OBJECT_KEY, "text/plain")
        signed = storage.sign_part(OBJECT_KEY, upload.upload_id, 1, 300)
    assert client.put(request_target(signed), data=b"partial").status_code == 200

    storage.abort_multipart(OBJECT_KEY, upload.upload_id)

    assert client.put(request_target(signed), data=b"retry").status_code == 404
    with pytest.raises(StorageError, match="multipart_upload_not_found"):
        storage.sign_part(OBJECT_KEY, upload.upload_id, 1, 300)


def test_local_put_publishes_content_and_metadata_as_one_snapshot(
    monkeypatch, tmp_path
):
    storage = LocalObjectStorage(tmp_path)
    storage.put_stream(
        OBJECT_KEY, BytesIO(b"old"), "text/old", {"revision": "old"}
    )
    object_replaced = threading.Event()
    publish_metadata = threading.Event()
    original_write_metadata = storage._write_object_metadata

    def paused_metadata(key, *, etag, content_type, metadata):
        if metadata.get("revision") == "new":
            object_replaced.set()
            assert publish_metadata.wait(2)
        return original_write_metadata(
            key,
            etag=etag,
            content_type=content_type,
            metadata=metadata,
        )

    monkeypatch.setattr(storage, "_write_object_metadata", paused_metadata)
    writer = threading.Thread(
        target=lambda: storage.put_stream(
            OBJECT_KEY,
            BytesIO(b"new content"),
            "text/new",
            {"revision": "new"},
        )
    )
    observed: dict[str, object] = {}
    reader_done = threading.Event()

    def read_snapshot():
        with storage.open_stream(OBJECT_KEY) as stream:
            observed["content"] = stream.read()
        observed["head"] = storage.head(OBJECT_KEY)
        reader_done.set()

    writer.start()
    assert object_replaced.wait(2)
    reader = threading.Thread(target=read_snapshot)
    reader.start()
    try:
        assert not reader_done.wait(0.1)
    finally:
        publish_metadata.set()
    writer.join(2)
    reader.join(2)

    assert observed["content"] == b"new content"
    head = observed["head"]
    assert head.content_type == "text/new"
    assert head.metadata == {"revision": "new"}
    assert head.etag == hashlib.md5(b"new content").hexdigest()


def test_local_delete_cannot_leave_metadata_orphan_during_put(
    monkeypatch, tmp_path
):
    storage = LocalObjectStorage(tmp_path)
    storage.put_stream(OBJECT_KEY, BytesIO(b"old"), "text/plain", {})
    object_replaced = threading.Event()
    publish_metadata = threading.Event()
    original_write_metadata = storage._write_object_metadata

    def paused_metadata(key, *, etag, content_type, metadata):
        if content_type == "text/new":
            object_replaced.set()
            assert publish_metadata.wait(2)
        return original_write_metadata(
            key,
            etag=etag,
            content_type=content_type,
            metadata=metadata,
        )

    monkeypatch.setattr(storage, "_write_object_metadata", paused_metadata)
    writer = threading.Thread(
        target=lambda: storage.put_stream(
            OBJECT_KEY, BytesIO(b"new"), "text/new", {}
        )
    )
    delete_done = threading.Event()

    def delete_object():
        storage.delete(OBJECT_KEY)
        delete_done.set()

    writer.start()
    assert object_replaced.wait(2)
    deleter = threading.Thread(target=delete_object)
    deleter.start()
    try:
        assert not delete_done.wait(0.1)
    finally:
        publish_metadata.set()
    writer.join(2)
    deleter.join(2)

    with pytest.raises(StorageNotFoundError):
        storage.head(OBJECT_KEY)
    assert list((storage.root / ".metadata").iterdir()) == []


def test_local_open_stream_blocks_replacement_until_stream_closes(tmp_path):
    storage = LocalObjectStorage(tmp_path)
    storage.put_stream(OBJECT_KEY, BytesIO(b"old"), "text/plain", {})
    stream = storage.open_stream(OBJECT_KEY)
    replaced = threading.Event()

    def replace_object():
        storage.put_stream(OBJECT_KEY, BytesIO(b"new"), "text/plain", {})
        replaced.set()

    writer = threading.Thread(target=replace_object)
    writer.start()
    try:
        assert not replaced.wait(0.1)
        assert stream.read() == b"old"
    finally:
        stream.close()
    writer.join(2)
    assert replaced.is_set()


def test_local_copy_keeps_source_content_and_metadata_from_one_version(
    monkeypatch, tmp_path
):
    storage = LocalObjectStorage(tmp_path)
    target_key = "projects/p1/attachments/f1/versions/v2/copy.txt"
    storage.put_stream(
        OBJECT_KEY, BytesIO(b"old"), "text/old", {"revision": "old"}
    )
    copy_has_source_metadata = threading.Event()
    release_copy = threading.Event()
    writer_done = threading.Event()
    original_put_unlocked = storage._put_stream_unlocked

    def paused_target_put(key, stream, content_type, metadata):
        if key == target_key:
            copy_has_source_metadata.set()
            assert release_copy.wait(2)
        return original_put_unlocked(key, stream, content_type, metadata)

    monkeypatch.setattr(storage, "_put_stream_unlocked", paused_target_put)
    copy_thread = threading.Thread(
        target=lambda: storage.copy(OBJECT_KEY, target_key)
    )
    copy_thread.start()
    assert copy_has_source_metadata.wait(2)

    def replace_source():
        storage.put_stream(
            OBJECT_KEY,
            BytesIO(b"new"),
            "text/new",
            {"revision": "new"},
        )
        writer_done.set()

    writer = threading.Thread(target=replace_source)
    writer.start()
    try:
        assert not writer_done.wait(0.1)
    finally:
        release_copy.set()
    copy_thread.join(2)
    writer.join(2)

    with storage.open_stream(target_key) as copied:
        assert copied.read() == b"old"
    copied_head = storage.head(target_key)
    assert copied_head.content_type == "text/old"
    assert copied_head.metadata == {"revision": "old"}
    assert copied_head.etag == hashlib.md5(b"old").hexdigest()


def test_local_multipart_complete_waits_for_inflight_signed_part(tmp_path):
    storage = LocalObjectStorage(tmp_path)
    upload = storage.begin_multipart(OBJECT_KEY, "text/plain")
    signed = urlparse(storage.sign_part(OBJECT_KEY, upload.upload_id, 1, 300))
    query = parse_qs(signed.query)
    upload_started = threading.Event()
    release_upload = threading.Event()

    class PausedStream(BytesIO):
        paused = False

        def read(self, size=-1):
            if not self.paused:
                self.paused = True
                upload_started.set()
                assert release_upload.wait(2)
            return super().read(size)

    upload_errors: list[Exception] = []
    complete_errors: list[Exception] = []
    complete_done = threading.Event()

    def upload_part():
        try:
            storage.accept_signed_part(
                method="PUT",
                key=OBJECT_KEY,
                upload_id=upload.upload_id,
                part_number=1,
                expires=query["expires"][0],
                signature=query["signature"][0],
                stream=PausedStream(b"part"),
            )
        except Exception as error:
            upload_errors.append(error)

    def complete_upload():
        try:
            storage.complete_multipart(
                OBJECT_KEY,
                upload.upload_id,
                [UploadedPart(1, hashlib.md5(b"part").hexdigest())],
            )
        except Exception as error:
            complete_errors.append(error)
        finally:
            complete_done.set()

    uploader = threading.Thread(target=upload_part)
    uploader.start()
    assert upload_started.wait(2)
    completer = threading.Thread(target=complete_upload)
    completer.start()
    try:
        assert not complete_done.wait(0.1)
    finally:
        release_upload.set()
    uploader.join(2)
    completer.join(2)

    assert upload_errors == []
    assert complete_errors == []
    with storage.open_stream(OBJECT_KEY) as completed:
        assert completed.read() == b"part"


def test_local_signed_urls_are_utf8_safe_and_expire_in_five_minutes(
    monkeypatch, tmp_path
):
    monkeypatch.setattr("fde_api.storage.local.time.time", lambda: 1_000.0)
    storage = LocalObjectStorage(tmp_path)
    storage.put_stream(OBJECT_KEY, BytesIO(b"hello"), "text/plain", {})

    url = storage.sign_download(OBJECT_KEY, "需求 文档.txt", 300)
    query = parse_qs(urlparse(url).query)

    assert urlparse(url).scheme == "http"
    assert query["expires"] == ["1300"]
    assert query["filename"] == ["需求 文档.txt"]
    assert query["signature"][0]


def test_local_signed_http_part_upload_uses_same_client_flow_as_oss(tmp_path):
    app = create_app(local_settings(tmp_path))
    client = app.test_client()
    with app.test_request_context(base_url="http://127.0.0.1:8010"):
        storage = object_storage.current
        upload = storage.begin_multipart(OBJECT_KEY, "text/plain")
        signed_url = storage.sign_part(OBJECT_KEY, upload.upload_id, 1, 300)

    parsed = urlparse(signed_url)
    response = client.put(
        f"{parsed.path}?{parsed.query}",
        data=b"uploaded through HTTP",
        content_type="application/octet-stream",
    )

    assert parsed.scheme == "http"
    assert parsed.netloc == "127.0.0.1:8010"
    assert response.status_code == 200
    etag = response.headers["ETag"].strip('"')
    completed = storage.complete_multipart(
        OBJECT_KEY, upload.upload_id, [UploadedPart(1, etag)]
    )
    assert completed.size == 21
    with storage.open_stream(OBJECT_KEY) as stream:
        assert stream.read() == b"uploaded through HTTP"


def test_local_signed_http_download_verifies_signature_expiry_and_filename(
    monkeypatch, tmp_path
):
    monkeypatch.setattr("fde_api.storage.local.time.time", lambda: 1_000.0)
    app = create_app(local_settings(tmp_path))
    client = app.test_client()
    with app.test_request_context(base_url="http://127.0.0.1:8010"):
        storage = object_storage.current
        storage.put_stream(OBJECT_KEY, BytesIO(b"hello"), "text/plain", {})
        signed_url = storage.sign_download(OBJECT_KEY, "需求 文档.txt", 300)

    parsed = urlparse(signed_url)
    response = client.get(f"{parsed.path}?{parsed.query}")
    tampered = client.get(
        f"{parsed.path}?{parsed.query.replace('filename=', 'filename=evil-')}"
    )
    monkeypatch.setattr("fde_api.storage.local.time.time", lambda: 1_300.0)
    expired = client.get(f"{parsed.path}?{parsed.query}")

    assert parsed.scheme == "http"
    assert response.status_code == 200
    assert response.data == b"hello"
    assert response.headers["Content-Disposition"] == (
        "attachment; filename*=UTF-8''"
        "%E9%9C%80%E6%B1%82%20%E6%96%87%E6%A1%A3.txt"
    )
    assert tampered.status_code == 403
    assert expired.status_code == 403


def test_local_signed_routes_are_not_available_with_oss_backend():
    settings = Settings(
        env="test",
        database_url="sqlite://",
        redis_url="redis://127.0.0.1:6379/15",
        jwt_secret="test-secret-with-at-least-thirty-two-characters",
        storage_backend="oss",
        oss_endpoint="https://oss-cn.example.invalid",
        oss_bucket="fde-test-bucket",
        oss_access_key_id="new-test-access-id",
        oss_access_key_secret="new-test-access-secret",
    )
    client = create_app(settings).test_client()

    response = client.put(
        "/api/v1/local-storage/multipart/upload/parts/1"
        "?key=projects/p1/a.txt&expires=1&signature=invalid",
        data=b"payload",
    )

    assert response.status_code == 404
    assert response.json["error"]["code"] == "local_storage_unavailable"


@pytest.mark.parametrize("expires", [0, -1, 301, 86_400])
def test_local_storage_rejects_out_of_bounds_signature_expiry(tmp_path, expires):
    storage = LocalObjectStorage(tmp_path)
    storage.put_stream(OBJECT_KEY, BytesIO(b"hello"), "text/plain", {})

    with pytest.raises(StorageError, match="invalid_expiration"):
        storage.sign_download(OBJECT_KEY, "a.txt", expires)


def test_local_storage_signature_is_valid_across_process_instances(tmp_path):
    signing_key = b"shared-local-storage-signing-key"
    first = LocalObjectStorage(tmp_path, signing_key=signing_key)
    upload = first.begin_multipart(OBJECT_KEY, "application/octet-stream")
    signed = urlparse(first.sign_part(OBJECT_KEY, upload.upload_id, 1, 300))
    query = parse_qs(signed.query)

    second = LocalObjectStorage(tmp_path, signing_key=signing_key)
    etag = second.accept_signed_part(
        method="PUT",
        key=query["key"][0],
        upload_id=upload.upload_id,
        part_number=1,
        expires=query["expires"][0],
        signature=query["signature"][0],
        stream=BytesIO(b"cross-worker"),
    )

    assert etag


def test_oss_put_open_head_copy_delete_and_utf8_metadata(
    oss_storage, fake_oss_bucket
):
    metadata = {"project-name": "测试", "source": "api"}

    stored = oss_storage.put_stream(
        OBJECT_KEY, BytesIO(b"hello"), "text/plain", metadata
    )

    assert stored.size == 5
    assert stored.metadata == metadata
    assert storage_call(fake_oss_bucket, "put_object") == (
        "put_object",
        OBJECT_KEY,
        {
            "Content-Type": "text/plain",
            "x-oss-meta-project-name": "%E6%B5%8B%E8%AF%95",
            "x-oss-meta-source": "api",
        },
        b"hello",
    )
    assert oss_storage.open_stream(OBJECT_KEY).read() == b"hello"
    assert oss_storage.head(OBJECT_KEY).metadata == metadata

    target = "projects/p1/attachments/f1/versions/v2/副本.txt"
    copied = oss_storage.copy(OBJECT_KEY, target)
    assert copied.key == target
    assert storage_call(fake_oss_bucket, "copy_object") == (
        "copy_object",
        "fde-test-bucket",
        OBJECT_KEY,
        target,
        None,
    )

    oss_storage.delete(target)
    assert storage_call(fake_oss_bucket, "delete_object") == (
        "delete_object",
        target,
    )


def test_oss_multipart_calls_exact_methods_and_sorts_parts(
    oss_storage, fake_oss_bucket
):
    upload = oss_storage.begin_multipart(OBJECT_KEY, "text/plain")
    fake_oss_bucket.uploads[upload.upload_id][1].update(
        {
            1: (b"hello ", "etag-1"),
            2: (b"world", "etag-2"),
        }
    )

    signed = oss_storage.sign_part(OBJECT_KEY, upload.upload_id, 2, 300)
    completed = oss_storage.complete_multipart(
        OBJECT_KEY,
        upload.upload_id,
        [UploadedPart(2, '"etag-2"'), UploadedPart(1, '"etag-1"')],
    )

    assert signed == f"https://signed.invalid/{OBJECT_KEY}"
    assert storage_call(fake_oss_bucket, "init_multipart_upload") == (
        "init_multipart_upload",
        OBJECT_KEY,
        {"Content-Type": "text/plain"},
    )
    assert storage_call(fake_oss_bucket, "sign_url") == (
        "sign_url",
        "PUT",
        OBJECT_KEY,
        300,
        None,
        {"uploadId": upload.upload_id, "partNumber": "2"},
    )
    assert storage_call(fake_oss_bucket, "complete_multipart_upload") == (
        "complete_multipart_upload",
        OBJECT_KEY,
        upload.upload_id,
        [(1, "etag-1"), (2, "etag-2")],
    )
    assert completed.size == 11


def test_oss_abort_calls_client_exactly(oss_storage, fake_oss_bucket):
    upload = oss_storage.begin_multipart(OBJECT_KEY, "text/plain")

    oss_storage.abort_multipart(OBJECT_KEY, upload.upload_id)

    assert storage_call(fake_oss_bucket, "abort_multipart_upload") == (
        "abort_multipart_upload",
        OBJECT_KEY,
        upload.upload_id,
    )


@pytest.mark.parametrize(
    "exception",
    [
        oss2.exceptions.NotFound(
            404,
            {"x-oss-request-id": "request-id"},
            b"",
            {"Code": "NotFound", "Message": "missing"},
        ),
        oss2.exceptions.ServerError(
            404,
            {"x-oss-request-id": "request-id"},
            b"",
            {"Code": "Unknown404", "Message": "missing"},
        ),
    ],
)
def test_oss_sdk_not_found_and_raw_404_map_to_stable_object_not_found(
    monkeypatch, oss_storage, fake_oss_bucket, exception
):
    def raise_not_found(_key):
        raise exception

    monkeypatch.setattr(fake_oss_bucket, "head_object", raise_not_found)

    with pytest.raises(StorageNotFoundError) as error:
        oss_storage.head(OBJECT_KEY)

    assert error.value.code == "object_not_found"


def test_oss_missing_multipart_upload_uses_stable_multipart_code(
    monkeypatch, oss_storage, fake_oss_bucket
):
    missing = oss2.exceptions.NoSuchUpload(
        404,
        {"x-oss-request-id": "request-id"},
        b"",
        {"Code": "NoSuchUpload", "Message": "missing"},
    )

    def raise_missing(_key, _upload_id):
        raise missing

    monkeypatch.setattr(fake_oss_bucket, "abort_multipart_upload", raise_missing)

    with pytest.raises(StorageNotFoundError) as error:
        oss_storage.abort_multipart(OBJECT_KEY, "missing-upload")

    assert error.value.code == "multipart_upload_not_found"


def test_oss_signed_download_binds_utf8_content_disposition(
    oss_storage, fake_oss_bucket
):
    oss_storage.put_stream(OBJECT_KEY, BytesIO(b"hello"), "text/plain", {})

    oss_storage.sign_download(OBJECT_KEY, "需求 文档.txt", 300)

    assert storage_call(fake_oss_bucket, "sign_url") == (
        "sign_url",
        "GET",
        OBJECT_KEY,
        300,
        None,
        {
            "response-content-disposition": (
                "attachment; filename*=UTF-8''"
                "%E9%9C%80%E6%B1%82%20%E6%96%87%E6%A1%A3.txt"
            )
        },
    )


@pytest.mark.parametrize("expires", [0, 301])
def test_oss_storage_rejects_out_of_bounds_signature_expiry(
    oss_storage, fake_oss_bucket, expires
):
    with pytest.raises(StorageError, match="invalid_expiration"):
        oss_storage.sign_part(OBJECT_KEY, "upload-1", 1, expires)
    assert not [call for call in fake_oss_bucket.calls if call[0] == "sign_url"]


def test_oss_sdk_logging_cannot_emit_access_ids_secrets_or_authorization(
    caplog, fake_oss_bucket
):
    access_id = "sensitive-access-id"
    access_secret = "sensitive-access-secret"
    signature = "sensitive-request-signature"
    sdk_logger = logging.getLogger("oss2.http")
    sdk_logger.disabled = False
    sdk_logger.propagate = True
    AliyunOssStorage(
        bucket_name="fde-test-bucket",
        access_key_id=access_id,
        access_key_secret=access_secret,
        client=fake_oss_bucket,
    )
    caplog.set_level(logging.DEBUG, logger="oss2")

    sdk_logger.warning(
        "headers Authorization=OSS %s:%s secret=%s",
        access_id,
        signature,
        access_secret,
    )

    captured = caplog.text
    assert access_id not in captured
    assert access_secret not in captured
    assert signature not in captured
    assert "Authorization" not in captured


def test_object_storage_extension_is_isolated_by_app_lifecycle(tmp_path):
    app_a = create_app(local_settings(tmp_path / "a"))
    app_b = create_app(local_settings(tmp_path / "b"))

    with app_a.app_context():
        first = object_storage.current
        assert first.root == (tmp_path / "a").resolve()
    with app_b.app_context():
        second = object_storage.current
        assert second.root == (tmp_path / "b").resolve()

    assert first is not second
    with pytest.raises(RuntimeError):
        _ = object_storage.current


def test_default_app_settings_use_the_function_scoped_tmp_directory(
    settings, tmp_path
):
    assert settings.local_storage_root.parent == tmp_path


def local_settings(storage_root: Path) -> Settings:
    return Settings(
        env="test",
        database_url="sqlite://",
        redis_url="redis://127.0.0.1:6379/15",
        jwt_secret="test-secret-with-at-least-thirty-two-characters",
        storage_backend="local",
        local_storage_root=storage_root,
    )


def storage_call(bucket: FakeOssBucket, method: str):
    return next(call for call in reversed(bucket.calls) if call[0] == method)


def request_target(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.path}?{parsed.query}"
