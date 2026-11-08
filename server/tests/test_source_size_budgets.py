"""源码体积预算（架构评估 P1-2：热点大文件**只钉不拆**）。

本轮的处置：``workflows/executor.py``（原 1562 行）按「调度 / 分派 / 结算 / 恢复」
拆成门面 + 五个子模块；其余四个千行热点（本体 / 项目 / 智能体 / 调研导入）本轮
**不拆**——同轮拆四个千行模块的爆炸半径不可控，拆不拆留给下一轮，先把
「不许再长」变成机器闸。

口径：单文件**逻辑行数**（``splitlines()`` 计数，CRLF/LF 同值）。基线值写死在本
文件里，与 AGENTS「口径数字引用前现测」同源——真要拆某个文件时，先更新这里的
预算（并写明拆分去处），再改代码。

三条钉：
1. 四个历史热点的**逐文件**上限（比全局上限更紧：它们必须变小，不能只是不变）；
2. ``src/fde_api`` 下**任一** .py 的全局上限（防新文件长成下一个热点）；
3. 工作流执行器拆分后的七个模块各自的体量上限（防「拆完又粘回去」）。
"""
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "fde_api"

# 历史热点（相对仓库根）：上限 = 本轮拆分前的实测行数（只许不变或变小）
HOTSPOT_BUDGETS = {
    "ontology/service.py": 2102,
    "projects/service.py": 1946,
    "agents/service.py": 1836,
    "research/imports.py": 1772,
}

# 全局上限：src/fde_api 下任何单文件不得超过此行数
GLOBAL_LINE_BUDGET = 2200

# 工作流执行器拆分后的模块体量上限（门面 + 五个子模块）
WORKFLOW_MODULE_BUDGETS = {
    "workflows/executor.py": 700,
    "workflows/constants.py": 120,
    "workflows/dag_utils.py": 200,
    "workflows/serialization.py": 200,
    "workflows/settlement.py": 350,
    "workflows/dispatch.py": 650,
    "workflows/recovery.py": 200,
}


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def test_hotspot_files_stay_within_budget():
    """历史热点逐文件上限：只许拆、不许长。"""
    over: list[str] = []
    for relative, budget in HOTSPOT_BUDGETS.items():
        path = SRC / relative
        assert path.exists(), f"{relative} 不存在——改名或移动时请同步本预算表"
        count = _line_count(path)
        if count > budget:
            over.append(f"{relative}: {count} 行 > 预算 {budget} 行")
    assert over == [], (
        "热点文件超预算（只许变小）："
        + "；".join(over)
        + "——本轮只钉不拆；若要拆，先把拆分去处写进 PR 描述，再更新本预算表"
    )


def test_no_source_file_exceeds_global_budget():
    """全局上限：防止新文件长成下一个千行热点。"""
    over: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        count = _line_count(path)
        if count > GLOBAL_LINE_BUDGET:
            over.append(f"{path.relative_to(SRC).as_posix()}: {count} 行")
    assert over == [], (
        f"以下文件超过全局上限 {GLOBAL_LINE_BUDGET} 行：{over}"
        "——按职责拆模块（拆法参照 workflows/executor.py 的 P1-2 拆分地图）"
    )


def test_workflow_modules_stay_within_budget():
    """工作流执行器拆分后的模块不得「粘回去」。"""
    over: list[str] = []
    for relative, budget in WORKFLOW_MODULE_BUDGETS.items():
        path = SRC / relative
        assert path.exists(), f"{relative} 不存在——模块改名时请同步本预算表"
        count = _line_count(path)
        if count > budget:
            over.append(f"{relative}: {count} 行 > 预算 {budget} 行")
    assert over == [], "工作流执行器模块超预算：" + "；".join(over)
