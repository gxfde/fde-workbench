import pytest

from fde_api.guidance.redaction import SensitiveCredentialDetected, redact_text


def test_redacts_contacts_but_keeps_business_context():
    result = redact_text("联系人张三 13800138000 zhang@example.com ERP MES")
    assert "13800138000" not in result
    assert "zhang@example.com" not in result
    assert "ERP MES" in result


def test_blocks_api_keys():
    with pytest.raises(SensitiveCredentialDetected):
        redact_text("接口密钥：example-api-key-not-real-123456")
