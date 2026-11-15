"""Ontology 开关配置测试（纯 Settings 校验，不依赖 MySQL）。"""

from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from fde_api.config import Settings

# **kwargs 展开进 pydantic-settings 构造器无法被类型桩精确建模——与其他 Settings 测试同惯例
_BASE: dict[str, str] = {
    "database_url": "mysql+pymysql://u:p@127.0.0.1:3306/x",
    "redis_url": "redis://127.0.0.1:6379/2",
    "jwt_secret": "test-secret-with-at-least-thirty-two-characters",
}


def _make(**extra: object) -> Settings:
    return Settings(env="test", **_BASE, **extra)  # type: ignore[arg-type]


def test_ontology_disabled_by_default() -> None:
    settings = _make()
    assert settings.ontology_enabled is False
    assert settings.ontology_api_key is None


def test_ontology_enabled_requires_auth_material() -> None:
    with pytest.raises(ValidationError, match="FDE_ONTOLOGY"):
        _make(ontology_enabled=True)


def test_ontology_enabled_requires_base_url() -> None:
    """D10 段 2：org 上下文取自项目归属（不再由配置提供）；base_url 空仍是配置错误。"""
    with pytest.raises(ValidationError, match="FDE_ONTOLOGY"):
        _make(
            ontology_enabled=True,
            ontology_api_key=SecretStr("k"),
            ontology_signing_key=SecretStr("s"),
            ontology_base_url=" ",
        )


def test_ontology_enabled_with_material_ok() -> None:
    settings = _make(
        ontology_enabled=True,
        ontology_api_key=SecretStr("k"),
        ontology_signing_key=SecretStr("s"),
    )
    assert settings.ontology_enabled is True
    # D10 段 2：FDE_ONTOLOGY_ORG_ID 配置已退役——org 上下文唯一来源=项目归属
    assert not hasattr(settings, "ontology_org_id")
    # 契约 §1 预留字段（M3 起）已声明
    assert settings.ontology_model_endpoint == ""
    # M5-WP2 S-16：全局降级闸缺省 per_gate（集成契约 §0；空串 env 显式值归一）
    assert settings.ontology_gate_dependency == "per_gate"
