"""OSS / object-storage contract acceptance tests.

These tests exercise the SAME ``ObjectStorage`` contract against the
application's configured adapter. When ``FDE_RUN_OSS_TESTS`` is ``"1"`` and the
required OSS environment variables are present they run against a real Aliyun
OSS bucket; otherwise (the default) they run against the bundled
``LocalObjectStorage`` adapter so the whole contract can be exercised locally
without cloud credentials.

Run explicitly with::

    cd server
    .venv/bin/python -m pytest tests/integration/test_oss_contract.py -q -m oss

Real OSS requires ``FDE_RUN_OSS_TESTS=1`` plus ``FDE_OSS_ENDPOINT``,
``FDE_OSS_BUCKET``, ``FDE_OSS_ACCESS_KEY_ID`` and ``FDE_OSS_ACCESS_KEY_SECRET``.
"""

from __future__ import annotations

import os
from io import BytesIO
from uuid import uuid4

import pytest

from fde_api.app import create_app
from fde_api.extensions import object_storage
from fde_api.storage import AliyunOssStorage, StorageError

pytestmark = pytest.mark.oss

#: Environment variables required to build a real OSS adapter.
REQUIRED_OSS_ENV = (
    "FDE_OSS_ENDPOINT",
    "FDE_OSS_BUCKET",
    "FDE_OSS_ACCESS_KEY_ID",
    "FDE_OSS_ACCESS_KEY_SECRET",
)


@pytest.fixture
def oss_storage(monkeypatch, test_settings, tmp_path):
    """Return the storage adapter the application would use for this run.

    FDE_RUN_OSS_TESTS=1 -> a real ``AliyunOssStorage`` built from ``Settings``
    (skipped when the required OSS settings are missing). Otherwise (default)
    the local adapter is used so no cloud credentials are ever required.
    """
    run_oss = os.environ.get("FDE_RUN_OSS_TESTS") == "1"
    if run_oss:
        missing = [name for name in REQUIRED_OSS_ENV if not os.environ.get(name)]
        if missing:
            pytest.skip(
                "FDE_RUN_OSS_TESTS=1 requires "
                + ", ".join(missing)
                + " to be set."
            )
        settings = test_settings.model_copy(
            update={
                "storage_backend": "oss",
                "oss_endpoint": os.environ["FDE_OSS_ENDPOINT"],
                "oss_bucket": os.environ["FDE_OSS_BUCKET"],
                "oss_access_key_id": os.environ["FDE_OSS_ACCESS_KEY_ID"],
                "oss_access_key_secret": os.environ["FDE_OSS_ACCESS_KEY_SECRET"],
            }
        )
    else:
        settings = test_settings.model_copy(
            update={
                "storage_backend": "local",
                "local_storage_root": tmp_path / "object-storage",
            }
        )

    app = create_app(settings)
    # A request context keeps the local adapter's base_url_provider working for
    # ``sign_download``; the OSS adapter ignores it, so this is harmless there.
    with app.app_context(), app.test_request_context(
        base_url="http://127.0.0.1:8010"
    ):
        # When explicitly opted in, verify a genuine OSS adapter is wired rather
        # than the local fallback before handing it to the tests.
        if run_oss:
            storage = object_storage.current
            assert isinstance(storage, AliyunOssStorage), (
                "FDE_RUN_OSS_TESTS=1 must resolve to the AliyunOssStorage adapter."
            )
        yield object_storage.current


@pytest.fixture
def unique_project_id() -> str:
    """A unique, run-scoped project id used to scope every test object key."""
    return f"e2e-{uuid4().hex[:12]}"


def test_real_or_local_bucket_object_stays_under_project_prefix(
    oss_storage, unique_project_id
):
    """A written object lives under exactly the project prefix, and is deleted."""
    key = (
        f"projects/{unique_project_id}/attachments/f1/versions/v1/test.txt"
    )
    try:
        stored = oss_storage.put_stream(key, BytesIO(b"proof"), "text/plain", {})
        assert stored.key == key
        assert oss_storage.head(key).size == 5
        assert key.startswith(f"projects/{unique_project_id}/")
        # The key must never escape the owning project's prefix.
        assert key.split("/", 2) == [
            "projects",
            unique_project_id,
            "attachments/f1/versions/v1/test.txt",
        ]
    finally:
        oss_storage.delete(key)
        with pytest.raises(StorageError):
            oss_storage.head(key)


def test_storage_contract_round_trip(oss_storage, unique_project_id):
    """put_stream / open_stream / head / copy / sign_download round-trip."""
    key = f"projects/{unique_project_id}/attachments/f1/versions/v1/test.txt"
    copied_key = (
        f"projects/{unique_project_id}/attachments/f1/versions/v2/copy.txt"
    )
    try:
        stored = oss_storage.put_stream(
            key, BytesIO(b"hello"), "text/plain", {"source": "contract"}
        )
        assert stored.key == key
        assert stored.size == 5
        assert stored.content_type == "text/plain"

        assert oss_storage.open_stream(key).read() == b"hello"

        head = oss_storage.head(key)
        assert head.size == 5
        assert head.etag
        assert head.metadata.get("source") == "contract"

        copied = oss_storage.copy(key, copied_key)
        assert copied.key == copied_key
        assert oss_storage.open_stream(copied_key).read() == b"hello"

        signed_url = oss_storage.sign_download(key, "test.txt", 300)
        assert isinstance(signed_url, str) and signed_url
    finally:
        oss_storage.delete(key)
        oss_storage.delete(copied_key)
