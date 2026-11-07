"""goal-ta4：路由审计清单同步钉（#174 教训机械化，零业务代码）。

`docs/audit/v3-route-inventory.csv` 与 `create_app().url_map` 实际路由逐行
对账——任何轮次新增/删除路由而未重生成清单（`scripts/audit/
extract_workbench_inventory.py`，AGENTS「审计清单刷新有前置条件」节）即在
server-tests CI 转红，不再依赖人工记得同步（#174 事故：#171 加了 confirm
的 redaction_reviewed 参数、#162 加了技能中心两路由，清单都落后了）。

比对口径与生成器一致（extract_workbench_inventory.py）：跳过 static、剔除
HEAD/OPTIONS、method 多值按字母序 `|` 连接；同一 (method, path) 集合必须
逐位相等。清单列的其余列（handler/service/auth…）是生成器的富化产物，
不在此重复断言（其正确性由生成器自身与人工评审守）。
"""
from __future__ import annotations

import csv
from pathlib import Path

from fde_api.app import create_app

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ROUTE_CSV = _REPO_ROOT / "docs" / "audit" / "v3-route-inventory.csv"


def _actual_routes(app) -> set[tuple[str, str]]:
    actual: set[tuple[str, str]] = set()
    for rule in app.url_map.iter_rules():
        if rule.endpoint == "static":
            continue
        methods = sorted(m for m in (rule.methods or []) if m not in {"HEAD", "OPTIONS"})
        actual.add(("|".join(methods), rule.rule))
    return actual


def _committed_routes() -> set[tuple[str, str]]:
    with open(_ROUTE_CSV, encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return {(row["method"], row["path"]) for row in rows}


def test_route_inventory_csv_matches_url_map(settings) -> None:
    app = create_app(settings)
    actual = _actual_routes(app)
    committed = _committed_routes()
    missing_in_csv = sorted(f"{method} {path}" for method, path in actual - committed)
    stale_in_csv = sorted(f"{method} {path}" for method, path in committed - actual)
    assert not missing_in_csv and not stale_in_csv, (
        "路由审计清单与实际路由漂移——请运行 `python scripts/audit/extract_workbench_inventory.py` "
        "重生成并随本 PR 提交（AGENTS「审计清单刷新有前置条件」）。\n"
        f"实际有而清单缺（{len(missing_in_csv)}）：{missing_in_csv}\n"
        f"清单有而实际无（{len(stale_in_csv)}）：{stale_in_csv}"
    )
