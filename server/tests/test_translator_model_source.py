"""goal-d14：翻译管道的模型来源（与 AI 聊天同源解析 + 可选 env 覆盖）。

拍板依据：蔡工无 kimi key，翻译改用「AI 聊天那个已经配置好的大模型」。

解析优先级（translator/jobs.py::_resolve_ai_target）：
1. env 覆盖：kimi 翻译槽位三件配齐 → 强制走 kimi-k3（留给将来拿到 key 的口子）；
2. 同源解析：模型偏好表（= AI 聊天的默认模型）优先，回落系统默认槽位；
3. 兜底：个人偏好不可用时回落系统默认槽位，不让一个人��偏好问题拖垮翻译。
"""
from __future__ import annotations

from cryptography.fernet import Fernet

from test_agents_d4_harness import d4_app, d4_client, d4_settings  # noqa: F401  (pytest fixture)
from test_metrics_report import _user
from test_translator_portal import PAYLOAD, _FakeDeepSeek, _headers, _job_for, _persist_user, _valid_contract_payload

from fde_api.control.model_preferences import ModelPreference
from fde_api.translator import jobs as translator_jobs
from fde_api.translator.models import TranslatorTranslation


def _capturing_client(monkeypatch) -> dict:
    """替换 DeepSeekClient 为捕获构造参数的替身，返回记录字典。"""
    captured: dict[str, object] = {}

    class _Capturing:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(translator_jobs, "DeepSeekClient", _Capturing)
    return captured


def _add_preference(db_session, d4_app, user, *, base_url: str, model: str, api_key: str, is_default: bool = True):
    """写一条模型偏好（密钥按产品口径加密入库）。"""
    cipher_key = Fernet.generate_key()
    d4_app.config["MODEL_CREDENTIAL_KEY"] = cipher_key
    item = ModelPreference(
        scope="personal", owner_user_id=user.id, name="测试模型", provider="openai-compatible",
        base_url=base_url, model=model,
        credential_ciphertext=Fernet(cipher_key).encrypt(api_key.encode()).decode(),
        is_default=is_default, supports_tools=True,
    )
    db_session.add(item)
    db_session.commit()
    return item


def test_preference_model_wins_over_system_default(db_session, d4_app, d4_settings, monkeypatch) -> None:
    """同源解析：模型偏好表里的默认模型优先于系统默认槽位。"""
    user = _persist_user(db_session)
    _add_preference(db_session, d4_app, user, base_url="https://api.example.com/v1",
                    model="example-model-1", api_key="preference-secret")
    captured = _capturing_client(monkeypatch)
    with d4_app.app_context():
        target = translator_jobs._resolve_ai_target(db_session, d4_settings, user.id)
        translator_jobs._client(d4_settings, target)
    assert target.source == "model_preference"
    assert target.base_url == "https://api.example.com/v1"
    assert target.model == "example-model-1"
    assert target.api_key == "preference-secret"
    assert captured["base_url"] == "https://api.example.com/v1"
    assert captured["model"] == "example-model-1"


def test_without_preference_falls_back_to_system_default(db_session, d4_app, d4_settings, monkeypatch) -> None:
    """没有偏好记录时回落系统默认槽位（AI 聊天同一条默认路径）。"""
    user = _persist_user(db_session)
    captured = _capturing_client(monkeypatch)
    with d4_app.app_context():
        target = translator_jobs._resolve_ai_target(db_session, d4_settings, user.id)
        translator_jobs._client(d4_settings, target)
    assert target.source == "system_default"
    assert target.base_url == d4_settings.deepseek_base_url
    assert target.model == d4_settings.deepseek_industry_template_model
    assert captured["base_url"] == d4_settings.deepseek_base_url
    assert captured["model"] == d4_settings.deepseek_industry_template_model


