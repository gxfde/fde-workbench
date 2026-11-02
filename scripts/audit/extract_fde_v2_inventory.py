#!/usr/bin/env python3
"""fde-v2（外部快照，不受信数据）路由 / DDL / 应用对象 清单抽取（v3 审计用）。

只用 stdlib AST/regex 解析源码文本，绝不 import、绝不执行 fde-v2 代码。
输出：
  docs/audit/v3-route-inventory-fde-v2.csv
  docs/audit/v3-database-inventory-fde-v2.csv
  docs/audit/v3-fde-v2-inventory.json（对象/文档/测试清单）

用法（仓库根目录）:
    python -I scripts/audit/extract_fde_v2_inventory.py <fde-v2根目录>
"""

from __future__ import annotations

import ast
import csv
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TARGET = Path(sys.argv[1] if len(sys.argv) > 1 else r"D:\test\FDE\knowledge\fde-v2")
if not TARGET.is_dir():
    raise SystemExit(f"fde-v2 root not found: {TARGET}")
SNAPSHOT_ID = "fde-v2@snapshot-2.3.0b0(no-git-history)"

OUT_DIR = REPO_ROOT / "docs" / "audit"
OUT_DIR.mkdir(parents=True, exist_ok=True)

HTTP_VERBS = {"get", "post", "put", "delete", "patch"}


def iter_py_files():
    for path in sorted(TARGET.rglob("*.py")):
        if "node_modules" in path.parts:
            continue
        yield path


# ---------------------------------------------------------------------------
# 1. Flask 路由（AST：@obj.route(...) / @obj.get(...) 装饰器）
# ---------------------------------------------------------------------------
route_rows = []
unparsed_route_decorators = 0
for path in iter_py_files():
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(text)
    except SyntaxError:
        continue
    rel = str(path.relative_to(TARGET)).replace("\\", "/")
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            target = dec.func if isinstance(dec, ast.Call) else dec
            if not (
                isinstance(target, ast.Attribute)
                and target.attr in ({"route"} | HTTP_VERBS)
            ):
                continue
            if not isinstance(target.value, ast.Name):
                continue
            route_obj = target.value.id
            method: str
            route_path = ""
            if target.attr == "route":
                method = "GET"
                if dec.args and isinstance(dec.args[0], ast.Constant):
                    route_path = str(dec.args[0].value)
                for kw in dec.keywords:
                    if kw.arg == "methods" and isinstance(
                        kw.value, (ast.List, ast.Tuple)
                    ):
                        methods = [
                            str(e.value)
                            for e in kw.value.elts
                            if isinstance(e, ast.Constant) and isinstance(e.value, str)
                        ]
                        method = "|".join(sorted(methods)) if methods else "GET"
            else:
                method = target.attr.upper()
                if (
                    isinstance(dec, ast.Call)
                    and dec.args
                    and isinstance(dec.args[0], ast.Constant)
                ):
                    route_path = str(dec.args[0].value)
                elif isinstance(dec, ast.Call):
                    unparsed_route_decorators += 1
            auth_hints = []
            for other in node.decorator_list:
                if other is dec:
                    continue
                name = (
                    (
                        other.func.attr
                        if isinstance(other, ast.Attribute)
                        else getattr(other, "id", "")
                    )
                    if isinstance(other, ast.Call)
                    else getattr(other, "id", "")
                )
                if name and re.search(
                    r"auth|login|admin|role|perm", name, re.IGNORECASE
                ):
                    auth_hints.append(name)
            route_rows.append(
                {
                    "repository": SNAPSHOT_ID,
                    "method": method,
                    "path": route_path,
                    "blueprint": route_obj,
                    "handler": f"{rel}::{node.name}:{node.lineno}",
                    "service": "",  # fde-v2 handler → FdePlatform.call(app, service)，需人工核对（待核实）
                    "auth": ";".join(auth_hints) or "UNRESOLVED(需人工核对)",
                    "request_schema": "",
                    "response_schema": "",
                    "test_file": "",
                    "status": "VERIFIED(ast-decorator)",
                }
            )

