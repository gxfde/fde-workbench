#!/usr/bin/env python3
"""架构图防陈旧闸（架构评估 P2-7）。

图纸是一类**特别容易过期**的文档：它的内容是「结构快照」，而结构每轮都在变。
本仓此前的五张图钉在 fork/main `58f7a26`，此后主干又并入了 V3.1 P0/P1、
商业化 G1 等多轮——图里的「47 蓝图 · 384 路由」「128 表」早已过期，而**没有任何
机器能发现它**：文档里的口径数字靠人记，而 AGENTS 的「口径数字引用前现测」
纪律管的是**引用时**，管不了**图上已经写着的旧数字**。

本闸把这件事变成机械检查：

- 图纸候选（``docs/architecture/archify-diagrams/*/candidate.json``）里出现的
  「N 蓝图 / N 路由 / N 表 / N 迁移」必须与
  ``docs/audit/v3-workbench-inventory.json``（本仓唯一的机器可读结构口径）
  逐项相等——**漂移即红**；
- ``meta.repository.revision`` 必须是 40 位十六进制（钉住取证基线）；
- 每张图必须有候选 + 已渲染 HTML（缺一即红——半张图不算交付）。

用法（仓库根目录）:
    python scripts/audit/check_archify_diagram_freshness.py
    python scripts/audit/check_archify_diagram_freshness.py --json
退出码：0 = 全部一致；1 = 漂移（并列出该改什么）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DIAGRAMS_DIR = REPO_ROOT / "docs" / "architecture" / "archify-diagrams"
INVENTORY_JSON = REPO_ROOT / "docs" / "audit" / "v3-workbench-inventory.json"

# 口径数字 → inventory JSON 的键。量词（张/个）可选，写作习惯两种都见过。
METRIC_PATTERNS: dict[str, tuple[str, re.Pattern[str]]] = {
    "blueprint_count": ("蓝图", re.compile(r"(\d+)\s*蓝图")),
    "route_count": ("路由", re.compile(r"(\d+)\s*路由")),
    "table_count": ("表", re.compile(r"(\d+)\s*[张个]?\s*表")),
    "revision_count": ("迁移", re.compile(r"(\d+)\s*迁移")),
}

REVISION_RE = re.compile(r"^[0-9a-f]{40}$")


def _inventory() -> dict:
    return json.loads(INVENTORY_JSON.read_text(encoding="utf-8"))


def _candidate_files() -> list[Path]:
    return sorted(DIAGRAMS_DIR.glob("*/candidate.json"))


def check() -> list[str]:
    """返回问题清单；空列表 = 全部一致。"""
    problems: list[str] = []
    inventory = _inventory()
    candidates = _candidate_files()
    if not candidates:
        return [f"{DIAGRAMS_DIR} 下没有任何 candidate.json——图纸目录是否被挪走了？"]

    for path in candidates:
        folder = path.parent
        label = folder.name
        raw = path.read_text(encoding="utf-8")
        try:
            candidate = json.loads(raw)
        except json.JSONDecodeError as error:
            problems.append(f"{label}/candidate.json 不是合法 JSON：{error}")
            continue

        # 1) 已渲染 HTML 必须与候选同在（半张图不算交付）
        html_files = sorted(folder.glob("*.html"))
        if not html_files:
            problems.append(f"{label}/ 没有已渲染的 HTML——请跑 archify finalize 后重生成")

        # 2) 取证基线必须是 40 位十六进制
        revision = str(candidate.get("meta", {}).get("repository", {}).get("revision", ""))
        if not REVISION_RE.match(revision):
            problems.append(
                f"{label}/candidate.json 的 meta.repository.revision 不是 40 位十六进制"
                f"（实测 {revision!r}）——请钉到真实的 commit"
            )

        # 3) 口径数字必须与 inventory 一致
        for key, (label_cn, pattern) in METRIC_PATTERNS.items():
            expected = inventory.get(key)
            if not isinstance(expected, int):
                problems.append(f"inventory JSON 缺 {key}——先重生成审计清单")
                continue
            found = {int(match) for match in pattern.findall(raw)}
            if not found:
                continue  # 该图不引用这个口径（不是问题）
            stale = sorted(value for value in found if value != expected)
            if stale:
                problems.append(
                    f"{label}/candidate.json 的「{label_cn}」口径过期："
                    f"图上 {sorted(found)} ≠ 清单 {expected}——"
                    "请改图并重跑 archify finalize（数字口径以 "
                    "docs/audit/v3-workbench-inventory.json 为准）"
                )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="架构图口径防陈旧闸")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    args = parser.parse_args()

    problems = check()
    if args.json:
        print(json.dumps({"ok": not problems, "problems": problems}, ensure_ascii=False, indent=2))
    elif problems:
        print("架构图口径漂移：")
        for problem in problems:
            print(f"  - {problem}")
        print("\n处置：① 按 docs/audit/v3-workbench-inventory.json 改图里的数字；"
              "② 重跑 archify finalize（输出路径已存在时加 --out-dir <folder>/review-<n>）；"
              "③ 整页实拍 preview.png（tools/capture-full-preview.mjs）。")
    else:
        print("OK: 架构图口径与 v3-workbench-inventory.json 逐项一致")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
