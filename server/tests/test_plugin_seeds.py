"""goal-d11：插件能力登记表种子（d6 挂账⑥收尾）。

- ensure_plugin_seeds 懒装载幂等：按 plugin_key 匹配，存在即跳过。
- 种子行 capabilities 从 manifest_json 读（_plugin_capabilities 消费格式），
  且全部在 CAPABILITY_REQUIREMENTS 白名单内（lcsc.browse 等）。
- extensions_center 首次进入触发装载（集成路径）。
"""
from __future__ import annotations

from sqlalchemy import select

from test_agents_d4_harness import d4_app, d4_client, d4_settings  # noqa: F401  (pytest fixture)
from test_metrics_report import _user

from conftest import INITIAL_PASSWORD
from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.control.access import CAPABILITY_REQUIREMENTS
from fde_api.control.models import PluginPackage
from fde_api.control.plugin_seeds import ensure_plugin_seeds


def _admin(db_session) -> User:
    user = _user("plugin.seed", "admin")
    db_session.add(user)
    db_session.commit()
    return user


def test_plugin_seeds_load_idempotent(db_session) -> None:
    admin = _admin(db_session)
    first = ensure_plugin_seeds(db_session, admin)
    db_session.commit()
    second = ensure_plugin_seeds(db_session, admin)
    db_session.commit()
    assert first > 0
    assert second == 0
    keys = set(db_session.scalars(select(PluginPackage.plugin_key)).all())
    assert "lcsc-browser-baseline" in keys
    assert "lcsc-browser-jev" in keys


def test_plugin_seed_capabilities_in_catalog(db_session) -> None:
    """种子的 capabilities 必须落在平台能力白名单内（登记表不是越权后门）。"""
    admin = _admin(db_session)
    ensure_plugin_seeds(db_session, admin)
    db_session.commit()
    from fde_api.control.extensions_service import _plugin_capabilities

    for plugin in db_session.scalars(select(PluginPackage)).all():
        capabilities = _plugin_capabilities(plugin)
        assert capabilities, plugin.plugin_key
        assert set(capabilities) <= set(CAPABILITY_REQUIREMENTS), plugin.plugin_key
