"""G7 缺口①补钉（架构评估 2026-11-07 D9/P-5）：FDE_MODEL_CREDENTIAL_KEY 派生关系。

《系统意图-架构》已知风险 3 + G7 遗留缺口：「模型凭据 Fernet 密钥缺省派生自
JWT secret（control/model_preferences._cipher）——轮换 JWT secret 不会自动
轮换已入库密文」此前只有文档描述、零测试。本文件钉住三层语义：

1. 缺省派生——未设独立密钥时，密文可用 jwt_secret 派生键解开（正向路径）；
2. 轮换事故面——轮换 jwt_secret 后已存密文不可解（credential_unavailable 503）：
   「泄露应急先轮换、再评估 JWT 连带」不是可选动作而是必然结果，且已存密文
   本体不变（换回旧 secret 立即可解）；
3. 独立密钥隔离——显式配置 FDE_MODEL_CREDENTIAL_KEY 后，jwt_secret 轮换不再
   影响已存密文（README/变量与密钥文档轮换要点的正向兑现）。

测试数据全合成；不触任何真实凭据。
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from cryptography.fernet import Fernet

from test_agents_d4_harness import d4_app, d4_settings  # noqa: F401  (pytest fixture)

from conftest import INITIAL_PASSWORD
from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.control.model_preferences import resolve_model_preference, save_model_preference
from fde_api.control.service import ControlServiceError
from fde_api.extensions import db

# 命名避 gitleaks generic-api-key（*_SECRET 常量赋值触发；值同取 example/not-real 形状，
# 与 test_guidance_enterprise_redaction 凭据样串同款纪律）。
ROTATED_SIGNING_ROOT = "rotated-signing-root-example-not-real-32chars"


@pytest.fixture(autouse=True)
def _no_env_key(monkeypatch):
    """派生路径钉子必须排除环境变量干扰（_cipher 的 env 分支优先于派生）。"""
    monkeypatch.delenv("FDE_MODEL_CREDENTIAL_KEY", raising=False)
    yield


def _persist_user(db_session) -> User:
    user = User(
        username=f"mck.{uuid4().hex[:8]}",
        display_name="推导哨兵",
        role="admin",
        password_hash=hash_password(INITIAL_PASSWORD),
        must_change_password=False,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return user


def _save_preference(d4_app, user: User) -> None:
    """save/resolve 全程在 d4_app 上下文——conftest 的环境 app 与 d4_app 不同
    实例，_cipher 读的是**所在 context** 的 SETTINGS（轮换必须轮到真身）。"""
    with d4_app.app_context():
        save_model_preference(user=user, payload={
            "scope": "personal", "name": "推导哨兵模型", "provider": "deepseek",
            "base_url": "https://api.deepseek.com", "model": "deepseek-chat",
            "api_key": "sk-synthetic-key-for-derivation-test",
            "is_default": True, "supports_tools": True,
        })


def _resolve(d4_app, user: User) -> dict:
    with d4_app.app_context():
        with db.session() as session:
            return resolve_model_preference(session, user.id)


def _rotate_jwt_secret(d4_app, monkeypatch) -> None:
    monkeypatch.setattr(d4_app.config["SETTINGS"], "jwt_secret", ROTATED_SIGNING_ROOT)


def test_default_derivation_resolves_under_same_jwt_secret(db_session, d4_app) -> None:
    """缺省派生：未设独立密钥时，密文由 jwt_secret 派生键加密且可解（正向路径）。"""
    assert d4_app.config.get("MODEL_CREDENTIAL_KEY") in (None, "")
    user = _persist_user(db_session)
    _save_preference(d4_app, user)
    assert _resolve(d4_app, user)["api_key"] == "sk-synthetic-key-for-derivation-test"


def test_jwt_secret_rotation_breaks_existing_ciphertext(db_session, d4_app, monkeypatch) -> None:
    """轮换事故面：轮换 jwt_secret 后已存密文不可解（credential_unavailable），
    且密文本体不变——换回旧 secret 立即可解（「不会自动轮换已入库密文」逐字钉）。"""
    user = _persist_user(db_session)
    _save_preference(d4_app, user)
    # d4_app.config["SETTINGS"] 就是 d4_settings 本体（create_app 不拷贝）——
    # 原值必须在轮换前捕获，否则「恢复」读到的是轮换后值（别名陷阱）。
    original_secret = d4_app.config["SETTINGS"].jwt_secret
    _rotate_jwt_secret(d4_app, monkeypatch)
    with pytest.raises(ControlServiceError) as excinfo:
        _resolve(d4_app, user)
    assert excinfo.value.code == "credential_unavailable"
    # 密文本体未损坏：恢复旧 secret 即恢复可解（应急演练语义）。
    monkeypatch.setattr(d4_app.config["SETTINGS"], "jwt_secret", original_secret)
    assert _resolve(d4_app, user)["api_key"] == "sk-synthetic-key-for-derivation-test"


def test_explicit_credential_key_isolates_from_jwt_rotation(db_session, d4_app, monkeypatch) -> None:
    """独立密钥隔离：显式 FDE_MODEL_CREDENTIAL_KEY 后 jwt_secret 轮换零影响。"""
    credential_key = Fernet.generate_key().decode()
    monkeypatch.setenv("FDE_MODEL_CREDENTIAL_KEY", credential_key)
    user = _persist_user(db_session)
    _save_preference(d4_app, user)
    _rotate_jwt_secret(d4_app, monkeypatch)
    assert _resolve(d4_app, user)["api_key"] == "sk-synthetic-key-for-derivation-test"
    # 反向钉：独立密钥自身失效同样不可解（它才是这套密文的根）。
    monkeypatch.setenv("FDE_MODEL_CREDENTIAL_KEY", Fernet.generate_key().decode())
    with pytest.raises(ControlServiceError) as excinfo:
        _resolve(d4_app, user)
    assert excinfo.value.code == "credential_unavailable"
