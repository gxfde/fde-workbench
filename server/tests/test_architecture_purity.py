"""B#4 purity 架构测试（agent-autoloop purity.test 语义）：用静态断言锁模块边界。

三条边界（全部 AST/文本静态扫描，零运行时依赖）：
1. workflows/ 包顶层不 import control 的 service/routes 层（环导入防线——
   反向 control.service → workflows 只允许函数内延迟导入，既有惯例）；
2. workflows/ 内核模块不读 os.environ、不摸 flask（current_app/request）——
   时间/配置从外壳注入，内核保持纯函数化；
3. workflows/ 零产品名硬编码（产品名单点来源红线在代码层的镜像）。
"""
from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "fde_api"


def _module_files(package: str) -> list[Path]:
    return sorted((SRC / package).rglob("*.py"))


def _top_level_imports(path: Path) -> list[str]:
    """仅顶层 import——函数内延迟导入是本仓库既有的环规避惯例，合法。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    mods: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            mods.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.append(node.module)
    return mods


def test_workflows_never_imports_control_service_or_routes_top_level():
    """workflows/ 顶层零 control.service / control.routes 导入（环防线）。"""
    violations: list[str] = []
    for path in _module_files("workflows"):
        for mod in _top_level_imports(path):
            if mod.startswith(("fde_api.control.service", "fde_api.control.routes")):
                violations.append(f"{path.name}: {mod}")
    assert violations == []


def test_control_service_imports_workflows_only_lazily():
    """反向环同理：control/service.py 顶层零 workflows 导入（:663 惯例固化）。"""
    path = SRC / "control" / "service.py"
    violations = [
        mod for mod in _top_level_imports(path) if mod.startswith("fde_api.workflows")
    ]
    assert violations == []


def test_workflow_kernel_reads_no_env_or_flask():
    """workflows/ 内核不读 os.environ、不摸 flask（current_app / request）。"""
    violations: list[str] = []
    for path in _module_files("workflows"):
        text = path.read_text(encoding="utf-8")
        for needle in ("os.environ", "current_app"):
            if needle in text:
                violations.append(f"{path.name}: {needle}")
    assert violations == []


def test_workflows_have_no_product_name_hardcode():
    """产品名单点来源（AGENTS 红线）在 workflows/ 的镜像：零「蔡工」字面量。"""
    violations: list[str] = []
    for path in _module_files("workflows"):
        if "蔡工" in path.read_text(encoding="utf-8"):
            violations.append(path.name)
    assert violations == []


# ---------------------------------------------------------------------------
# 架构评估 2026-11-07 P-4：包级顶层导入环冻结清单（import-lint）。
#
# 仓库的环规避惯例 = 子模块分工（models 层单向）+ 函数内懒导入；顶层包级双
# 向依赖是「导入序地雷」（events.py 反转 projects↔control 教训）与重构成本
# 的来源。本清单冻结既有 18 对环：出现**新环**（新增顶层 import 打破分工）
# 即红；消除既有环同样要求显式更新清单（有意识的清单维护，不允许静默漂移）。
# 仅 workflows↔control 不在清单——该环被上面的 purity 断言专门禁止。
KNOWN_PACKAGE_IMPORT_CYCLES = frozenset({
    ("agents", "guidance"),
    ("agents", "meetings"),
    ("agents", "solutions"),
    ("ai", "guidance"),
    ("ai", "research"),
    ("dispatch", "projects"),
    ("dispatch", "solutions"),
    ("documents", "research"),
    ("evidence", "projects"),
    ("extensions", "storage"),
    ("files", "projects"),
    ("guidance", "translator"),
    ("meetings", "solutions"),
    ("ontology", "projects"),
    ("ontology", "research"),
    ("projects", "research"),
    ("projects", "workflows"),
    ("research", "workbench"),
})


def _import_graph_packages() -> set[str]:
    """节点 = src/fde_api 下的包与顶层模块（__init__ 除外）。"""
    return {
        path.name if path.is_dir() else path.stem
        for path in SRC.iterdir()
        if not path.name.startswith("__") and (path.is_dir() or path.suffix == ".py")
    }


def _package_import_cycles() -> set[tuple[str, str]]:
    nodes = _import_graph_packages()
    edges: dict[str, set[str]] = {}
    for path in SRC.rglob("*.py"):
        rel = path.relative_to(SRC)
        source = rel.parts[0] if len(rel.parts) > 1 else rel.stem
        if source not in nodes:
            continue
        for mod in _top_level_imports(path):
            if not mod.startswith("fde_api."):
                continue
            target = mod.split(".")[1]
            if target in nodes and target != source:
                edges.setdefault(source, set()).add(target)
    return {
        (a, b) for a in nodes for b in nodes if a < b
        and b in edges.get(a, ()) and a in edges.get(b, ())
    }


def test_top_level_package_import_cycles_stay_frozen():
    """包级顶层导入环 = 冻结清单（新增环红、静默解环也红——清单必须显式维护）。"""
    current = _package_import_cycles()
    known = {tuple(pair) for pair in KNOWN_PACKAGE_IMPORT_CYCLES}
    added = current - known
    removed = known - current
    assert not added, (
        f"新增包级顶层导入环 {sorted(added)}——先评审可否经子模块分工/懒导入解环，"
        "确需保留再登记 KNOWN_PACKAGE_IMPORT_CYCLES（评估报告 P-4）"
    )
    assert not removed, (
        f"清单中的环 {sorted(removed)} 已不存在——环被解除是好事，请同步收缩"
        "KNOWN_PACKAGE_IMPORT_CYCLES（有意识的清单维护）"
    )
