"""AF2-WP2 TransformPlan 计划面：类型化 Schema + 九算子白名单 + 结构静态校验器。

计划面纪律（15 号 §2 D2 分阶段落地口径 / 03 §5 / 04 §3.2）：

- 计划是**类型化声明**：算子走九算子闭集、每算子参数键集精确匹配——
  **多余键即拒**（``expr``/``sql``/``script``/``template`` 等自由文本槽
  结构上不存在），嵌入 SQL/Python/模板/表达式因此不可能（03 §5）；
- 值域枚举化：时区走 IANA tzdata（zoneinfo）、单位走受控量纲表（跨量纲
  即拒）、枚举映射与质量断言走闭集 kind；
- 04 §3.2 显式定义逐项 fail-closed（缺声明即校验失败）：日期时区 =
  ``normalize_datetime.to_tz``；Decimal 与舍入 = ``cast(to_type=decimal)``
  必带 ``scale``+``rounding``；空值 = ``policies.null_handling``；重复
  主键 = ``policies.duplicate_key``；Join 基数 = ``join.cardinality``；
  丢弃/拒绝记录 = ``policies.reject_record``；
- op 级依赖 DAG：无环 + 稳定拓扑序（兼作血缘骨架）；单 sink 语义——
  最终 schema 沿拓扑序演进，output 声明须与产出集精确一致；
- 受限 Join（03 §77）：Join 只接受显式声明键对——``basis=fk_catalog``
  的证据键对（右表+右列）须在计划 relations 段查得；``declared_by_plan``
  仅表示人工声明。relations 段**无生产态字段**（``status``/``promoted``
  等多余键即拒）——计划内无关系候选翻产通道。

编译面（算子 step → logic_engine AST 求值）归 WP3 design-first 门：本
模块**只产出声明与校验报告**，不产生任何可执行工件、不做任何 I/O。
"""
from __future__ import annotations

from zoneinfo import ZoneInfo
from typing import Any

PLAN_VERSION = "af2-wp2-v1"

# 类型词表（输入/输出列与 cast 目标共用；cast 兼容矩阵单列）
TYPE_VOCAB = ("string", "integer", "number", "decimal", "boolean", "date", "datetime", "enum")

# 九算子闭集（03 §5 WP2 行原文六类拆到可执行粒度）
OPERATOR_WHITELIST = (
    "select",
    "rename",
    "cast",
    "normalize_datetime",
    "convert_unit",
    "map_enum",
    "dedup",
    "join",
    "assert_quality",
)

# 04 §3.2 三策略显式定义：键闭集 + 值闭集（缺键/多余键/坏值一律拒）
POLICY_KEYS = ("null_handling", "reject_record", "duplicate_key")
POLICY_VALUES: dict[str, tuple[str, ...]] = {
    "null_handling": ("reject", "keep_null"),
    "reject_record": ("collect", "count"),
    "duplicate_key": ("error", "keep_first"),
}

# cast 类型兼容矩阵（to_type → 允许的来源类型集）：字符串→时间类型拒
# （计划面无格式声明槽，解析语义不确定=不可静态判定，fail-closed）
_CAST_COMPAT: dict[str, set[str]] = {
    "string": {"string"},
    "integer": {"integer", "string", "number", "decimal"},
    "number": {"number", "string", "integer", "decimal"},
    "decimal": {"decimal", "string", "integer", "number"},
    "boolean": {"boolean", "integer"},
    "date": {"date"},
    "datetime": {"datetime"},
    "enum": {"enum", "string"},
}
DECIMAL_SCALE_MAX = 28
ROUNDING_MODES = ("half_up", "half_even", "floor", "ceiling")

# 受控单位换算表（量纲 → 单位闭集）：跨量纲换算在计划面即拒
_UNIT_DIMENSIONS: dict[str, str] = {
    "mm": "length",
    "cm": "length",
    "m": "length",
    "km": "length",
    "g": "mass",
    "kg": "mass",
    "t": "mass",
    "s": "time",
    "min": "time",
    "h": "time",
}