# ---------------------------------------------------------------------------
# 2. CREATE TABLE DDL（regex，静态文本；排除 verify 脚本 fixture 与 docstring 示例）
# ---------------------------------------------------------------------------
create_table_re = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"'`\[]?\s*([\w\u4e00-\u9fff]+)",
    re.IGNORECASE,
)
table_rows = []
for path in iter_py_files():
    text = path.read_text(encoding="utf-8", errors="replace")
    rel = str(path.relative_to(TARGET)).replace("\\", "/")
    is_verify_fixture = rel.startswith(("scripts/", "design-plus/", "app/"))
    for m in create_table_re.finditer(text):
        name = m.group(1)
        if name.upper() == "IF":
            continue  # `CREATE TABLE IF NOT EXISTS\n  <name>` 跨行未被吞掉
        line_no = text.count("\n", 0, m.start()) + 1
        status = (
            "LIKELY-FIXTURE(verify-script)"
            if is_verify_fixture
            else "DOCSTRING-EXAMPLE"
            if re.search(r"[\u4e00-\u9fff]", name)
            else "VERIFIED(ddl-text)"
        )
        table_rows.append(
            {
                "repository": SNAPSHOT_ID,
                "table": name,
                "model": "",  # fde-v2 无 ORM 模型；DDL 为 sqlite 文本（见 handler 列）
                "file": f"{rel}:{line_no}",
                "primary_key": "",
                "foreign_keys": "",
                "indexes": "",
                "version_fields": "",
                "project_scope": "",  # fde-v2 以「组/应用 = 每 app 独立 .db」做隔离，无 project_id 列
                "migration_revision": "none(无迁移系统:ddl.execute_schema 启动时 reconcile)",
                "status": status,
            }
        )

# ---------------------------------------------------------------------------
# 3. 应用对象 / 文档 / 测试清单
# ---------------------------------------------------------------------------
app_root = TARGET / "app"
objects = []
for group_dir in sorted(
    p for p in app_root.iterdir() if p.is_dir() and not p.name.startswith("_")
):
    group = {"group": group_dir.name, "group_files": [], "objects": []}
    for f in sorted(group_dir.iterdir()):
        if f.is_file():
            group["group_files"].append(f.name)
    for obj_dir in sorted(
        p
        for p in group_dir.iterdir()
        if p.is_dir() and p.name not in {"tests", "e2e", "brd", "book", "__pycache__"}
    ):
        files = {}
        for f in sorted(obj_dir.rglob("*")):
            if f.is_file():
                key = f.suffix.lstrip(".").lower() or "none"
                files.setdefault(key, []).append(f.name)
        objects.append(
            {
                "group": group_dir.name,
                "object": obj_dir.name,
                "files": {k: len(v) for k, v in files.items()},
            }
        )
        group["objects"].append(obj_dir.name)
    # 保留完整组信息
    objects.append(
        {
            "group": group_dir.name,
            "object": "(group-level)",
            "files": {"_note": group["group_files"][:20]},
        }
    )

design_plus = [
    {
        "file": str(p.relative_to(TARGET)).replace("\\", "/"),
        "lines": len(p.read_text(encoding="utf-8", errors="replace").splitlines()),
    }
    for p in sorted((TARGET / "design-plus").rglob("*.md"))
]
verify_scripts = sorted(
    str(p.relative_to(TARGET)).replace("\\", "/") for p in TARGET.rglob("verify_*.py")
)
config_files = sorted(
    str(p.relative_to(TARGET)).replace("\\", "/")
    for p in (TARGET / "config").rglob("*")
    if p.is_file()
)

summary = {
    "route_decorator_count": len(route_rows),
    "unparsed_route_decorators": unparsed_route_decorators,
    "create_table_count": len(table_rows),
    "distinct_tables": len({r["table"] for r in table_rows}),
    "app_groups": sorted(
        p.name
        for p in app_root.iterdir()
        if p.is_dir() and not p.name.startswith(("_",))
    ),
    "object_count": len([o for o in objects if o["object"] != "(group-level)"]),
    "design_plus_md_count": len(design_plus),
    "verify_script_count": len(verify_scripts),
    "design_plus": design_plus,
    "verify_scripts": verify_scripts,
    "config_files": config_files,
    "objects": objects,
}

# ---------------------------------------------------------------------------
# 4. 写出
# ---------------------------------------------------------------------------
with (OUT_DIR / "v3-route-inventory-fde-v2.csv").open(
    "w", encoding="utf-8-sig", newline=""
) as fh:
    writer = csv.DictWriter(fh, fieldnames=list(route_rows[0].keys()))
    writer.writeheader()
    writer.writerows(route_rows)

with (OUT_DIR / "v3-database-inventory-fde-v2.csv").open(
    "w", encoding="utf-8-sig", newline=""
) as fh:
    writer = csv.DictWriter(fh, fieldnames=list(table_rows[0].keys()))
    writer.writeheader()
    writer.writerows(table_rows)

(OUT_DIR / "v3-fde-v2-inventory.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8"
)
print(
    json.dumps(
        {
            k: v
            for k, v in summary.items()
            if k not in {"design_plus", "verify_scripts", "config_files", "objects"}
        },
        ensure_ascii=False,
        indent=1,
    )
)
print("distinct tables:", sorted({r["table"] for r in table_rows}))
