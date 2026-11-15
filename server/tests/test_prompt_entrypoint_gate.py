"""提示词卫生差距②静态钉（B#12+B#31 拍板落地，2026-11-06 交互拍板）。

差距②：`direct_tool_completion` / `execute_ai_prompt` 的 `system_prompt`
形参是「提示词权威层白名单」的**外放通道**——函数本身接受任意字符串，
语义层约束（上游必须传白名单来源）此前无静态闸。本轮按拍板补 AST
实参来源允许名单断言（与 J-1 同组织，纯静态扫描零运行时依赖）。

允许名单（全部已追实，与 J-1 系测试 docstring 登记一致）：
- `ast.Constant`：字面常量（structured_completion 的固定 JSON 指令）；
- `ast.Name` 且变量名 ∈ 允许集合（形参直传链/治理面 instructions）；
- `ast.Call` 且被调函数 ∈ 允许集合（`_workbench_system_prompt()`）。

域外新增实参形态即红：新调用点 PR 必须对照契约 §2 表登记。
"""
from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "fde_api"

# 受闸函数（system_prompt 形参 = 权威层外放通道）
GATED_FUNCTIONS = {
    "execute_ai_prompt",
    "direct_tool_completion",
    "direct_provider_completion",
    "_degraded_direct_result",
}

# 允许的变量名（形参直传链——上游实参来源已逐点登记）：
# - system_prompt：函数间直传（execute_ai_prompt → 降级腿/DSH 体，源头
#   必为调用方白名单实参，链路本身不加工）；
# - instructions：executor skill 节点 = 治理面发布版本行（白名单④）。
_ALLOWED_PARAM_NAMES = {"system_prompt", "instructions"}

# 允许的组装函数：
# - _workbench_system_prompt：白名单③ chat 系统提示词 = 常量+config+内置手册目录；
# - _simulation_workbench_system_prompt：学习闭环 2.0 L4 训练场 workbench 适配器
#   ＝注册表常量 WORKBENCH_SYSTEM_PROMPT + run config 受控候选 overlay 追加条款
#   （≤200 字，N6 受控例外拍板 2026-11-13 登记）。
_ALLOWED_CALL_NAMES = {"_workbench_system_prompt", "_simulation_workbench_system_prompt"}

# 允许的提示词权威常量名（白名单①「内部权威常量」的具名形态）：
# - DISCOVERY_SYSTEM_PROMPT：V3.1 P0-1 discovery 抽取（discovery/prompt.py
#   模块级常量，jobs.py 直传——2026-11-08 登记）。
# - DISCOVERY_CHUNK_SYSTEM_PROMPT：V31-P1b discovery 分段抽取的片级提示词
#   （discovery/prompt.py 模块级常量，仍是内部权威常量形态——2026-11-09 登记）。
# - DIAGNOSTIC_REPORT_SYSTEM_PROMPT：获客诊断 T-10b 的报告生成提示词
#   （diagnostics/prompts.py 模块级常量，jobs.py 直传——2026-11-11 登记）。
# - QUALITY_TESTCASE_DRAFT_SYSTEM_PROMPT：AI 原生化 N3a 的 quality 用例
#   AI 起草提示词（quality/draft.py 模块级常量，同模块直传——2026-11-11 登记）。
# - DELIVERY_PLAN_DRAFT_SYSTEM_PROMPT：AI 原生化 N3b（G-04）的交付方案 AI
#   起草提示词（plans/draft_ai.py 模块级常量，同模块直传——2026-11-12 登记）。
# - WORKFLOW_DAG_DRAFT_SYSTEM_PROMPT：AI 原生化 N3b（G-03）的 DAG AI 起草
#   提示词（workflows/draft_ai.py 模块级常量，同模块直传——2026-11-12 登记，
#   N3b ADR §3 机制 1）。
# - DISPATCH_RECOMMENDATION_SYSTEM_PROMPT：AI 原生化 N3c（G-06）的派单建议
#   腿提示词（dispatch/recommend_ai.py 模块级常量，同模块直传——2026-11-12
#   登记）。
_ALLOWED_PROMPT_CONSTANTS = {
    "DISCOVERY_SYSTEM_PROMPT",
    "DISCOVERY_CHUNK_SYSTEM_PROMPT",
    "DIAGNOSTIC_REPORT_SYSTEM_PROMPT",
    "QUALITY_TESTCASE_DRAFT_SYSTEM_PROMPT",
    "DELIVERY_PLAN_DRAFT_SYSTEM_PROMPT",
    "WORKFLOW_DAG_DRAFT_SYSTEM_PROMPT",
    "DISPATCH_RECOMMENDATION_SYSTEM_PROMPT",
    "WORKBENCH_SYSTEM_PROMPT",
    "IMPROVEMENT_DRAFT_SYSTEM_PROMPT",
}