_JOIN_BASES = ("fk_catalog", "declared_by_plan")
_JOIN_CARDINALITIES = ("one_to_one", "many_to_one")  # one_to_many 行爆炸=计划面拒
_QUALITY_KINDS = ("not_null", "unique")
_UNMAPPED_MODES = ("error", "keep")

_RELATION_KEYS = frozenset({"left_table", "right_table", "left_column", "right_column", "basis"})
_SOURCE_KEYS = frozenset({"profile_id", "table"})
_STEP_KEYS = frozenset({"id", "op", "params", "depends_on"})


def _err(errors: list[dict[str, str]], code: str, path: str, message: str) -> None:
    errors.append({"code": code, "path": path, "message": message})


def _is_str(v: Any) -> bool:
    return isinstance(v, str) and bool(v.strip())


def _check_columns_decl(
    errors: list[dict[str, str]],
    raw: Any,
    path: str,
) -> dict[str, str]:
    """列声明段（input/output 共用）：[{name, type}]，名唯一、类型在词表。

    返回 ``名→类型`` 映射（畸形段返回空映射，错误已逐条登记）。
    """
    if not isinstance(raw, list) or not raw:
        _err(errors, "invalid_parameter_value", path, "列声明须为非空数组。")
        return {}
    columns: dict[str, str] = {}
    for i, item in enumerate(raw):
        item_path = f"{path}[{i}]"
        if not isinstance(item, dict) or set(item) != {"name", "type"}:
            _err(errors, "unexpected_parameter", item_path, "列声明键集须精确为 {name, type}。")
            continue
        name, col_type = item["name"], item["type"]
        if not _is_str(name):
            _err(errors, "invalid_parameter_value", f"{item_path}.name", "列名须为非空字符串。")
            continue
        if name in columns:
            _err(errors, "duplicate_column", item_path, f"列 {name} 重复声明。")
            continue
        if col_type not in TYPE_VOCAB:
            _err(errors, "invalid_parameter_value", f"{item_path}.type", f"未知类型 {col_type!r}。")
            continue
        columns[name] = col_type
    return columns


def _check_policies(errors: list[dict[str, str]], raw: Any) -> None:
    if not isinstance(raw, dict):
        _err(errors, "invalid_parameter_value", "policies", "策略段缺失或非对象。")
        return
    for key in POLICY_KEYS:
        if key not in raw:
            # 04 §3.2 fail-closed：空值/拒绝记录/重复主键策略必须显式定义
            _err(errors, "invalid_parameter_value", f"policies.{key}", f"策略 {key} 必须显式声明。")
    for key in raw:
        if key not in POLICY_KEYS:
            _err(errors, "unexpected_parameter", f"policies.{key}", f"未知策略键 {key}。")
    for key, allowed in POLICY_VALUES.items():
        if key in raw and raw[key] not in allowed:
            _err(
                errors,
                "invalid_parameter_value",
                f"policies.{key}",
                f"值 {raw[key]!r} 不在闭集 {allowed} 内。",
            )


def _check_relations(errors: list[dict[str, str]], raw: Any) -> list[dict[str, Any]]:
    """关系候选段：键集精确五键、无生产态字段（status/promoted 即拒）。"""
    if not isinstance(raw, list):
        _err(errors, "invalid_parameter_value", "relations", "关系段缺失或非数组。")
        return []
    relations: list[dict[str, Any]] = []
    for i, item in enumerate(raw):
        item_path = f"relations[{i}]"
        if not isinstance(item, dict):
            _err(errors, "invalid_parameter_value", item_path, "关系声明须为对象。")
            continue
        for key in item:
            if key not in _RELATION_KEYS:
                _err(errors, "unexpected_parameter", f"{item_path}.{key}", f"关系段无 {key} 字段（无生产态）。")
        for key in _RELATION_KEYS:
            if key not in item:
                _err(errors, "missing_parameter", f"{item_path}.{key}", f"关系声明缺 {key}。")
        if set(item) == _RELATION_KEYS:
            if item["basis"] not in _JOIN_BASES:
                _err(
                    errors,
                    "invalid_parameter_value",
                    f"{item_path}.basis",
                    f"basis {item['basis']!r} 不在闭集 {_JOIN_BASES} 内。",
                )
            for key in ("left_table", "right_table", "left_column", "right_column"):
                if not _is_str(item[key]):
                    _err(errors, "invalid_parameter_value", f"{item_path}.{key}", "须为非空字符串。")
            relations.append(item)
    return relations


