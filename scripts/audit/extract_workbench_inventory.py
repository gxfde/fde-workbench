#!/usr/bin/env python3
"""Workbench 路由/数据表/迁移清单自动抽取（v3 审计用）。

只读审计：不连接数据库、不初始化 extensions；通过在裸 Flask 应用上注册
fde_api.app 中声明的全部 blueprint 来枚举 url_map，通过导入全部模型模块
读取 Base.metadata。输出 docs/audit/v3-route-inventory.csv、
docs/audit/v3-database-inventory.csv、docs/audit/v3-workbench-inventory.json。

用法（仓库根目录）:
    server/.venv/Scripts/python.exe scripts/audit/extract_workbench_inventory.py
"""

from __future__ import annotations

import ast
import csv
import importlib.util
import inspect
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_SRC = REPO_ROOT / "server" / "src"
sys.path.insert(0, str(SERVER_SRC))

from flask import Flask

OUT_DIR = REPO_ROOT / "docs" / "audit"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# 1. 蓝图注册（复制 fde_api/app.py create_app 的注册顺序，不调用 create_app，
#    以避免 db/redis/object_storage/dsh_runtime 初始化与持久化配置读取）
# ---------------------------------------------------------------------------
from fde_api.agents.routes import agents_blueprint
from fde_api.app import (
    ai_blueprint,
    auth_blueprint,
    control_blueprint,
    dispatch_blueprint,
    document_templates_blueprint,
    files_blueprint,
    guidance_blueprint,
    health_blueprint,
    local_storage_blueprint,
    mailing_blueprint,
    modules_blueprint,
    project_documents_blueprint,
    project_research_blueprint,
    projects_blueprint,
    solutions_blueprint,
    system_configuration_blueprint,
    template_research_blueprint,
    templates_blueprint,
    users_blueprint,
)
from fde_api.bridge import bridge_blueprint
from fde_api.control.api_actions import actions_blueprint
from fde_api.control.chat import chat_blueprint
from fde_api.control.clawbot_weixin import weixin_blueprint
from fde_api.control.extension_management_routes import management_blueprint
from fde_api.control.lcsc_desktop import desktop_lcsc_blueprint
from fde_api.control.lcsc_skills import lcsc_blueprint
from fde_api.control.mcp_gateway import mcp_blueprint
from fde_api.control.task_board import task_board_blueprint
from fde_api.evidence.routes import evidence_blueprint
from fde_api.meetings.routes import meetings_blueprint
from fde_api.metrics.routes import metrics_blueprint
from fde_api.translator.routes import translator_blueprint
from fde_api.workbench.routes import workbench_blueprint

BLUEPRINTS = [
    health_blueprint,
    auth_blueprint,
    ai_blueprint,
    users_blueprint,
    system_configuration_blueprint,
    modules_blueprint,
    templates_blueprint,
    template_research_blueprint,
    projects_blueprint,
    workbench_blueprint,
    bridge_blueprint,
    project_research_blueprint,
    local_storage_blueprint,
    files_blueprint,
    document_templates_blueprint,
    project_documents_blueprint,
    solutions_blueprint,
    evidence_blueprint,
    dispatch_blueprint,
    guidance_blueprint,
    agents_blueprint,
    meetings_blueprint,
    metrics_blueprint,
    translator_blueprint,
    mailing_blueprint,
    control_blueprint,
    task_board_blueprint,
    management_blueprint,
    weixin_blueprint,
    mcp_blueprint,
    chat_blueprint,
    lcsc_blueprint,
    desktop_lcsc_blueprint,
    actions_blueprint,
]

app = Flask(__name__)
for bp in BLUEPRINTS:
    app.register_blueprint(bp)

# ---------------------------------------------------------------------------
# 2. 测试文件内容（用于 route → test_file 匹配）
# ---------------------------------------------------------------------------
TESTS_DIR = REPO_ROOT / "server" / "tests"
test_contents: dict[str, str] = {}
for path in sorted(TESTS_DIR.rglob("*.py")):
    try:
        test_contents[str(path.relative_to(REPO_ROOT)).replace("\\", "/")] = (
            path.read_text(encoding="utf-8", errors="replace")
        )
    except OSError:
        continue


