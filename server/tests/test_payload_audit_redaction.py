"""S03 拍板落地钉（批5 决策单，2026-11-18 P1「全部批准」）：工具载荷落库
脱敏——``payload_audit.audit_payload`` 键名命中即遮蔽。

红线依据（任务书 §15：凭据不明文存储/不进日志；05 §4.1 S03 挂账）：载荷
来自白名单工具实参/返回，其中 ``ontology_dry_validate.proposed_json`` 携带
``evidence_quote``（逐字摘自客户材料）——材料含凭据/PII 时旧实现明文落库。

契约（决策单③推荐案）：
- 键名白名单命中（password/secret/token/api_key/authorization/cookie/
  credential/private_key，大小写与分隔符归一后匹配）→ 值替换固定掩码，
  键名保留；
- 截断逻辑与 ``payload_truncated`` 标记语义零变化；
- best-effort 契约零变化（脱敏失败不改变工具结果，落 NULL）。
"""
from __future__ import annotations

import json

from fde_api.control.payload_audit import audit_payload

MASK = "***redacted***"


def _json_loads(text: str | None) -> dict:
    assert text is not None
    data = json.loads(text)
    assert isinstance(data, dict)
    return data


def test_sensitive_keys_masked_keys_visible() -> None:
    """掩码后键名可见、值不可见（决策单③验收口径）。"""
    payload = {
        "password": "hunter2",
        "api_key": "sk-123",
        "AUTHORIZATION": "Bearer abc",
        "db_password": "pw!",          # 分隔符/大小写归一后命中
        "privateKey": "-----BEGIN",
        "normal_field": "visible",
    }
    text, truncated = audit_payload(payload)
    assert truncated is False
    data = _json_loads(text)
    assert data["password"] == MASK
    assert data["api_key"] == MASK
    assert data["AUTHORIZATION"] == MASK
    assert data["db_password"] == MASK
    assert data["privateKey"] == MASK
    assert data["normal_field"] == "visible"


def test_nested_and_list_payloads_masked() -> None:
    payload = {
        "items": [{"access_token": "tok-1", "note": "keep"}, {"deep": {"client_secret": "s"}}],
    }
    text, _ = audit_payload(payload)
    data = _json_loads(text)
    assert data["items"][0]["access_token"] == MASK
    assert data["items"][0]["note"] == "keep"
    assert data["items"][1]["deep"]["client_secret"] == MASK


def test_truncation_semantics_unchanged() -> None:
    """截断逻辑零变化：64KB 上限与标记行为不受脱敏影响。"""
    from fde_api.control.payload_audit import MAX_AUDIT_PAYLOAD_BYTES

    big = {"blob": "x" * (MAX_AUDIT_PAYLOAD_BYTES + 1024)}
    text, truncated = audit_payload(big)
    assert truncated is True
    assert text is not None
    assert text.endswith('…"payload_truncated":true')
    # 掩码不产生假截断
    small, truncated = audit_payload({"password": "x" * 10})
    assert truncated is False
    assert small is not None
    assert MASK in small


def test_best_effort_contract_unchanged() -> None:
    """None → (None, False)；default=str 兜底契约保持；脱敏失败不炸判定面。"""
    assert audit_payload(None) == (None, False)
    # 既有契约：default=str 兜底（set 转字符串）——脱敏不改变该行为
    text, truncated = audit_payload({1, 2})
    assert truncated is False
    assert text is not None
    # 自引用不炸（RecursionError 捕获面）
    selfref: dict = {}
    selfref["self"] = selfref
    result_text, _ = audit_payload(selfref)
    assert result_text is None or isinstance(result_text, str)
