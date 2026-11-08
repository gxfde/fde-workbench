"""结构口径同步钉（架构评估 P2-4：把「口径数字」变成机器可校验的单一来源）。

`docs/audit/v3-workbench-inventory.json` 是本仓**唯一的机器可读结构口径**
（路由数 / 蓝图数 / 表数 / 迁移数 / head / root）。此前它只是审计脚本的输出物，
没人校验它与现实是否一致——文档里引用的「391 路由 / 49 蓝图 / 130 表」因此
会在若干轮之后悄悄过期（AGENTS 口径纪律要求「引用前现测」，但没有机器保证
现测值与已发布清单一致）。

本模块把 JSON 与**独立重算**的现实逐项对账：

- 路由数 ← `create_app().url_map`（口径同 test_route_inventory_sync）；
- 蓝图数 ← `app.py::iter_blueprints()`（P2-5 的唯一权威注册表）；
- 表数   ← 导入全部模型模块后的 `Base.metadata.tables`；
- 迁移数 ← `migrations/versions/` 里声明了 revision 的文件数；
- head/root ← 迁移链图（head 恰好一个——与 P1-1 的单头闸互为印证）。

漂移即红，并给出重生成指引：跑
`python scripts/audit/extract_workbench_inventory.py` 后连同三份清单一起提交。
"""
from __future__ import annotations

import importlib
import json
import pkgutil
import re
from pathlib import Path

import fde_api
from fde_api.app import create_app, iter_blueprints
from fde_api.auth.models import Base

_REPO_ROOT = Path(__file__).resolve().parents[2]
_INVENTORY_JSON = _REPO_ROOT / "docs" / "audit" / "v3-workbench-inventory.json"
_MIGRATIONS_DIR = _REPO_ROOT / "server" / "migrations" / "versions"

# 不叫 models 的建表模块（表名就在这些模块里声明）
_EXTRA_TABLE_MODULES = (
    "fde_api.control.model_preferences",
    "fde_api.control.chat",
    "fde_api.control.lcsc_skills",
    "fde_api.system_configuration",
)

_REVISION_RE = re.compile(r'^revision(?::\s*str)?\s*=\s*["\']([\w]+)["\']', re.MULTILINE)
_DOWN_RE = re.compile(
    r'^down_revision(?::[^=]+)?\s*=\s*(["\'][\w]+["\']|None)', re.MULTILINE
)

_FIX_HINT = (
    "请运行 `python scripts/audit/extract_workbench_inventory.py` 重生成"
    "docs/audit/v3-workbench-inventory.json 与两份 CSV，并随本 PR 提交"
)


def _inventory() -> dict:
    return json.loads(_INVENTORY_JSON.read_text(encoding="utf-8"))


def _actual_routes(app) -> set[tuple[str, str]]:
    actual: set[tuple[str, str]] = set()
    for rule in app.url_map.iter_rules():
        if rule.endpoint == "static":
            continue
        methods = sorted(m for m in (rule.methods or []) if m not in {"HEAD", "OPTIONS"})
        actual.add(("|".join(methods), rule.rule))
    return actual


def _actual_table_count() -> int:
    importlib.import_module("fde_api.app")  # 蓝图模块传递导入模型模块
    for module in pkgutil.walk_packages(fde_api.__path__, prefix="fde_api."):
        if module.name.endswith("models") or module.name in _EXTRA_TABLE_MODULES:
            importlib.import_module(module.name)
    return len(Base.metadata.tables)


def _migration_graph() -> tuple[dict[str, str | None], list[str], list[str]]:
    """(revision → down_revision, heads, roots)。"""
    downs: dict[str, str | None] = {}
    for path in sorted(_MIGRATIONS_DIR.glob("*.py")):
        body = path.read_text(encoding="utf-8")
        revision_match = _REVISION_RE.search(body)
        if revision_match is None:
            continue
        down_match = _DOWN_RE.search(body)
        down = None
        if down_match and down_match.group(1) != "None":
            down = down_match.group(1).strip("\"'")
        downs[revision_match.group(1)] = down
    children = {down for down in downs.values() if down}
    heads = sorted(rev for rev in downs if rev not in children)
    roots = sorted(rev for rev, down in downs.items() if down is None)
    return downs, heads, roots


def test_inventory_route_count_matches_url_map(settings) -> None:
    """路由数 ≡ 实际 url_map（口径同 route CSV 同步钉）。"""
    app = create_app(settings)
    assert _inventory()["route_count"] == len(_actual_routes(app)), (
        f"inventory 的 route_count 与实际路由数漂移（清单 { _inventory()['route_count'] } "
        f"vs 实际 {len(_actual_routes(app))}）——{_FIX_HINT}"
    )


def test_inventory_blueprint_count_matches_registry() -> None:
    """蓝图数 ≡ 权威注册表产出数（P2-5 的单一来源）。"""
    actual = len(list(iter_blueprints()))
    assert _inventory()["blueprint_count"] == actual, (
        f"inventory 的 blueprint_count 漂移（清单 {_inventory()['blueprint_count']} "
        f"vs 实际 {actual}）——{_FIX_HINT}"
    )


def test_inventory_table_count_matches_metadata() -> None:
    """表数 ≡ Base.metadata 的表数。"""
    actual = _actual_table_count()
    assert _inventory()["table_count"] == actual, (
        f"inventory 的 table_count 漂移（清单 {_inventory()['table_count']} "
        f"vs 实际 {actual}）——{_FIX_HINT}"
    )


def test_inventory_revision_count_and_heads_match_chain() -> None:
    """迁移数与 head/root ≡ 迁移链图（head 恰好一个——与 P1-1 单头闸互为印证）。"""
    downs, heads, roots = _migration_graph()
    inventory = _inventory()
    assert inventory["revision_count"] == len(downs), (
        f"inventory 的 revision_count 漂移（清单 {inventory['revision_count']} "
        f"vs 实际 {len(downs)}）——{_FIX_HINT}"
    )
    assert sorted(inventory["heads"]) == heads, (
        f"inventory 的 heads 漂移（清单 {inventory['heads']} vs 实际 {heads}）——{_FIX_HINT}"
    )
    assert len(heads) == 1, f"迁移链必须恰好一个 head，实测 {heads}"
    assert sorted(inventory["roots"]) == roots, (
        f"inventory 的 roots 漂移（清单 {inventory['roots']} vs 实际 {roots}）——{_FIX_HINT}"
    )