def rule_to_regex(rule: str) -> re.Pattern[str]:
    placeholder = "@@VAR@@"
    simplified = re.sub(r"<[^>]+>", placeholder, rule)
    escaped = re.escape(simplified).replace(re.escape(placeholder), "[^/\"'`\\s{}]+")
    return re.compile(escaped)


def match_test_files(rule: str) -> str:
    pattern = rule_to_regex(rule)
    hits = [name for name, text in test_contents.items() if pattern.search(text)]
    return ";".join(hits[:3])


DECORATOR_RE = re.compile(r"^@[A-Za-z_][\w.]*", re.MULTILINE)
AUTH_DECORATORS = {
    "require_auth",
    "require_role",
    "require_minimum_role",
    "require_bridge_token",
    "require_capability",
}

_MODULE_CACHE: dict[str, dict] = {}


def module_ast_info(module_name: str) -> dict:
    """解析模块 AST：导入映射（alias/name → fde_api 模块）与函数名 → FunctionDef。"""
    if module_name in _MODULE_CACHE:
        return _MODULE_CACHE[module_name]
    info = {"alias": {}, "names": {}, "funcs": {}, "file": ""}
    mod = sys.modules.get(module_name)
    if mod is None:
        _MODULE_CACHE[module_name] = info
        return info
    try:
        source = inspect.getsource(mod)
        info["file"] = str(Path(inspect.getfile(mod)).relative_to(REPO_ROOT)).replace(
            "\\", "/"
        )
        tree = ast.parse(source)
    except (OSError, TypeError, SyntaxError, ValueError):
        _MODULE_CACHE[module_name] = info
        return info
    package = getattr(mod, "__package__", "") or module_name
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                info["alias"][alias.asname or alias.name.split(".")[0]] = alias.name
        elif isinstance(node, ast.ImportFrom):
            try:
                base = importlib.util.resolve_name(
                    "." * (node.level or 0) + (node.module or ""), package
                )
            except (ImportError, ValueError):
                base = node.module or ""
            for alias in node.names:
                if alias.name == "*":
                    continue
                info["names"][alias.asname or alias.name] = f"{base}.{alias.name}"
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            info["funcs"][node.name] = node
    _MODULE_CACHE[module_name] = info
    return info


def analyze_handler(module_name: str, func_name: str):
    """对 handler 函数体做 AST 分析：调用的 fde_api 服务、请求字段、响应序列化。"""
    info = module_ast_info(module_name)
    node = info["funcs"].get(func_name)
    called: set[str] = set()
    request_keys: set[str] = set()
    response_hints: set[str] = set()
    if node is None:
        return sorted(called), request_keys, response_hints
    payload_names = {"payload", "data", "body", "json_body", "json", "params", "form"}
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            func = sub.func
            if isinstance(func, ast.Attribute):
                base = func.value
                if isinstance(base, ast.Name):
                    base_id = base.id
                    if base_id in info["alias"]:
                        target = info["alias"][base_id]
                        if target.startswith("fde_api"):
                            called.add(f"{target}.{func.attr}")
                        continue
                    if base_id in payload_names and func.attr == "get":
                        for arg in sub.args:
                            if isinstance(arg, ast.Constant) and isinstance(
                                arg.value, str
                            ):
                                request_keys.add(arg.value)
                    if func.attr.startswith(
                        ("serialize", "_serialize", "to_dict", "as_dict", "_payload")
                    ):
                        response_hints.add(func.attr)
            elif isinstance(func, ast.Name):
                target = info["names"].get(func.id)
                if (
                    target
                    and target.startswith("fde_api")
                    and not target.startswith("fde_api.auth.decorators")
                ):
                    called.add(target)
        elif isinstance(sub, ast.Subscript):
            base = sub.value
            if (
                isinstance(base, ast.Name)
                and base.id in payload_names
                and isinstance(sub.slice, ast.Constant)
                and isinstance(sub.slice.value, str)
            ):
                request_keys.add(sub.slice.value)
    return sorted(called), request_keys, response_hints