def test_env_override_wins_over_preference(db_session, d4_app, d4_settings, monkeypatch) -> None:
    """env 覆盖优先：kimi 翻译槽位配齐时强制走 kimi-k3（将来拿到 key 的口子）。"""
    user = _persist_user(db_session)
    _add_preference(db_session, d4_app, user, base_url="https://api.example.com/v1",
                    model="example-model-1", api_key="preference-secret")
    settings = d4_settings.model_copy(update={
        "kimi_translator_api_key": "env-secret",
        "kimi_translator_base_url": "https://api.moonshot.cn/v1",
        "kimi_translator_model": "kimi-k3",
    })
    captured = _capturing_client(monkeypatch)
    with d4_app.app_context():
        target = translator_jobs._resolve_ai_target(db_session, settings, user.id)
        translator_jobs._client(settings, target)
    assert target.source == "env_override"
    assert target.base_url == "https://api.moonshot.cn/v1"
    assert target.model == "kimi-k3"
    assert target.api_key == "env-secret"
    assert captured["model"] == "kimi-k3"


def test_broken_preference_credential_falls_back(db_session, d4_app, d4_settings, monkeypatch) -> None:
    """偏好密钥解不开时不抛错——回落系统默认槽位，翻译不停摆。"""
    user = _persist_user(db_session)
    cipher_key = Fernet.generate_key()
    d4_app.config["MODEL_CREDENTIAL_KEY"] = cipher_key
    db_session.add(ModelPreference(
        scope="personal", owner_user_id=user.id, name="坏密钥模型", provider="openai-compatible",
        base_url="https://api.example.com/v1", model="example-model-1",
        credential_ciphertext=Fernet(Fernet.generate_key()).encrypt(b"undecryptable").decode(),
        is_default=True, supports_tools=True,
    ))
    db_session.commit()
    with d4_app.app_context():
        target = translator_jobs._resolve_ai_target(db_session, d4_settings, user.id)
    assert target.source == "system_default"
    assert target.model == d4_settings.deepseek_industry_template_model


def test_no_credentials_anywhere_fails_classified(db_session, d4_app, d4_client, d4_settings, monkeypatch) -> None:
    """全链路都没有可用凭据时分类失败 ai_service_not_configured（不裸 500、不卡 running）。"""
    user = _persist_user(db_session)
    settings = d4_settings.model_copy(update={
        "deepseek_api_key": None,
        "kimi_translator_api_key": None,
    })
    # job 读的是 app 里的 SETTINGS，必须替换掉（局部副本不生效）。
    d4_app.config["SETTINGS"] = settings
    data = d4_client.post(
        "/api/v1/translator/translations", json=PAYLOAD, headers=_headers(user, settings)
    ).json["data"]
    job = _job_for(db_session, data["id"])
    with d4_app.app_context():
        translator_jobs.handle_translator_translate(job)
    row = db_session.get(TranslatorTranslation, data["id"])
    assert row.status == "failed"
    assert row.failure_code == "ai_service_not_configured"
    assert row.ai_model == ""  # 失败不虚标模型


def test_job_records_resolved_model(db_session, d4_app, d4_client, d4_settings) -> None:
    """端到端：ready 分支落账的 ai_model = 实际解析出的模型名。"""
    user = _persist_user(db_session)
    _add_preference(db_session, d4_app, user, base_url="https://api.example.com/v1",
                    model="example-model-1", api_key="preference-secret")
    fake = _FakeDeepSeek([_valid_contract_payload()])
    d4_app.extensions["fde_api_translator_ai"] = fake
    data = d4_client.post(
        "/api/v1/translator/translations", json=PAYLOAD, headers=_headers(user, d4_settings)
    ).json["data"]
    job = _job_for(db_session, data["id"])
    with d4_app.app_context():
        translator_jobs.handle_translator_translate(job)
    row = db_session.get(TranslatorTranslation, data["id"])
    assert row.status == "ready"
    assert row.ai_model == "example-model-1"
