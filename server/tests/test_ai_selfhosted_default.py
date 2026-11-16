"""AF1-WP1 定参④：自托管默认档（docs/ai-fde/09 §2.2 方案 B①，P1 已批）。

resolve_model_preference 的 system-default 档：配置了 ai_selfhosted_* 时
先于 deepseek_* 槽位解析（红线：客户敏感数据不默认发公共模型）；未配置
回落既有槽位（向后兼容）。
"""
from __future__ import annotations

import pytest

from fde_api.auth.models import User
from fde_api.control.model_preferences import resolve_model_preference


@pytest.fixture
def pref_user(app, db_session):
    user = User(
        username=f"selfhost-{id(db_session)}",
        display_name="selfhost",
        password_hash="unused",
        role="admin",
        is_active=True,
        must_change_password=False,
    )
    db_session.add(user)
    db_session.commit()
    return user


def test_selfhosted_endpoint_wins_system_default(app, db_session, pref_user, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app.config["SETTINGS"], "ai_selfhosted_base_url", "http://127.0.0.1:11434/v1")
    monkeypatch.setattr(app.config["SETTINGS"], "ai_selfhosted_model", "qwen3:14b")
    out = resolve_model_preference(db_session, pref_user.id)
    assert out["id"] == "system-selfhosted"
    assert out["base_url"] == "http://127.0.0.1:11434/v1"
    assert out["model"] == "qwen3:14b"
    # 本地端点不校验凭据：留空 → 显式占位（直连契约要求非空；非真实凭据）
    assert out["api_key"] == "selfhosted-local"
    assert out["supports_tools"] is True


def test_explicit_api_key_is_preserved(app, db_session, pref_user, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app.config["SETTINGS"], "ai_selfhosted_base_url", "http://10.0.0.8:8000/v1")
    monkeypatch.setattr(app.config["SETTINGS"], "ai_selfhosted_model", "qwen3-32b")
    monkeypatch.setattr(app.config["SETTINGS"], "ai_selfhosted_api_key", "lan-token-1")
    out = resolve_model_preference(db_session, pref_user.id)
    assert out["api_key"] == "lan-token-1"
    # 私网网关名不出现在 provider 标签（_provider_for_base_url 兜底 openai-compatible）
    assert out["provider"] == "openai-compatible"


def test_without_selfhosted_config_falls_through_to_deepseek_slot(app, db_session, pref_user) -> None:
    """未配置自托管 → 落回 deepseek_* 槽位路径。

    CI 测试环境无 deepseek_api_key → 该槽位的正确行为是 fail-closed
    model_not_configured（409 要求先配置模型）——断言的是「走了回落路径」
    而非成功解析（自托管分支若误判，这里会拿到 system-selfhosted）。
    """
    from fde_api.control.service import ControlServiceError

    with pytest.raises(ControlServiceError) as excinfo:
        resolve_model_preference(db_session, pref_user.id)
    assert excinfo.value.code == "model_not_configured"


def test_explicit_default_preference_beats_selfhosted(app, db_session, pref_user, monkeypatch: pytest.MonkeyPatch) -> None:
    """三分序钉：显式偏好行（用户/公共 default）恒最优先于自托管系统档。"""
    from fde_api.control.model_preferences import ModelPreference, _cipher

    monkeypatch.setattr(app.config["SETTINGS"], "ai_selfhosted_base_url", "http://127.0.0.1:11434/v1")
    monkeypatch.setattr(app.config["SETTINGS"], "ai_selfhosted_model", "qwen3:14b")
    db_session.add(ModelPreference(
        owner_user_id=pref_user.id,
        scope="personal",
        name="自托管对照-云端偏好行",
        provider="deepseek",
        base_url="https://api.deepseek.com",
        model="deepseek-chat",
        supports_tools=True,
        is_default=True,
        credential_ciphertext=_cipher().encrypt(b"pref-key").decode(),
    ))
    db_session.commit()
    out = resolve_model_preference(db_session, pref_user.id)
    assert out["id"] != "system-selfhosted"
    assert out["model"] == "deepseek-chat"
