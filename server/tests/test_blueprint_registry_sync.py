"""蓝图注册表同步钉（架构评估 P2-5：把「记得同步清单」变成结构不可能）。

此前蓝图登记有两份真身——`server/src/fde_api/app.py` 的注册序，与
`scripts/audit/extract_workbench_inventory.py` 里照抄的硬编码 BLUEPRINTS 清单。
两份真身必然漂移，且已漏条三次（T-J2/CR-027 的两个 admin 面板、#145 的
fact_chain_blueprint、#177 前审计）：AGENTS 的「审计清单刷新有前置条件」是
**流程纪律**，人记得住一次、记不住十次。

现在真身只有一份：`app.py::_BLUEPRINT_SPECS`，经 `iter_blueprints()` 出货。
本模块钉三件事：

1. **双向集合相等**：权威表导出的蓝图名 ≡ `create_app()` 实际注册出的名字
   （漏一条、多一条都红）；
2. **不得重名**：同名蓝图注册会被 Flask 静默覆盖（比漏条更阴）；
3. **不得绕过注册表**：app.py 源码里除注册表循环外不得出现直接
   `app.register_blueprint(` 调用——绕过即意味着又开了一份真身。
"""
from __future__ import annotations

import re
from pathlib import Path

from fde_api.app import _BLUEPRINT_SPECS, create_app, iter_blueprints

_APP_SOURCE = Path(__file__).resolve().parents[1] / "src" / "fde_api" / "app.py"


def test_blueprint_registry_matches_registered_app(settings) -> None:
    """权威注册表 ≡ 实际注册（双向名字集合）。"""
    app = create_app(settings)
    derived = sorted(bp.name for bp in iter_blueprints())
    registered = sorted(app.blueprints)
    assert derived == registered, (
        "蓝图注册表与实际注册漂移——请改 server/src/fde_api/app.py::_BLUEPRINT_SPECS\n"
        f"注册表有而实际无：{sorted(set(derived) - set(registered))}\n"
        f"实际有而注册表无：{sorted(set(registered) - set(derived))}"
    )


def test_blueprint_names_are_unique() -> None:
    """蓝图名不得重复（同名注册会被 Flask 静默覆盖）。"""
    names = [bp.name for bp in iter_blueprints()]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    assert not duplicates, f"蓝图名重复：{duplicates}"
    assert len(names) == len(_BLUEPRINT_SPECS), (
        f"iter_blueprints() 产出 {len(names)} 个，注册表登记 {len(_BLUEPRINT_SPECS)} 条"
    )


def test_app_source_has_no_direct_blueprint_registration() -> None:
    """app.py 里除注册表循环外不得直接 app.register_blueprint(...)。"""
    source = _APP_SOURCE.read_text(encoding="utf-8")
    direct_calls = [
        line.strip()
        for line in source.splitlines()
        if re.search(r"app\.register_blueprint\(", line)
    ]
    # 注册表循环本身是唯一允许的一处：它的实参是注册表产出的蓝图对象。
    assert direct_calls == ["app.register_blueprint(blueprint)"], (
        "app.py 出现绕过注册表的直接注册调用——蓝图真身必须只有 _BLUEPRINT_SPECS 一处："
        f"{direct_calls}"
    )
