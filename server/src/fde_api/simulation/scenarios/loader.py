"""场景装载与视图切分（V3.2 G2，G1 §4.3 的技术落点）。

**装载器是唯一入口**：任何代码要拿场景内容，必须经 ``load_view`` 取得某个
视图，不得直接读 ``content_json`` / ``reference_json`` 字段。装载后立即做
递归泄漏自检——命中即抛错（宁可装载失败，也不把答案喂给被测方）。

三个视图的可见面见 ``fde_api.simulation.schemas`` 模块文档。
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from fde_api.simulation.schemas import (
    ANSWER_SIDE_KEYS,
    CUSTOMER_SIDE_KEYS,
    SCENARIO_VIEWS,
    contains_forbidden_keys,
)

SEEDS_DIR = Path(__file__).resolve().parent.parent / "seeds"


class ScenarioLeakError(Exception):
    """装载后泄漏自检失败：视图里出现了不该可见的键。"""

    def __init__(self, code: str, message: str, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or {}

    def __str__(self) -> str:  # pragma: no cover - 调试用
        return f"{self.code}: {self.message}"


def _forbidden_for(view: str) -> frozenset[str]:
    if view == "tester":
        return ANSWER_SIDE_KEYS | CUSTOMER_SIDE_KEYS
    if view == "customer":
        return ANSWER_SIDE_KEYS
    return frozenset()


def load_view(
    content: dict[str, Any],
    reference: dict[str, Any] | None,
    view: str,
) -> dict[str, Any]:
    """按视图装载场景内容。

    - ``tester``：只有客户初始简报、已知系统与既定约束（其余须追问获得）。
    - ``customer``：客户侧全部真相（画像/隐藏事实/变体覆盖/故障注入/种子数据）。
    - ``judge``：``content`` + ``reference`` 全量。

    装载后做递归泄漏自检；命中即抛 ``ScenarioLeakError``。
    """
    if view not in SCENARIO_VIEWS:
        raise ScenarioLeakError(
            "invalid_view", f"未知装载视图：{view}", {"view": view}
        )
    if not isinstance(content, dict):
        raise ScenarioLeakError("invalid_content", "场景内容必须是对象。")

    if view == "tester":
        visible = content.get("visible")
        visible = visible if isinstance(visible, dict) else {}
        payload: dict[str, Any] = {
            "brief": copy.deepcopy(visible.get("initial_brief") or []),
            "known_systems": copy.deepcopy(visible.get("known_systems") or []),
            "constraints": copy.deepcopy(visible.get("constraints") or {}),
        }
    elif view == "customer":
        payload = copy.deepcopy(content)
    else:
        payload = copy.deepcopy(content)
        if reference is not None:
            payload["reference"] = copy.deepcopy(reference)

    hits = contains_forbidden_keys(payload, _forbidden_for(view))
    if hits:
        raise ScenarioLeakError(
            "reference_leak",
            "装载视图包含不可见键，拒绝装载。",
            {"view": view, "paths": hits[:10]},
        )
    return payload


def materialize_variant(content: dict[str, Any], variant: str) -> dict[str, Any]:
    """把基线场景（normal）物化成指定变体的**独立**场景内容。

    变体覆盖来自 ``content["variant_overrides"][variant]``：
    ``extra_constraints`` 追加到既定约束、``budget``/``timeline`` 覆盖约束值、
    ``probe_tolerance`` 调整追问容忍度、``conflicts`` 注入部门冲突、
    ``change_events`` 注入需求变更事件、``suppress_facts`` 抑制部分隐藏事实、
    ``extra_known_systems`` 追加客户自述系统。

    物化后**移除** ``variant_overrides`` 本身——物化结果是自包含的独立场景，
    不再依赖基线场景。normal 变体为基线副本（同样移除 variant_overrides）。
    """
    if not isinstance(content, dict):
        raise ScenarioLeakError("invalid_content", "场景内容必须是对象。")
    overrides_all = content.get("variant_overrides")
    overrides_all = overrides_all if isinstance(overrides_all, dict) else {}
    override = overrides_all.get(variant)
    override = override if isinstance(override, dict) else {}

    result = copy.deepcopy(content)
    result.pop("variant_overrides", None)

    visible = result.get("visible")
    if not isinstance(visible, dict):
        visible = {}
        result["visible"] = visible
    constraints = visible.get("constraints")
    constraints = copy.deepcopy(constraints) if isinstance(constraints, dict) else {}

    extra_constraints = override.get("extra_constraints")
    if isinstance(extra_constraints, list):
        existing = constraints.get("extra")
        merged = list(existing) if isinstance(existing, list) else []
        for item in extra_constraints:
            if isinstance(item, str) and item.strip() and item not in merged:
                merged.append(item)
        constraints["extra"] = merged
    for key in ("budget", "timeline"):
        if isinstance(override.get(key), str) and override[key].strip():
            constraints[key] = override[key]
    visible["constraints"] = constraints

    extra_systems = override.get("extra_known_systems")
    if isinstance(extra_systems, list):
        known = visible.get("known_systems")
        known = list(known) if isinstance(known, list) else []
        for item in extra_systems:
            if isinstance(item, str) and item.strip() and item not in known:
                known.append(item)
        visible["known_systems"] = known

    probe_tolerance = override.get("probe_tolerance")
    if isinstance(probe_tolerance, int) and probe_tolerance >= 0:
        result["probe_tolerance"] = probe_tolerance

    conflicts = override.get("conflicts")
    if isinstance(conflicts, list) and conflicts:
        result["conflicts"] = copy.deepcopy(conflicts)

    change_events = override.get("change_events")
    if isinstance(change_events, list) and change_events:
        result["change_events"] = copy.deepcopy(change_events)

    suppress = override.get("suppress_facts")
    if isinstance(suppress, list) and suppress:
        blocked = {item for item in suppress if isinstance(item, str)}
        hidden = result.get("hidden")
        if isinstance(hidden, dict) and isinstance(hidden.get("facts"), list):
            hidden["facts"] = [
                fact
                for fact in hidden["facts"]
                if not (isinstance(fact, dict) and fact.get("fact_id") in blocked)
            ]
    return result


def load_case_file(path: Path) -> dict[str, Any]:
    """读取一个案例种子文件（JSON）。"""
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ScenarioLeakError("invalid_content", f"案例文件必须是对象：{path.name}")
    return data


def list_case_files() -> list[Path]:
    """列出案例种子文件（按文件名排序，顺序稳定）。"""
    if not SEEDS_DIR.exists():
        return []
    return sorted(SEEDS_DIR.glob("CASE-*.json"))
