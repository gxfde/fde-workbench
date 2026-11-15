#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""M6-WP5/M6-D5：standalone_pod 私有化交付产物纯度闸（静态红线）。

规格锚（docs/v3.3/m6/00-m6-prep-decision-pack.md §M6-D5 升级段）：
云端作战室 100% 留驻我方——fde-workbench（含 commercial 19 表分账、diagnostics 线索池、
dispatch 派单算法）绝不打入客户私有化镜像；交付产物中出现任一商业敏感路径即 CI 红。

用法（仓库根或任意目录）：
  python scripts/verify/check_onprem_package_purity.py <交付产物目录>
  tar -tzf bundle.tar.gz | python scripts/verify/check_onprem_package_purity.py --from-list <清单文件>

约定：
- 纯静态：只读路径文本，零 import 产品代码、零网络/DB 访问；
- 匹配面 = 路径片段（大小写不敏感），种子三域锚定 D5 原文，禁止漂移扩权或漏项——
  新增敏感域必须走决策单改本清单；
- 命中即 exit 1 并逐条列命中路径；干净 exit 0 输出 OK 行。
"""

from __future__ import annotations

import argparse
import fnmatch
import sys
from pathlib import Path

# D5 原文三域种子（commercial 19 表分账 / diagnostics 线索池 / dispatch 派单算法）。
# 模式为路径片段匹配（子串+通配），覆盖目录名、文件名与前缀扩展（commercial_*、Diagnostics 等）。
SENSITIVE_PATTERNS: tuple[str, ...] = (
    "commercial",
    "commercials",
    "diagnostics",
    "diagnostic_pool",
    "dispatch",
)

EXIT_CLEAN = 0
EXIT_VIOLATION = 1
EXIT_USAGE = 2


def _violation_reason(path: str) -> str | None:
    lowered = path.lower().replace("\\", "/")
    for pattern in SENSITIVE_PATTERNS:
        if pattern in lowered or fnmatch.fnmatch(lowered, f"*{pattern}*"):
            return pattern
    return None


def scan_tree(root: Path) -> list[tuple[str, str]]:
    hits: list[tuple[str, str]] = []
    for item in sorted(root.rglob("*")):
        reason = _violation_reason(str(item.relative_to(root)))
        if reason is not None:
            hits.append((str(item.relative_to(root)), reason))
    return hits


def scan_list(list_file: Path) -> list[tuple[str, str]]:
    hits: list[tuple[str, str]] = []
    for raw in list_file.read_text(encoding="utf-8", errors="replace").splitlines():
        entry = raw.strip()
        if not entry:
            continue
        reason = _violation_reason(entry)
        if reason is not None:
            hits.append((entry, reason))
    return hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="standalone_pod 交付产物纯度闸（M6-D5）")
    parser.add_argument("target", nargs="?", help="交付产物目录")
    parser.add_argument(
        "--from-list",
        metavar="FILE",
        help="改读路径清单文件（tar/zip -t 输出，逐行一路径）",
    )
    args = parser.parse_args(argv)

    if args.from_list:
        hits = scan_list(Path(args.from_list))
        scope = f"list:{args.from_list}"
    elif args.target:
        root = Path(args.target)
        if not root.is_dir():
            print(f"[usage] 目标不是目录：{root}", file=sys.stderr)
            return EXIT_USAGE
        hits = scan_tree(root)
        scope = f"tree:{root}"
    else:
        parser.print_usage()
        return EXIT_USAGE

    if hits:
        print(f"FAIL（M6-D5 纯度闸）：{scope} 命中 {len(hits)} 条商业敏感路径——云端作战室资产禁入私有化镜像")
        for path, pattern in hits:
            print(f"  [hit] {path}  (pattern: {pattern})")
        return EXIT_VIOLATION

    print(f"OK（M6-D5 纯度闸）：{scope} 未命中商业敏感路径（commercial/diagnostics/dispatch）")
    return EXIT_CLEAN


if __name__ == "__main__":
    sys.exit(main())
