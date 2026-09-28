from __future__ import annotations

import re

from fde_api.guidance.docx_extract import ExtractedBlock, ExtractedPresurvey


class SensitiveCredentialDetected(ValueError):
    pass


_CREDENTIAL = re.compile(
    r"(?:密码|口令|密钥|secret|api[_ -]?key|access[_ -]?token|token)\s*[:：=]?\s*"
    r"(?:sk-|ak-|bearer\s+)?[A-Za-z0-9_./+=-]{12,}", re.IGNORECASE
)
_EMAIL = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
_MOBILE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_LANDLINE = re.compile(r"(?<!\d)(?:0\d{2,3}[- ]?)?\d{7,8}(?!\d)")
_ID_CARD = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")


def redact_text(value: str) -> str:
    if _CREDENTIAL.search(value):
        raise SensitiveCredentialDetected("文档中疑似包含密码、密钥或令牌，请移除后重试。")
    value = _EMAIL.sub("[邮箱已脱敏]", value)
    value = _MOBILE.sub("[手机号已脱敏]", value)
    value = _ID_CARD.sub("[证件号已脱敏]", value)
    return _LANDLINE.sub("[电话已脱敏]", value)


def redact_presurvey(extracted: ExtractedPresurvey) -> ExtractedPresurvey:
    return ExtractedPresurvey(tuple(
        ExtractedBlock(block.source_ref, redact_text(block.text))
        for block in extracted.blocks
    ))