def _fk_evidence_exists(relations: list[dict[str, Any]], right_table: Any, right_key: Any) -> bool:
    return any(
        rel.get("basis") == "fk_catalog"
        and rel.get("right_table") == right_table
        and rel.get("right_column") == right_key
        for rel in relations
    )


def _check_step_params(errors: list[dict[str, str]], step: dict[str, Any], path: str) -> None:
    """schema 无关检查：op 白名单 + 参数键集精确匹配 + 值域枚举。"""
    op = step.get("op")
    params = step.get("params")
    if params is None or not isinstance(params, dict):
        _err(errors, "missing_parameter", f"{path}.params", "params 必须为对象。")
        return
    p_path = f"{path}.params"

    def _reject_extra(allowed: set[str]) -> None:
        # 多余键即拒：自由文本槽（expr/sql/script/template…）结构上不存在
        for key in params:
            if key not in allowed:
                _err(errors, "unexpected_parameter", f"{p_path}.{key}", f"算子 {op} 不接受参数 {key}。")

    def _require(*keys: str) -> bool:
        missing = [key for key in keys if key not in params]
        for key in missing:
            _err(errors, "missing_parameter", f"{p_path}.{key}", f"算子 {op} 缺必填参数 {key}。")
        return not missing

    if op == "select":
        _reject_extra({"columns"})
        if not _require("columns"):
            return
        raw = params["columns"]
        if not isinstance(raw, list) or not raw or not all(_is_str(c) for c in raw):
            _err(errors, "invalid_parameter_value", f"{p_path}.columns", "columns 须为非空字符串数组。")
    elif op == "rename":
        _reject_extra({"mapping"})
        if not _require("mapping"):
            return
        raw = params["mapping"]
        if not isinstance(raw, dict) or not raw or not all(
            _is_str(k) and _is_str(v) for k, v in raw.items()
        ):
            _err(errors, "invalid_parameter_value", f"{p_path}.mapping", "mapping 须为非空 {旧名: 新名} 对象。")
    elif op == "cast":
        to_type = params.get("to_type")
        allowed = {"column", "to_type"}
        if to_type == "decimal":
            allowed |= {"scale", "rounding"}
        _reject_extra(allowed)
        if not _require("column", "to_type"):
            return
        if to_type not in TYPE_VOCAB:
            _err(errors, "invalid_parameter_value", f"{p_path}.to_type", f"未知目标类型 {to_type!r}。")
        if to_type == "decimal":
            # 04 §3.2：Decimal 与舍入必须显式定义——缺一即拒
            if "scale" not in params or "rounding" not in params:
                _err(
                    errors,
                    "missing_parameter",
                    p_path,
                    "cast 到 decimal 必须显式声明 scale 与 rounding。",
                )
            scale = params.get("scale")
            if scale is not None and (isinstance(scale, bool) or not isinstance(scale, int) or not 0 <= scale <= DECIMAL_SCALE_MAX):
                _err(errors, "invalid_parameter_value", f"{p_path}.scale", "scale 须为 0..28 整数。")
            if "rounding" in params and params["rounding"] not in ROUNDING_MODES:
                _err(
                    errors,
                    "invalid_parameter_value",
                    f"{p_path}.rounding",
                    f"rounding {params['rounding']!r} 不在闭集 {ROUNDING_MODES} 内。",
                )
    elif op == "normalize_datetime":
        _reject_extra({"column", "to_tz"})
        if not _require("column", "to_tz"):
            return
        to_tz = params["to_tz"]
        if not _is_str(to_tz):
            _err(errors, "invalid_parameter_value", f"{p_path}.to_tz", "to_tz 须为 IANA 时区名。")
        else:
            try:
                ZoneInfo(to_tz)
            except Exception:
                _err(errors, "invalid_parameter_value", f"{p_path}.to_tz", f"未知 IANA 时区 {to_tz!r}。")
    elif op == "convert_unit":
        _reject_extra({"column", "from_unit", "to_unit"})
        if not _require("column", "from_unit", "to_unit"):
            return
        from_unit, to_unit = params["from_unit"], params["to_unit"]
        from_dim, to_dim = _UNIT_DIMENSIONS.get(from_unit), _UNIT_DIMENSIONS.get(to_unit)
        if from_dim is None or to_dim is None:
            _err(
                errors,
                "invalid_parameter_value",
                f"{p_path}.from_unit",
                f"单位 {from_unit!r}/{to_unit!r} 不在受控单位表内。",
            )
        elif from_dim != to_dim:
            _err(
                errors,
                "invalid_parameter_value",
                f"{p_path}.to_unit",
                f"跨量纲换算被拒（{from_dim} → {to_dim}）。",
            )
    elif op == "map_enum":
        _reject_extra({"column", "mapping", "unmapped"})
        if not _require("column", "mapping", "unmapped"):
            return
        raw = params["mapping"]
        if not isinstance(raw, dict) or not raw or not all(_is_str(k) and _is_str(v) for k, v in raw.items()):
            _err(errors, "invalid_parameter_value", f"{p_path}.mapping", "mapping 须为非空 {原值: 新值} 对象。")
        if params["unmapped"] not in _UNMAPPED_MODES:
            _err(
                errors,
                "invalid_parameter_value",
                f"{p_path}.unmapped",
                f"unmapped {params['unmapped']!r} 不在闭集 {_UNMAPPED_MODES} 内。",
            )
    elif op == "dedup":
        _reject_extra({"keys"})
        if not _require("keys"):
            return
        raw = params["keys"]
        if not isinstance(raw, list) or not raw or not all(_is_str(k) for k in raw):
            _err(errors, "invalid_parameter_value", f"{p_path}.keys", "keys 须为非空字符串数组。")
    elif op == "join":
        # 04 §3.2：Join 基数必须显式定义（cardinality 缺失即拒）
        # AF2-WP3 additive：right_columns＝右列投影显式声明（可选键；最小暴露——
        # 不声明则不带右列产出；17 号 §3.2 编码期细化）
        _reject_extra({"left_key", "right_table", "right_key", "cardinality", "basis", "right_columns"})
        if not _require("left_key", "right_table", "right_key", "cardinality", "basis"):
            return
        if params["cardinality"] not in _JOIN_CARDINALITIES:
            _err(
                errors,
                "invalid_parameter_value",
                f"{p_path}.cardinality",
                f"cardinality {params['cardinality']!r} 不在闭集 {_JOIN_CARDINALITIES} 内。",
            )
        if params["basis"] not in _JOIN_BASES:
            _err(
                errors,
                "invalid_parameter_value",
                f"{p_path}.basis",
                f"basis {params['basis']!r} 不在闭集 {_JOIN_BASES} 内。",
            )
        if "right_columns" in params:
            raw = params["right_columns"]
            if not isinstance(raw, list) or not raw or not all(_is_str(c) for c in raw):
                _err(
                    errors,
                    "invalid_parameter_value",
                    f"{p_path}.right_columns",
                    "right_columns 须为非空字符串数组（右列投影显式声明）。",
                )
    elif op == "assert_quality":
        _reject_extra({"kind", "column"})
        if not _require("kind", "column"):
            return
        if params["kind"] not in _QUALITY_KINDS:
            _err(
                errors,
                "invalid_parameter_value",
                f"{p_path}.kind",
                f"断言 kind {params['kind']!r} 不在闭集 {_QUALITY_KINDS} 内。",
            )


