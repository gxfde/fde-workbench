# -*- coding: utf-8 -*-
"""M6-WP5/D5：standalone_pod 私有化交付产物纯度闸（tests 先行，TDD 红→绿）。

规格锚：docs/v3.3/m6/00-m6-prep-decision-pack.md §M6-D5 升级段——
「云端作战室 100% 留驻我方：fde-workbench（含 commercial 19 表分账、diagnostics 线索池、
dispatch 派单算法）绝不打入客户私有化镜像。增设 scripts/verify/check_onprem_package_purity.py
静态红线闸：交付产物中出现任一商业敏感路径即 CI 红。」

行为口径：
- 纯静态：只读路径/文件名，绝不 import 产品代码、不连任何服务；
- 命中即 exit 1 且逐条列出命中路径与命中模式；干净 exit 0；
- 双输入形态：目录树扫描（默认）/ 清单文件（--from-list，逐行路径，供 tar/zip -t 管道用）。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "verify" / "check_onprem_package_purity.py"


def _run(script_args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *script_args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def test_script_exists_and_help() -> None:
    assert _SCRIPT.is_file(), f"纯度闸脚本缺失：{_SCRIPT}"
    proc = _run(["--help"])
    assert proc.returncode == 0, proc.stderr


def test_clean_package_tree_passes(tmp_path: Path) -> None:
    (tmp_path / "ontology-service").mkdir()
    (tmp_path / "ontology-service" / "app.py").write_text("# runtime", encoding="utf-8")
    (tmp_path / "README.md").write_text("onprem bundle", encoding="utf-8")
    proc = _run([str(tmp_path)])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "OK" in proc.stdout


def test_commercial_path_trips_gate(tmp_path: Path) -> None:
    (tmp_path / "server" / "src" / "fde_api").mkdir(parents=True)
    (tmp_path / "server" / "src" / "fde_api" / "commercial").mkdir()
    (tmp_path / "server" / "src" / "fde_api" / "commercial" / "billing.py").write_text(
        "# 分账", encoding="utf-8"
    )
    proc = _run([str(tmp_path)])
    assert proc.returncode == 1
    assert "commercial" in proc.stdout and "billing.py" in proc.stdout


def test_diagnostics_and_dispatch_trip_gate(tmp_path: Path) -> None:
    (tmp_path / "diagnostics_pool").mkdir()
    (tmp_path / "diagnostics_pool" / "leads.csv").write_text("x", encoding="utf-8")
    (tmp_path / "dispatch_algo.py").write_text("# 派单", encoding="utf-8")
    proc = _run([str(tmp_path)])
    assert proc.returncode == 1
    assert "diagnostics" in proc.stdout and "dispatch" in proc.stdout


def test_mixed_case_and_prefix_variants_trip_gate(tmp_path: Path) -> None:
    # 大小写变体与前缀扩展（commercial_*/Diagnostics）同属命中面
    (tmp_path / "Commercial_Invoice.pdf").write_text("x", encoding="utf-8")
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "dispatch_rules_v2.json").write_text("{}", encoding="utf-8")
    proc = _run([str(tmp_path)])
    assert proc.returncode == 1


def test_from_list_mode_scans_manifest_lines(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.txt"
    manifest.write_text(
        "app/main.py\nserver/src/fde_api/commercial/ledger.py\nstatic/index.html\n",
        encoding="utf-8",
    )
    proc = _run(["--from-list", str(manifest)])
    assert proc.returncode == 1
    assert "ledger.py" in proc.stdout

    clean = tmp_path / "clean.txt"
    clean.write_text("app/main.py\nstatic/index.html\n", encoding="utf-8")
    proc = _run(["--from-list", str(clean)])
    assert proc.returncode == 0, proc.stdout


def test_allowlist_anchors_documented() -> None:
    # 敏感模式种子必须锚定 D5 原文三域，防止漂移扩权/漏项
    source = _SCRIPT.read_text(encoding="utf-8")
    for anchor in ("commercial", "diagnostics", "dispatch", "M6-D5"):
        assert anchor in source
