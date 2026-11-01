"""插件能力登记表种子（goal-d11，d6 挂账⑥收尾）。

lcsc.browse 等已知插件的 PluginPackage 种子数据：懒装载幂等（按 plugin_key
匹配，「存在即跳过」——种子演进不覆写现场，沿 agents/seeds.py 模式）。
capabilities 从 manifest_json["capabilities"] 读（_plugin_capabilities 消费
格式）；package_sha256 对种子行规范化 JSON 计算（登记完整性指纹）。
"""
from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from fde_api.auth.models import User
from fde_api.control.models import PluginPackage

_SEEDS_PATH = Path(__file__).resolve().parents[3] / "seeds" / "plugin_packages.json"


def _plugin_seeds() -> tuple[dict[str, Any], ...]:
    payload = json.loads(_SEEDS_PATH.read_text(encoding="utf-8"))
    rows = payload.get("plugins") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("plugin_packages.json seed empty")
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("plugin_key"), str):
            raise RuntimeError("plugin_packages.json seed row invalid")
        manifest = row.get("manifest")
        if not isinstance(manifest, dict) or not isinstance(manifest.get("capabilities"), list):
            raise RuntimeError("plugin seed manifest.capabilities missing")
    return tuple(rows)


def ensure_plugin_seeds(session: Session, actor: User) -> int:
    """幂等装载种子插件，返回新建行数。匹配键 = plugin_key。"""
    existing = set(
        session.scalars(select(PluginPackage.plugin_key)).all()
    )
    created = 0
    for row in _plugin_seeds():
        plugin_key = str(row["plugin_key"])
        if plugin_key in existing:
            continue
        canonical = json.dumps(row, ensure_ascii=False, sort_keys=True)
        session.add(
            PluginPackage(
                plugin_key=plugin_key,
                name=str(row["name"]),
                description=str(row.get("description") or ""),
                publisher=str(row.get("publisher") or ""),
                current_version=str(row.get("current_version") or "1.0.0"),
                manifest_json=dict(row.get("manifest") or {}),
                package_sha256=sha256(canonical.encode("utf-8")).hexdigest(),
                verified=bool(row.get("verified", False)),
                status="active",
                created_by_user_id=actor.id,
                source=str(row.get("source") or "internal"),
                category=str(row.get("category") or ""),
            )
        )
        created += 1
    if created:
        session.flush()
    return created