def handler_info(view):
    """返回 (handler_qualname, file_relpath, decorators, called_services, req, resp)。"""
    target = inspect.unwrap(view)
    qual = getattr(target, "__name__", getattr(view, "__name__", "<anonymous>"))
    module = getattr(target, "__module__", "")
    decorators: list[str] = []
    file_rel = ""
    try:
        source = inspect.getsource(view)
        decorators = [
            d.rstrip("(").lstrip("@")
            for d in DECORATOR_RE.findall(source.split("def ", 1)[0])
        ]
    except (OSError, TypeError):
        pass
    if module:
        info = module_ast_info(module)
        file_rel = info["file"]
        called, req_keys, resp_hints = analyze_handler(module, qual)
    else:
        called, req_keys, resp_hints = [], set(), set()
    return qual, file_rel, decorators, called, req_keys, resp_hints


route_rows = []
for rule in sorted(
    app.url_map.iter_rules(), key=lambda r: (r.rule, sorted(r.methods or []))
):
    if rule.endpoint == "static":
        continue
    methods = sorted(m for m in (rule.methods or []) if m not in {"HEAD", "OPTIONS"})
    view = app.view_functions.get(rule.endpoint)
    qual, file_rel, decorators, services, req_keys, resp_hints = (
        handler_info(view) if view else ("<missing>", "", [], [], set(), set())
    )
    auth = ";".join(
        d
        for d in decorators
        if any(d == a or d.startswith(a + "(") for a in AUTH_DECORATORS)
    ) or ("none-found" if view else "")
    blueprint = rule.endpoint.split(".", 1)[0] if "." in rule.endpoint else "(root)"
    request_schema = ";".join(sorted(req_keys)) or "UNRESOLVED(manual-json)"
    response_schema = ";".join(sorted(resp_hints))
    route_rows.append(
        {
            "repository": "fde-workbench@0570384",
            "method": "|".join(methods),
            "path": rule.rule,
            "blueprint": blueprint,
            "handler": f"{file_rel}::{qual}" if file_rel else qual,
            "service": ";".join(services)[:240],
            "auth": auth,
            "request_schema": request_schema,
            "response_schema": response_schema,
            "test_file": match_test_files(rule.rule),
            "status": "VERIFIED(url_map)",
        }
    )

# ---------------------------------------------------------------------------
# 3. 数据表清单（导入全部模型模块后读 Base.metadata）
# ---------------------------------------------------------------------------
from fde_api.auth.models import Base

MODEL_MODULES = [
    "fde_api.agents.models",
    "fde_api.auth.models",
    "fde_api.control.chat",
    "fde_api.control.lcsc_skills",
    "fde_api.control.model_preferences",
    "fde_api.control.models",
    "fde_api.control.weixin_models",
    "fde_api.dispatch.models",
    "fde_api.documents.models",
    "fde_api.evidence.models",
    "fde_api.files.models",
    "fde_api.guidance.models",
    "fde_api.jobs.models",
    "fde_api.mailing.models",
    "fde_api.meetings.models",
    "fde_api.research.models",
    "fde_api.solutions.models",
    "fde_api.system_configuration",
    "fde_api.translator.models",
    "fde_api.workbench.models",
]
import importlib

for mod in MODEL_MODULES:
    importlib.import_module(mod)

model_by_table: dict[str, str] = {}
model_file_by_table: dict[str, str] = {}

for mapper in Base.registry.mappers:
    cls = mapper.class_
    table = mapper.local_table
    if table is None:
        continue
    model_by_table.setdefault(table.name, cls.__name__)
    try:
        model_file_by_table.setdefault(
            table.name,
            str(Path(inspect.getfile(cls)).relative_to(REPO_ROOT)).replace("\\", "/"),
        )
    except (TypeError, OSError, ValueError):
        pass

# ---------------------------------------------------------------------------
# 4. Alembic 迁移链 + 表 → 首个创建 revision
# ---------------------------------------------------------------------------
VERSIONS_DIR = REPO_ROOT / "server" / "migrations" / "versions"
revision_re = re.compile(r'^revision(?::\s*str)?\s*=\s*["\']([\w]+)["\']', re.MULTILINE)
down_re = re.compile(
    r'^down_revision(?::[^=]+)?\s*=\s*(["\'][\w]+["\']|None)', re.MULTILINE
)
create_table_re = re.compile(r'op\.create_table\(\s*["\']([\w]+)["\']')
add_column_re = re.compile(r'op\.add_column\(\s*["\']([\w]+)["\']')