def _check_step_schema(
    errors: list[dict[str, str]],
    step: dict[str, Any],
    path: str,
    schema: dict[str, str],
    relations: list[dict[str, Any]],
) -> dict[str, str]:
    """schema 相关检查（列引用/类型兼容/Join 证据）+ 类型演进，返回新 schema。"""
    op = step.get("op")
    params = step.get("params")
    if not isinstance(params, dict):
        return dict(schema)
    p_path = f"{path}.params"

    def _column(name: Any, key_path: str = "column") -> str | None:
        if not _is_str(name) or name not in schema:
            _err(errors, "unknown_column", f"{p_path}.{key_path}", f"列 {name!r} 不在当前产出集内。")
            return None
        return str(name)

    if op == "select":
        raw = params.get("columns")
        if not isinstance(raw, list) or not all(isinstance(c, str) for c in raw):
            return dict(schema)
        if len(set(raw)) != len(raw):
            _err(errors, "duplicate_column", f"{p_path}.columns", "select 列表存在重复列。")
        for col in raw:
            _column(col, "columns")
        return {c: schema[c] for c in raw if c in schema}
    if op == "rename":
        raw = params.get("mapping")
        if not isinstance(raw, dict) or not raw:
            return dict(schema)
        renamed_keys = [k for k in raw if isinstance(k, str)]
        for old in renamed_keys:
            if old not in schema:
                _err(errors, "unknown_column", f"{p_path}.mapping.{old}", f"列 {old} 不在当前产出集内。")
        staying = {name for name in schema if name not in renamed_keys}
        targets = [v for v in raw.values() if isinstance(v, str)]
        if len(set(targets)) != len(targets):
            _err(errors, "duplicate_column", f"{p_path}.mapping", "多个列重命名到同一目标名。")
        for old, new in raw.items():
            if isinstance(new, str) and new in staying:
                _err(
                    errors,
                    "duplicate_column",
                    f"{p_path}.mapping.{old}",
                    f"重命名目标 {new} 与既有列冲突。",
                )
        return {raw.get(name, name): col_type for name, col_type in schema.items()}
    if op == "cast":
        col = _column(params.get("column"))
        to_type = params.get("to_type")
        if col is None or to_type not in TYPE_VOCAB:
            return dict(schema)
        current = schema[col]
        if current not in _CAST_COMPAT[str(to_type)]:
            _err(
                errors,
                "type_incompatible",
                p_path,
                f"{current} → {to_type} 不在 cast 兼容矩阵内。",
            )
            return dict(schema)
        evolved = dict(schema)
        evolved[col] = str(to_type)
        return evolved
    if op == "normalize_datetime":
        col = _column(params.get("column"))
        if col is None:
            return dict(schema)
        if schema[col] not in ("date", "datetime"):
            _err(errors, "type_incompatible", p_path, f"normalize_datetime 要求 date/datetime 列，得 {schema[col]}。")
            return dict(schema)
        evolved = dict(schema)
        evolved[col] = "datetime"
        return evolved
    if op == "convert_unit":
        col = _column(params.get("column"))
        if col is not None and schema[col] not in ("integer", "number", "decimal"):
            _err(errors, "type_incompatible", p_path, f"单位换算要求数值列，得 {schema[col]}。")
            return dict(schema)
        # AF2-WP3 additive（17 号 §3.1）：换算产出精确 Decimal——类型进位 decimal
        evolved = dict(schema)
        if col is not None:
            evolved[col] = "decimal"
        return evolved
    if op == "map_enum":
        col = _column(params.get("column"))
        if col is not None and schema[col] not in ("string", "enum"):
            _err(errors, "type_incompatible", p_path, f"枚举映射要求 string/enum 列，得 {schema[col]}。")
        return dict(schema)
    if op == "dedup":
        raw = params.get("keys")
        if isinstance(raw, list):
            for key in raw:
                _column(key, "keys")
        return dict(schema)
    if op == "join":
        left_key = _column(params.get("left_key"), "left_key")
        right_table = params.get("right_table")
        right_key = params.get("right_key")
        # 03 §77：fk_catalog 声明须有 relations 段证据键对背书，不得凭空宣称
        if (
            left_key is not None
            and params.get("basis") == "fk_catalog"
            and not _fk_evidence_exists(relations, right_table, right_key)
        ):
            _err(
                errors,
                "join_evidence_missing",
                p_path,
                "basis=fk_catalog 但关系段查无此键对（不得凭空宣称硬证据）。",
            )
        # Join 演进（AF2-WP3 additive）：right_columns 声明列并入产出集（类型保守
        # string——计划面无右表列类型元数据；不声明则左 schema 不变）
        evolved = dict(schema)
        for col in params.get("right_columns") or []:
            if isinstance(col, str):
                evolved[col] = "string"
        return evolved
    if op == "assert_quality":
        _column(params.get("column"))
        return dict(schema)
    return dict(schema)


