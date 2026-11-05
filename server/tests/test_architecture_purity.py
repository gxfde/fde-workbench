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
