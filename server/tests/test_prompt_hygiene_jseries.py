"""外部文字禁入与原件派生分离契约 J 系判据（B#12+B#31 接线）。

契约：`docs/architecture/外部文字禁入与原件派生分离契约-v1.md` §5——判据接线轮。
组织同 B#4 purity 测试（静态 AST/文本扫描，零运行时依赖），零迁移零路由零依赖。

- J-1（静态）：全仓 system role 消息组装点枚举钉——content 必须是「白名单形态」：
  常量 / 常量名引用 / 形参直传链（system_prompt）/ 已登记例外。新增组装点
  引入域外变量名或形态即红（PR 须对照契约 §2 表登记）。
- J-2（行为）：file_read / help_fetch / lcsc_search / lcsc_runs_read 四类
  「不可信外部资料」工具结果必须带结果级 source 标记（P-3 二者其一的标记腿）。
- J-3（静态）：documents/ai_content 的 system 提示词是纯常量构造——构造表达式
  不得引用 payload / 请求内容变量（「构造即固定」钉）。
"""
from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "fde_api"

# ---------------------------------------------------------------------------
# J-1：system 组装点形态白名单
# ---------------------------------------------------------------------------

# 形参直传链（上游实参已在契约 §2 表逐点登记来源）：变量名允许清单。
# 上游来源 = chat.py:187 _workbench_system_prompt()（常量+config+内置手册）/
# executor.py:1098 治理面发布 instructions / structured 固定常量。
_SYSTEM_PROMPT_PARAM_NAMES = {"system_prompt"}

# 已登记例外（契约 §2 表锚定，逐符号登记；域外新增即红）：
# - lcsc_desktop.instruction / lcsc_other.RULES：模块级常量变量，
#   与常量拼接不可信框架文案（P-3 框架腿），来源是我方代码常量。
# - guidance/ai_prompt.file_content：客户 DOCX 经 AI 文件服务**原生提取**的
#   内容按 Kimi 文件语义随 system 传递（kimi.py analyze_docx_json 合同），
#   提取后原文不落库；边界如实登记于契约 §4 差距④同类（不收窄，需另拍板）。
# - guidance/ai_prompt.source_ref：我方生成的「kimi-file:<版本id>」证据键
#   （结构化引用，非外部文字），f-string 内插进 system 模板。
# - industry_template.context：**DB 模块目录**（ModuleCatalog，admin 治理面
#   维护）的 JSON 序列化——治理面数据的结构化投影，非外部不可信文字。
# - project_draft.catalog_text：同上，DB 模块目录的文本投影。
_KNOWN_EXCEPTION_VARIABLES = {
    "GENERATION_SYSTEM_PROMPT",  # industry_template_prompt.py 模块常量
    "SYSTEM_PROMPT",             # research_form_prompt.py 模块常量
    "instruction",               # lcsc_desktop.py 函数内常量拼接
    "RULES",                     # lcsc_other.py 模块常量
    "file_content",              # guidance/ai_prompt.py:51（已登记例外）
    "source_ref",                # guidance/ai_prompt.py:31 内插（我方证据键）
    "context",                   # industry_template_prompt.py:32（DB 目录投影）
    "catalog_text",              # project_draft.py:69（DB 目录投影）
    "system",                    # documents/ai_content.py 本函数常量定义（J-3 另钉）
}


