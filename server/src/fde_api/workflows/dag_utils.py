"""工作流 DAG / 占位符纯函数（架构评估 P1-2：从 executor.py 拆出）。

本模块**零 IO**：只做 DAG 节点抽取、确定性拓扑序（Kahn + 字典序稳定）、占位符
解析与 when 真值裁决。调用方（executor 门面 / dispatch / recovery）只从这里取
纯函数，不在这里反向依赖任何有副作用的模块。
"""
from __future__ import annotations

import json
import re
from typing import Any

from fde_api.workflows.constants import WorkflowRunError, _MissingPlaceholder
from fde_api.workflows.definition_service import PLACEHOLDER_PATTERN


def _dag_nodes(dag: Any) -> list[dict[str, Any]]:
    nodes = dag.get("nodes") if isinstance(dag, dict) else None
    if not isinstance(nodes, list) or not nodes:
        raise WorkflowRunError("dag_invalid", "定义快照损坏：nodes 缺失。", 422)
    return [node for node in nodes if isinstance(node, dict)]


def _topo_order(dag_nodes: list[dict[str, Any]]) -> list[str]:
    """执行器侧确定性拓扑序（Kahn，key 字典序稳定）；定义期已过环检测，
    防御性场景下的部分序由主循环迭代上限兜底。"""
    by_key = {str(node["key"]): node for node in dag_nodes}
    indegree = {key: 0 for key in by_key}
    children: dict[str, list[str]] = {key: [] for key in by_key}
    for key, node in by_key.items():
        for dep in node.get("depends_on") or []:
            dep_key = str(dep)
            if dep_key in by_key:
                indegree[key] += 1
                children[dep_key].append(key)
    queue = sorted(key for key, degree in indegree.items() if degree == 0)
    order: list[str] = []
    while queue:
        key = queue.pop(0)
        order.append(key)
        for child in children[key]:
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
                queue.sort()
    return order


def _lookup(path: str, context: dict[str, Any], outputs: dict[str, Any]) -> Any:
    root, _, rest = path.partition(".")
    if root in context:
        value: Any = context[root]
    elif root in outputs:
        value = outputs[root]
    else:
        raise _MissingPlaceholder(path)
    for part in (part for part in rest.split(".") if part):
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            raise _MissingPlaceholder(path)
    return value


def _resolve_value(
    value: Any, context: dict[str, Any], outputs: dict[str, Any]
) -> Any:
    """深解析：整串单占位符 → 原类型替换（不字符串化）；内嵌占位符 → 字符串插值；
    缺键 → _MissingPlaceholder（节点 failed，绝不填空串——修 fde-v2 缺陷）。"""
    if isinstance(value, str):
        whole = PLACEHOLDER_PATTERN.fullmatch(value.strip())
        if whole:
            return _lookup(whole.group(1), context, outputs)

        def _substitute(match: re.Match[str]) -> str:
            resolved = _lookup(match.group(1), context, outputs)
            if isinstance(resolved, str):
                return resolved
            return json.dumps(resolved, ensure_ascii=False)

        return PLACEHOLDER_PATTERN.sub(_substitute, value)
    if isinstance(value, dict):
        return {k: _resolve_value(v, context, outputs) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_value(item, context, outputs) for item in value]
    return value


def _when_truthy(when: Any, context: dict[str, Any], outputs: dict[str, Any]) -> bool:
    """T-W3 最小语义：when 仅支持整串单占位符，取其 JSON 值的 Python 真值；
    缺键/其它形态一律 False（诚实不猜）。表达式引擎待真实需求。"""
    if not isinstance(when, str):
        return False
    whole = PLACEHOLDER_PATTERN.fullmatch(when.strip())
    if whole is None:
        return False
    try:
        return bool(_lookup(whole.group(1), context, outputs))
    except _MissingPlaceholder:
        return False
