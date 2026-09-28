"""Tencent iLink file attachments; plaintext and CDN credentials never reach AI.

Protocol: Tencent/openclaw-weixin src/cdn/upload.ts and messaging/send.ts.
Only the fixed Tencent CDN is accepted, without redirects or bot auth headers.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
from urllib.parse import urlencode, urlparse

import requests
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from fde_api.control.service import ControlServiceError

MAX_ATTACHMENT_BYTES = 20_000_000  # Application safety limit, not a provider claim.
CDN_BASE = "https://novac2c.cdn.weixin.qq.com/c2c"


def upload_attachment(transport, *, credentials: dict, content: bytes, filename: str) -> dict:
    if not content or len(content) > MAX_ATTACHMENT_BYTES:
        raise ControlServiceError("weixin_file_size", "附件为空或超过 20 MB，请在文件库下载。", 409)
    key = secrets.token_bytes(16)
    padder = padding.PKCS7(128).padder()
    padded = padder.update(content) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()
    filekey = secrets.token_hex(16)
    result = transport.call("getuploadurl", base_url=credentials["base_url"], token=credentials["bot_token"], payload={
        "filekey": filekey, "media_type": 3, "to_user_id": credentials["ilink_user_id"],
        "rawsize": len(content), "rawfilemd5": hashlib.md5(content).hexdigest(),
        "filesize": len(ciphertext), "no_need_thumb": True, "aeskey": key.hex(),
    })
    url = result.get("upload_full_url") or ""
    if not url and isinstance(result.get("upload_param"), str) and result["upload_param"]:
        url = CDN_BASE + "/upload?" + urlencode({"encrypted_query_param": result["upload_param"], "filekey": filekey})
    try:
        parsed = urlparse(url)
        valid = (parsed.scheme == "https" and parsed.hostname == "novac2c.cdn.weixin.qq.com"
                 and parsed.port in {None, 443} and parsed.path == "/c2c/upload"
                 and not parsed.username and not parsed.password and not parsed.fragment)
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise ControlServiceError("weixin_invalid_cdn", "微信附件上传地址未通过安全检查。", 502)
    try:
        with requests.post(url, data=ciphertext, headers={"Content-Type": "application/octet-stream"},
                           timeout=(5, 45), allow_redirects=False, stream=True) as response:
            download = response.headers.get("x-encrypted-param")
            if response.status_code != 200 or not download or len(download) > 16384:
                raise ControlServiceError("weixin_upload_failed", "微信附件上传失败，文件仍保留在文件库。", 502)
    except requests.RequestException:
        raise ControlServiceError("weixin_upload_failed", "微信附件上传失败，文件仍保留在文件库。", 502) from None
    return {"type": 4, "file_item": {"media": {
        "encrypt_query_param": download,
        # Tencent expects base64 of the HEX STRING, not base64 of raw key bytes.
        "aes_key": base64.b64encode(key.hex().encode("ascii")).decode("ascii"), "encrypt_type": 1,
    }, "file_name": filename, "len": str(len(content))}}