def _system_message_contents(path: Path) -> list[tuple[int, ast.expr]]:
    """收集单个文件中所有 system role 消息的 content 表达式（含行号）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[tuple[int, ast.expr]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            role_val = content_val = None
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value == "role":
                    role_val = v
                elif isinstance(k, ast.Constant) and k.value == "content":
                    content_val = v
            if (
                isinstance(role_val, ast.Constant)
                and role_val.value == "system"
                and content_val is not None
            ):
                found.append((node.lineno, content_val))
    return found


def _is_static_text(node: ast.expr) -> bool:
    """常量字符串 / 常量拼接 / 常量 f-string——构造即固定的静态文本。"""
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str)
    if isinstance(node, ast.JoinedStr):
        for part in node.values:
            if isinstance(part, ast.FormattedValue):
                if not _is_static_text(part.value):
                    return False
            elif not isinstance(part, ast.Constant):
                return False
        return True
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _is_static_text(node.left) and _is_static_text(node.right)
    if isinstance(node, ast.Name):
        # 常量名（大写蛇形=模块常量惯例）或已登记例外
        return node.id.isupper() or node.id in _KNOWN_EXCEPTION_VARIABLES
    if isinstance(node, ast.Call):
        # 白名单函数：_workbench_system_prompt()（chat 组装器，白名单③）
        func = node.func
        return isinstance(func, ast.Name) and func.id == "_workbench_system_prompt"
    return False


def test_j1_system_message_contents_are_whitelisted_shapes():
    """J-1：全仓 system role content 必须是白名单形态/变量；域外新增即红。"""
    violations: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        for lineno, content in _system_message_contents(path):
            if _is_static_text(content):
                continue
            if (
                isinstance(content, ast.Name)
                and content.id in _SYSTEM_PROMPT_PARAM_NAMES
            ):
                continue  # 形参直传链（上游来源已逐点登记）
            rel = str(path.relative_to(SRC)).replace("\\", "/")
            violations.append(f"{rel}:{lineno} content={type(content).__name__}:{getattr(content, 'id', '')}")
    assert violations == [], f"新增 system 组装点未按契约 §2 表登记：{violations}"


def test_j1_executors_system_prompt_call_site_is_still_governed_instructions():
    """J-1 附钉：executor skill 节点 system_prompt 仍=治理面发布 instructions（T-S1）。

    若有人把运行期外部文字接进该实参，说明白名单④被旁路——直接转红。
    """
    path = SRC / "workflows" / "executor.py"
    matches = [
        (node.lineno, kw.value)
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call)
        for kw in node.keywords
        if kw.arg == "system_prompt"
    ]
    assert matches, "executor 的 system_prompt 调用点消失了？"
    for lineno, value in matches:
        assert isinstance(value, ast.Name) and value.id == "instructions", (
            f"executor.py:{lineno} system_prompt 实参不再是治理面 instructions 变量"
        )


# ---------------------------------------------------------------------------
# J-2：不可信资料工具的结果级 source 标记（P-3 标记腿）
# ---------------------------------------------------------------------------

# 四类工具的 source 标记期望值（工具面「不可信资料」框架的结果级落地）。
_EXPECTED_SOURCE_MARKS = {
    "mcp_gateway.py": {
        '"source": "untrusted_project_file"',      # file_read（既有）
        "'source': 'untrusted_storefront_content'",  # lcsc_runs_read（本轮补）
    },
    "help_bundle.py": {
        '"source": "workbench_help_manual"',       # help_fetch（既有）
    },
    "lcsc_skills.py": {
        '"source": "untrusted_storefront_content"',  # lcsc_search=_serialize（本轮补）
    },
}


def test_j2_untrusted_material_tools_carry_source_marks():
    """J-2：四类不可信资料工具的结果体必须自带 source 标记（文本级锚定）。"""
    violations: list[str] = []
    for filename, needles in _EXPECTED_SOURCE_MARKS.items():
        text = (SRC / "control" / filename).read_text(encoding="utf-8")
        for needle in needles:
            if needle not in text:
                violations.append(f"control/{filename} 缺标记 {needle}")
    assert violations == []


def test_j2_lcsc_serialize_is_the_single_shape_source():
    """J-2 附钉：lcsc_search 与 lcsc_runs_read 共用 _serialize 形状源——
    标记只在一处添加；若有人绕开 _serialize 自行构造 run 返回体即红。"""
    text = (SRC / "control" / "lcsc_skills.py").read_text(encoding="utf-8")
    serialize_defs = text.count("def _serialize(")
    assert serialize_defs == 1
    # run_lcsc_skill 的 HTTP 直跑路径返回 _serialize(run)（不另造形状）
    assert "output = _serialize(run)" in text


# ---------------------------------------------------------------------------
# J-3：ai_content 的 system 提示词构造即固定
# ---------------------------------------------------------------------------


def test_j3_ai_content_system_is_a_pure_constant_expression():
    """J-3：documents/ai_content 的 system 是纯常量元组拼接——构造表达式
    不得引用 payload / 请求内容变量（「构造即固定」，契约 §5-J-3）。"""
    path = SRC / "documents" / "ai_content.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[ast.expr] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "system":
                    found.append(node.value)
    assert len(found) == 1, f"system 定义应恰一处，实得 {len(found)}"
    expr = found[0]
    if isinstance(expr, ast.Constant):
        ok = isinstance(expr.value, str)
    else:
        # 允许 BinOp/Add 拼接与括号元组隐式拼接（ast.BinOp 树），拒绝任何 Name/Call 插值
        def pure_static(n: ast.expr) -> bool:
            if isinstance(n, ast.Constant):
                return isinstance(n.value, str)
            if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add):
                return pure_static(n.left) and pure_static(n.right)
            return False
        ok = pure_static(expr)
    assert ok, "ai_content 的 system 构造引用了非常量表达式（payload 变量泄漏进 system）"
