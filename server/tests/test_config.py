import pytest
from pydantic import ValidationError

from fde_api.config import Settings


BASE_SETTINGS = {
    "_env_file": None,
    "database_url": "sqlite://",
    "redis_url": "redis://127.0.0.1:6379/15",
    "jwt_secret": "test-secret-with-at-least-thirty-two-characters",
}


def test_shared_environment_template_ignores_desktop_only_keys(
    monkeypatch, tmp_path
):
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "FDE_ENV=development",
                "FDE_DATABASE_URL=mysql+pymysql://local:test@127.0.0.1/fde_workbench",
                "FDE_REDIS_URL=redis://127.0.0.1:6379/2",
                "FDE_JWT_SECRET=local-secret-with-at-least-thirty-two-characters",
                "FDE_DESKTOP_API_URL=http://127.0.0.1:8010",
                "FDE_OSS_BUCKET=fde-test-bucket",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    settings = Settings()

    assert settings.database_url.endswith("/fde_workbench")


def test_development_and_test_default_to_local_storage_without_oss_credentials():
    development = Settings(env="development", **BASE_SETTINGS)
    test = Settings(env="test", **BASE_SETTINGS)

    assert development.storage_backend == "local"
    assert test.storage_backend == "local"


def test_production_supports_local_storage_for_self_hosting():
    settings = Settings(env="production", storage_backend="local", **BASE_SETTINGS)
    assert settings.storage_backend == "local"


@pytest.mark.parametrize(
    "missing",
    [
        "oss_endpoint",
        "oss_bucket",
        "oss_access_key_id",
        "oss_access_key_secret",
    ],
)
def test_oss_backend_requires_all_four_oss_environment_values(missing):
    values = {
        "oss_endpoint": "https://oss-cn.example.invalid",
        "oss_bucket": "fde-test-bucket",
        "oss_access_key_id": "new-test-access-id",
        "oss_access_key_secret": "new-test-access-secret",
    }
    values.pop(missing)

    with pytest.raises(ValidationError, match="missing_oss_configuration"):
        Settings(env="test", storage_backend="oss", **values, **BASE_SETTINGS)


def test_production_accepts_operator_selected_oss_bucket():
    settings = Settings(
        env="production",
        storage_backend="oss",
        oss_endpoint="https://oss-cn.example.invalid",
        oss_bucket="fde-production-bucket",
        oss_access_key_id="new-production-access-id",
        oss_access_key_secret="new-production-access-secret",
        **BASE_SETTINGS,
    )

    assert settings.oss_bucket == "fde-production-bucket"


def test_access_keys_are_secret_and_never_appear_in_repr_or_validation_error():
    access_id = "sensitive-access-key-id"
    access_secret = "sensitive-access-key-secret"
    settings = Settings(
        env="test",
        storage_backend="oss",
        oss_endpoint="https://oss-cn.example.invalid",
        oss_bucket="fde-test-bucket",
        oss_access_key_id=access_id,
        oss_access_key_secret=access_secret,
        **BASE_SETTINGS,
    )

    assert access_id not in repr(settings)
    assert access_secret not in repr(settings)
    assert settings.oss_access_key_id.get_secret_value() == access_id
    assert settings.oss_access_key_secret.get_secret_value() == access_secret

    assert access_id not in repr(settings)
    assert access_secret not in repr(settings)


def test_deepseek_key_is_optional_and_secret():
    without_key = Settings(env="test", **BASE_SETTINGS)
    assert without_key.deepseek_api_key is None

    secret = "industry-template-test-secret"
    settings = Settings(
        env="test",
        deepseek_api_key=secret,
        **BASE_SETTINGS,
    )

    assert settings.deepseek_api_key.get_secret_value() == secret
    assert secret not in repr(settings)
    assert settings.deepseek_industry_template_model == "deepseek-v4-pro"


def test_kimi_presurvey_key_is_optional_and_secret():
    without_key = Settings(env="test", **BASE_SETTINGS)
    assert without_key.kimi_project_presurvey_api_key is None

    secret = "kimi-presurvey-test-secret"
    settings = Settings(env="test", kimi_project_presurvey_api_key=secret, **BASE_SETTINGS)

    assert settings.kimi_project_presurvey_api_key.get_secret_value() == secret
    assert secret not in repr(settings)
    assert settings.kimi_project_presurvey_model == "kimi-k3"


def test_dsh_is_disabled_by_default_and_requires_a_service_token_when_enabled():
    settings = Settings(env="test", **BASE_SETTINGS)
    assert settings.dsh_enabled is False
    assert settings.dsh_runtime_version == "unconfigured"

    with pytest.raises(ValidationError, match="missing_dsh_service_token"):
        Settings(env="test", dsh_enabled=True, dsh_runtime_version="1.2.3", **BASE_SETTINGS)

    enabled = Settings(
        env="test",
        dsh_enabled=True,
        dsh_service_token="private-dsh-token",
        dsh_runtime_version="1.2.3",
        **BASE_SETTINGS,
    )
    assert enabled.dsh_service_token.get_secret_value() == "private-dsh-token"
    assert "private-dsh-token" not in repr(enabled)

def test_dsh_market_is_disabled_by_default_and_requires_https_in_production():
    settings = Settings(env="test", **BASE_SETTINGS)
    assert settings.dsh_market_enabled is False
    assert settings.dsh_market_registry_url == "https://example.com/plugins.json"

    with pytest.raises(ValidationError, match="invalid_dsh_market_registry_url"):
        Settings(
            env="production",
            dsh_market_enabled=True,
            dsh_market_registry_url="http://market.example.invalid/plugins.json",
            **BASE_SETTINGS,
        )
def test_clawbot_gateway_is_disabled_by_default_and_requires_a_secret():
    settings = Settings(env="test", **BASE_SETTINGS)
    assert settings.clawbot_enabled is False
    assert settings.clawbot_gateway_token is None

    with pytest.raises(ValidationError, match="missing_clawbot_gateway_token"):
        Settings(env="test", clawbot_enabled=True, **BASE_SETTINGS)

    enabled = Settings(
        env="test",
        clawbot_enabled=True,
        clawbot_gateway_token="private-clawbot-token",
        **BASE_SETTINGS,
    )
    assert enabled.clawbot_gateway_token.get_secret_value() == "private-clawbot-token"
    assert "private-clawbot-token" not in repr(enabled)