revisions: dict[str, dict] = {}
table_first_revision: dict[str, str] = {}
table_touched_revisions: dict[str, list[str]] = {}
for path in sorted(VERSIONS_DIR.glob("*.py")):
    text = path.read_text(encoding="utf-8", errors="replace")
    m_rev = revision_re.search(text)
    if not m_rev:
        continue
    rev = m_rev.group(1)
    m_down = down_re.search(text)
    down = None
    if m_down and m_down.group(1) != "None":
        down = m_down.group(1).strip("'\"")
    revisions[rev] = {
        "file": path.name,
        "down_revision": down,
        "create_tables": create_table_re.findall(text),
        "add_column_tables": sorted(set(add_column_re.findall(text))),
    }
    for t in create_table_re.findall(text):
        table_first_revision.setdefault(t, rev)
    for t in set(create_table_re.findall(text)) | set(add_column_re.findall(text)):
        table_touched_revisions.setdefault(t, []).append(rev)

children: dict[str | None, list[str]] = {}
for rev, info in revisions.items():
    children.setdefault(info["down_revision"], []).append(rev)
heads = [rev for rev in revisions if rev not in children or not children.get(rev)]
downs = {info["down_revision"] for info in revisions.values() if info["down_revision"]}
roots = [rev for rev, info in revisions.items() if info["down_revision"] is None]

VERSION_FIELD_RE = re.compile(r"(version|revision|hash|snapshot|parent)", re.IGNORECASE)


def table_row(name, table):
    pk = [c.name for c in table.primary_key.columns]
    fks = sorted(
        f"{fk.parent.table.name}.{fk.parent.name}->{fk.column.table.name}.{fk.column.name}"
        for fk in table.foreign_keys
    )
    indexes = sorted(
        f"{ix.name}({','.join(c.name for c in ix.columns)}){'*U' if ix.unique else ''}"
        for ix in table.indexes
    )
    uniq = sorted(
        f"uq:{','.join(c.name for c in uc.columns)}"
        for uc in table.constraints
        if getattr(uc, "columns", None) and uc.__class__.__name__ == "UniqueConstraint"
    )
    version_fields = sorted(
        c.name for c in table.columns if VERSION_FIELD_RE.search(c.name)
    )
    project_scope = any("project" in c.name for c in table.columns)
    return {
        "repository": "fde-workbench@0570384",
        "table": name,
        "model": model_by_table.get(name, ""),
        "file": model_file_by_table.get(name, ""),
        "primary_key": ",".join(pk),
        "foreign_keys": ";".join(fks),
        "indexes": ";".join(indexes + uniq),
        "version_fields": ",".join(version_fields),
        "project_scope": "yes" if project_scope else "no",
        "migration_revision": table_first_revision.get(name, "UNKNOWN"),
        "status": "VERIFIED(metadata)",
    }


table_rows = [
    table_row(name, table) for name, table in sorted(Base.metadata.tables.items())
]

# ---------------------------------------------------------------------------
# 5. 写出
# ---------------------------------------------------------------------------
route_csv = OUT_DIR / "v3-route-inventory.csv"
with route_csv.open("w", encoding="utf-8-sig", newline="") as fh:
    writer = csv.DictWriter(fh, fieldnames=list(route_rows[0].keys()))
    writer.writeheader()
    writer.writerows(route_rows)

db_csv = OUT_DIR / "v3-database-inventory.csv"
with db_csv.open("w", encoding="utf-8-sig", newline="") as fh:
    writer = csv.DictWriter(fh, fieldnames=list(table_rows[0].keys()))
    writer.writeheader()
    writer.writerows(table_rows)

summary = {
    "route_count": len(route_rows),
    "blueprint_count": len(BLUEPRINTS),
    "table_count": len(table_rows),
    "revision_count": len(revisions),
    "heads": heads,
    "roots": roots,
    "tables_without_create_revision": sorted(
        r["table"] for r in table_rows if r["migration_revision"] == "UNKNOWN"
    ),
    "revisions": revisions,
}
(OUT_DIR / "v3-workbench-inventory.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8"
)
print(
    json.dumps(
        {k: v for k, v in summary.items() if k != "revisions"},
        ensure_ascii=False,
        indent=1,
    )
)
