import base64

import pytest
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from fde_api.control.service import ControlServiceError
from fde_api.control.weixin_files import upload_attachment


class Transport:
    result = {"upload_param": "upload-secret"}

    def call(self, endpoint, **kwargs):
        assert endpoint == "getuploadurl"
        self.payload = kwargs["payload"]
        return self.result


def test_attachment_encryption_and_tencent_payload(monkeypatch):
    transport = Transport()
    sent = {}

    class Response:
        status_code = 200
        headers = {"x-encrypted-param": "download-secret"}
        def __enter__(self): return self
        def __exit__(self, *_): pass

    def post(url, **kwargs):
        sent.update(kwargs)
        assert url.startswith("https://novac2c.cdn.weixin.qq.com/c2c/upload?")
        assert kwargs["allow_redirects"] is False
        assert "Authorization" not in kwargs["headers"]
        return Response()

    monkeypatch.setattr("fde_api.control.weixin_files.requests.post", post)
    content = b"project-plan-progress-docx"
    item = upload_attachment(transport, credentials={"base_url": "https://ilinkai.weixin.qq.com", "bot_token": "secret", "ilink_user_id": "owner"}, content=content, filename="项目计划及进度.docx")
    media = item["file_item"]["media"]
    key = bytes.fromhex(base64.b64decode(media["aes_key"]).decode())
    decryptor = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
    padded = decryptor.update(sent["data"]) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    assert unpadder.update(padded) + unpadder.finalize() == content
    assert transport.payload["media_type"] == 3
    assert transport.payload["to_user_id"] == "owner"
    assert item["type"] == 4
    assert item["file_item"]["len"] == str(len(content))


@pytest.mark.parametrize("url", ["http://novac2c.cdn.weixin.qq.com/c2c/upload", "https://attacker.test/c2c/upload", "https://novac2c.cdn.weixin.qq.com:444/c2c/upload", "https://user@novac2c.cdn.weixin.qq.com/c2c/upload", "https://novac2c.cdn.weixin.qq.com/other"])
def test_attachment_rejects_untrusted_upload_target(url, monkeypatch):
    transport = Transport()
    transport.result = {"upload_full_url": url}
    monkeypatch.setattr("fde_api.control.weixin_files.requests.post", lambda *_a, **_k: pytest.fail("must not upload"))
    with pytest.raises(ControlServiceError, match="安全检查"):
        upload_attachment(transport, credentials={"base_url": "https://ilinkai.weixin.qq.com", "bot_token": "secret", "ilink_user_id": "owner"}, content=b"data", filename="file.docx")