def validate_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """结构静态校验（纯函数）：返回校验报告（valid/errors/DAG/输出声明）。

    报告形状::

        {"valid": bool,
         "errors": [{"code", "path", "message"}],
         "dependency_graph": {"nodes", "edges", "topological_order"},
         "output_columns": [{name, type}]}
    """
    errors: list[dict[str, str]] = []
    if not isinstance(plan, dict):
        return {
            "valid": False,
            "errors": [{"code": "invalid_parameter_value", "path": "plan", "message": "计划须为对象。"}],
            "dependency_graph": {"nodes": [], "edges": [], "topological_order": []},
            "output_columns": [],
        }

    # ---- 版本 ----
    if plan.get("plan_version") != PLAN_VERSION:
        _err(errors, "unsupported_plan_version", "plan_version", f"仅支持 {PLAN_VERSION}。")

    # ---- 来源声明 ----
    source = plan.get("source")
    if not isinstance(source, dict) or set(source) != _SOURCE_KEYS:
        _err(errors, "unexpected_parameter", "source", "source 键集须精确为 {profile_id, table}。")
    elif not all(_is_str(source[key]) for key in _SOURCE_KEYS):
        _err(errors, "invalid_parameter_value", "source", "profile_id/table 须为非空字符串。")

    # ---- 输入声明 ----
    input_block = plan.get("input")
    schema = _check_columns_decl(
        errors, input_block.get("columns") if isinstance(input_block, dict) else None, "input.columns"
    )

    # ---- 04 §3.2 策略显式定义 ----
    _check_policies(errors, plan.get("policies"))

    # ---- 关系候选段（证据登记，无生产态） ----
    relations = _check_relations(errors, plan.get("relations"))

    # ---- 步骤结构（id 唯一 / op 白名单 / 键闭集 / depends_on 引用） ----
    steps = plan.get("steps")
    if not isinstance(steps, list) or not steps:
        _err(errors, "invalid_parameter_value", "steps", "steps 须为非空数组。")
        steps = []
    ids: list[str] = []
    deps_map: dict[str, list[str]] = {}
    declared_ids = {
        str(s["id"]) for s in steps if isinstance(s, dict) and _is_str(s.get("id"))
    }
    unknown_refs = False
    for i, step in enumerate(steps):
        path = f"steps[{i}]"
        if not isinstance(step, dict):
            _err(errors, "invalid_parameter_value", path, "步骤须为对象。")
            continue
        for key in step:
            if key not in _STEP_KEYS:
                _err(errors, "unexpected_parameter", f"{path}.{key}", f"步骤不接受字段 {key}。")
        step_id = step.get("id")
        if not _is_str(step_id):
            _err(errors, "missing_parameter", f"{path}.id", "步骤缺 id。")
            continue
        if step_id in ids:
            _err(errors, "duplicate_step_id", f"{path}.id", f"步骤 id {step_id} 重复。")
        ids.append(str(step_id))
        deps = step.get("depends_on") or []
        if not isinstance(deps, list) or not all(isinstance(dep, str) for dep in deps):
            _err(errors, "invalid_parameter_value", f"{path}.depends_on", "depends_on 须为字符串数组。")
            deps = []
        if any(dep not in declared_ids for dep in deps):
            unknown_refs = True
        deps_map[str(step_id)] = [str(dep) for dep in deps]
        _check_step_params(errors, step, path)

    # ---- op 白名单（unknown_operator 在步骤循环外的显式闸，防 op 缺失静默） ----
    for i, step in enumerate(steps):
        if isinstance(step, dict) and step.get("op") not in OPERATOR_WHITELIST:
            _err(
                errors,
                "unknown_operator",
                f"steps[{i}].op",
                f"算子 {step.get('op')!r} 不在九算子白名单内。",
            )

    # ---- DAG：边集 + 稳定拓扑序 + 无环 ----
    unique_ids = list(dict.fromkeys(ids))
    edges = [(dep, sid) for sid in unique_ids for dep in deps_map.get(sid, []) if dep in unique_ids]
    indeg = {sid: 0 for sid in unique_ids}
    adjacency: dict[str, list[str]] = {sid: [] for sid in unique_ids}
    for dep, sid in edges:
        indeg[sid] += 1
        adjacency[dep].append(sid)
    order: list[str] = []
    ready = [sid for sid in unique_ids if indeg[sid] == 0]
    while ready:
        sid = ready.pop(0)
        order.append(sid)
        for nxt in adjacency[sid]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                ready.append(nxt)
    acyclic = len(order) == len(unique_ids) and bool(unique_ids)
    if unique_ids and not acyclic:
        _err(errors, "dependency_cycle", "steps", "依赖图存在环。")
    if unknown_refs:
        for dep_sid, deps in deps_map.items():
            for dep in deps:
                if dep not in unique_ids:
                    _err(
                        errors,
                        "unknown_step_reference",
                        "steps",
                        f"步骤 {dep_sid} 依赖了不存在的步骤 {dep}。",
                    )

    # ---- 单 sink 类型演进（拓扑序）----
    final_schema = dict(schema)
    if acyclic:
        # 重复 id 已单独报错：step_by_id 取首个声明（演进只走一遍，不双计）
        step_by_id: dict[str, dict[str, Any]] = {}
        for s in steps:
            if isinstance(s, dict) and _is_str(s.get("id")):
                step_by_id.setdefault(str(s["id"]), s)
        for sid in order:
            step = step_by_id.get(sid)
            if step is not None:
                final_schema = _check_step_schema(
                    errors, step, f"steps[{ids.index(sid)}]", final_schema, relations
                )

    # ---- 输出声明须与产出集精确一致 ----
    output_block = plan.get("output")
    out_columns: list[dict[str, Any]] = []
    if isinstance(output_block, dict) and set(output_block) == {"columns"}:
        out_columns = output_block["columns"] if isinstance(output_block["columns"], list) else []
    produced = _check_columns_decl(errors, out_columns, "output.columns")
    for name, declared_type in produced.items():
        if name not in final_schema:
            _err(errors, "output_mismatch", "output.columns", f"输出列 {name} 不在任何步骤产出集内。")
        elif final_schema[name] != declared_type:
            _err(
                errors,
                "output_mismatch",
                "output.columns",
                f"输出列 {name} 类型 {declared_type} 与产出类型 {final_schema[name]} 不符。",
            )

    return {
        "valid": not errors,
        "errors": errors,
        "dependency_graph": {
            "nodes": unique_ids,
            "edges": [[dep, sid] for dep, sid in edges],
            "topological_order": order,
        },
        "output_columns": out_columns,
    }