def _iter_gated_calls():
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else (
                func.attr if isinstance(func, ast.Attribute) else None)
            if name in GATED_FUNCTIONS:
                rel = str(path.relative_to(SRC)).replace("\\", "/")
                for kw in node.keywords:
                    if kw.arg == "system_prompt":
                        yield rel, node.lineno, name, kw.value


def _is_allowed(value: ast.expr) -> bool:
    if isinstance(value, ast.Constant):
        return isinstance(value.value, str)
    if isinstance(value, ast.Name):
        return value.id in _ALLOWED_PARAM_NAMES or value.id in _ALLOWED_PROMPT_CONSTANTS
    if isinstance(value, ast.Call):
        func = value.func
        callee = func.id if isinstance(func, ast.Name) else (
            func.attr if isinstance(func, ast.Attribute) else None)
        return callee in _ALLOWED_CALL_NAMES
    return False


def test_gap2_gated_entrypoints_system_prompt_args_are_whitelisted():
    """差距②钉：受闸入口的 system_prompt 实参必须是允许名单形态。

    域外形态（例如把 payload/请求内容变量、f-string 拼接直接塞进
    execute_ai_prompt(system_prompt=…)）即红——新调用点须对照契约 §2 表登记。
    """
    violations = [
        f"{rel}:{lineno} {fname}(system_prompt={type(value).__name__})"
        for rel, lineno, fname, value in _iter_gated_calls()
        if not _is_allowed(value)
    ]
    assert violations == [], f"system_prompt 实参来源不在允许名单（契约 §2 表登记）：{violations}"


def test_gap2_entrypoint_surface_unchanged():
    """附钉：受闸函数集合不静默扩大——有人新增外放入口（新形参名/新函数）
    却不进本钉允许名单时，此钉先红提醒登记。"""
    # 定义落点（历史锚定；移动文件即红，防止定义漂移出受闸文件面）
    assert "def direct_tool_completion(" in (
        SRC / "control" / "ai_tool_loop.py").read_text(encoding="utf-8")
    text = (SRC / "control" / "ai_server_client.py").read_text(encoding="utf-8")
    for fn in ("execute_ai_prompt", "direct_provider_completion", "_degraded_direct_result"):
        assert f"def {fn}(" in text, f"受闸函数 {fn} 定义消失了？"


def test_gap2_no_new_kwarg_passthrough_into_system_prompt():
    """附钉：禁「kwargs 透传进 system_prompt」模式——形参直传链必须显式
    命名（system_prompt=system_prompt），不允许 **kwargs 展开把任意键注入
    system_prompt 位置（绕过 AST 形态判定）。"""
    violations = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = func.id if isinstance(func, ast.Name) else (
                    func.attr if isinstance(func, ast.Attribute) else None)
                if name in GATED_FUNCTIONS:
                    has_kwexpansion = any(kw.arg is None for kw in node.keywords)
                    if has_kwexpansion:
                        rel = str(path.relative_to(SRC)).replace("\\", "/")
                        violations.append(f"{rel}:{node.lineno} {name}(**…)")
    assert violations == [], f"受闸入口不允许 **kwargs 展开（须显式命名实参）：{violations}"
