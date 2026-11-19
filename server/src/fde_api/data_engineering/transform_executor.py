"""AF2-WP3 TransformPlan 执行器（17 号 v1.0 已批规格；甲案=worker 固定算子）。

**语义真身**：本模块是 17 号 §3 算子语义表的运行时实现——九算子固定语义、
拒绝账本 reason 码九码闭集、行数守恒机检钉、两级血缘、资源上限诚实终态。
语义变更须走 17 号修订+决策单，禁止在本模块静默改语义。

设计纪律（17 号 §4 威胁模型）：

- **纯函数零 I/O**：``execute_plan(plan, tables)`` 只做内存变换——行值全程
  不离开调用方授权域（甲案核心：零 outbound、零行值出域）；
- **计划=不可信候选**：入口强制先过 WP2 ``validate_plan``（静态校验器），
  校验失败即拒（§4.1 第一道闸）；
- **编译产物=固定算子调用图**：无任何「参数拼进表达式源串」路径（零模板
  拼接面，§4.3）；
- **fail-fast 契约违反**：dedup error / one_to_one 基数违反 / 右表缺 /
  右列缺 / 右列名冲突 ＝ run 终态 ``failed``（failure_reason 闭集），零产出；
- **诚实终态**（§2.4）：输入/输出上限触顶＝``budget_exhausted`` 非静默截断；
  拒绝账本溢出只计数（``row_limit`` 语义）；
- **行数守恒机检钉**（§3.4，**弱守恒**口径）：``output >= input - rejected``
  （＝无行丢失：每条输入行要么产出、要么被拒）——join ``many_to_one`` 合法
  展开使一条输入行产出多行，严格等式在合法数据上必假（规格原文 bug 编码期
  实证，round2 经 P1 追认）；破坏＝``internal_inconsistency``（执行器缺陷，
  非数据问题）；
- **账本零行值原文**（§3.3）：条目键集精确 ``{row_index, reason, column}``。

空值判定口径（17 号 §3.1 编码期细化）：行值 ``None`` 或空串＝null（与画像
``null_count`` 对齐）。行值统一字符串形态（files 解析底座产出）；``decimal``
/``integer`` 等数值 cast 产出字符串（保精度），``number`` 产出 float。
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN, ROUND_HALF_UP
from math import isfinite
from zoneinfo import ZoneInfo
from datetime import datetime, date
from typing import Any

from fde_api.data_engineering.transform_plan import validate_plan

# 资源上限闭集（17 号 §2.4；初值编码期定参、实测后冻结，沿 MAX_TOOL_ROUNDS 先例）
TRANSFORM_MAX_INPUT_ROWS = 10_000
TRANSFORM_MAX_OUTPUT_ROWS = 10_000
TRANSFORM_MAX_REJECT_ROWS = 10_000

# 拒绝账本 reason 码闭集（17 号 §3.3；T3 data_eng.reject_ledger 对齐）
REJECT_REASONS = (
    "null_policy",
    "cast_failed",
    "datetime_failed",
    "enum_unmapped",
    "duplicate_key",
    "cardinality_violation",
    "quality_not_null",
    "quality_unique",
    "row_limit",
)

# run 终态闭集
RUN_STATUSES = ("succeeded", "failed", "budget_exhausted", "internal_inconsistency")

# failure_reason 闭集（run 终态 failed 域；非账本 reason——契约违反/快照缺口）
FAILURE_REASONS = (
    "duplicate_key",
    "cardinality_violation",
    "snapshot_table_missing",
    "snapshot_column_missing",
    "unknown_right_column",
    "duplicate_column",
    "main_table_missing",
)

_ROUNDING_MAP = {
    "half_up": ROUND_HALF_UP,
    "half_even": ROUND_HALF_EVEN,
    "floor": ROUND_FLOOR,
    "ceiling": ROUND_CEILING,
}

# 受控量纲精确乘数表（17 号 §3.1：全乘数=精确 Decimal 字面量，浮点禁止）。
# 值=每单位含多少基准量：factor(src→dst)=unit_value[src]/unit_value[dst]。
_UNIT_FACTORS: dict[tuple[str, str], Decimal] = {}
_LENGTH = (("mm", "1"), ("cm", "10"), ("m", "1000"), ("km", "1000000"))
_MASS = (("g", "1"), ("kg", "1000"), ("t", "1000000"))
_TIME = (("s", "1"), ("min", "60"), ("h", "3600"))
for _units in (_LENGTH, _MASS, _TIME):
    _names = [u for u, _ in _units]
    _values = {u: Decimal(f) for u, f in _units}
    for src in _names:
        for dst in _names:
            if src != dst:
                _UNIT_FACTORS[(src, dst)] = _values[src] / _values[dst]


class TransformExecutionError(Exception):
    """执行入口拒绝（计划非法等）——写路径 400 族。"""


def _is_null(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value == "")


def _null_columns(row: dict[str, Any], columns: list[str]) -> str | None:
    for column in columns:
        if _is_null(row.get(column)):
            return column
    return None


def _ledger_add(
    ledger: list[dict[str, Any]],
    rejected: list[int],
    overflow: list[int],
    row_index: int,
    reason: str,
    column: str,
    *,
    max_reject_rows: int,
) -> None:
    """拒绝登记：细目封顶内入账本，超限只计数（row_limit 语义）。"""
    rejected.append(row_index)
    if len(rejected) <= max_reject_rows:
        ledger.append({"row_index": row_index, "reason": reason, "column": column})
    else:
        overflow.append(row_index)


def _cast_value(value: str, to_type: str, params: dict[str, Any]) -> str | float:
    """cast 固定转换（17 号 §3.1）：失败抛 ``_RowReject``。"""
    if to_type == "decimal":
        scale = params["scale"]
        if scale is None:  # 计划校验目前接受显式 null
            raise _RowReject("cast_failed")
        try:
            number = Decimal(value)
            if not number.is_finite():
                raise _RowReject("cast_failed")
            quantum = Decimal(1).scaleb(-scale)
            return str(number.quantize(quantum, rounding=_ROUNDING_MAP[params["rounding"]]))
        except (InvalidOperation, ValueError) as error:
            raise _RowReject("cast_failed") from error
    if to_type == "integer":
        try:
            number = Decimal(value)
        except (InvalidOperation, ValueError) as error:
            raise _RowReject("cast_failed") from error
        if not number.is_finite() or number != number.to_integral_value():
            raise _RowReject("cast_failed")  # 小数字面量不静默截断
        return str(number.to_integral_value())
    if to_type == "number":
        try:
            number_float = float(Decimal(value))
        except (InvalidOperation, ValueError, OverflowError) as error:
            raise _RowReject("cast_failed") from error
        if not isfinite(number_float):
            raise _RowReject("cast_failed")
        return number_float
    if to_type == "boolean":
        if value == "1":
            return "true"
        if value == "0":
            return "false"
        raise _RowReject("cast_failed")
    if to_type == "string":
        return value
    if to_type == "enum":
        return value  # 值域约束由 map_enum 承载；cast enum=原样
    # date/datetime：计划面已禁 string→时间域（无格式声明槽），仅同域规整
    raise _RowReject("cast_failed")


class _RowReject(Exception):
    """行级拒绝信号（reason 码闭集内）。"""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _normalize_datetime(value: str, to_tz: str) -> str:
    try:
        tz = ZoneInfo(to_tz)
        if "T" in value or ":" in value:
            parsed = datetime.fromisoformat(value)
        else:
            parsed = datetime.combine(date.fromisoformat(value), datetime.min.time())
    except (ValueError, TypeError) as error:
        raise _RowReject("datetime_failed") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    else:
        parsed = parsed.astimezone(tz)
    return parsed.isoformat()


def _step_columns(step: dict[str, Any]) -> list[str]:
    """步骤引用列（null_handling reject 的检查面；17 号 §3.1「被步骤引用的列」）。"""
    op = step["op"]
    params = step.get("params") or {}
    if op == "select":
        return [str(c) for c in params.get("columns") or []]
    if op == "rename":
        return [str(k) for k in (params.get("mapping") or {}).keys()]
    if op in ("cast", "normalize_datetime", "convert_unit", "map_enum", "assert_quality"):
        return [str(params["column"])] if params.get("column") else []
    if op == "dedup":
        return [str(k) for k in params.get("keys") or []]
    if op == "join":
        return [str(params["left_key"])] if params.get("left_key") else []
    return []


def _apply_row_step(
    step: dict[str, Any],
    schema: dict[str, str],
    row: dict[str, Any],
    tables: dict[str, list[dict[str, Any]]],
) -> tuple[dict[str, Any], dict[str, str]]:
    """行级算子固定实现：返回 (新行, 新 schema)。失败抛 ``_RowReject``。"""
    op = step["op"]
    params = step.get("params") or {}
    new_row = dict(row)
    new_schema = dict(schema)

    if op == "select":
        columns = params["columns"]
        new_row = {c: row.get(c) for c in columns}
        new_schema = {c: schema[c] for c in columns if c in schema}
    elif op == "rename":
        mapping = params["mapping"]
        new_row = {mapping.get(k, k): v for k, v in row.items()}
        new_schema = {mapping.get(k, k): t for k, t in schema.items()}
    elif op == "cast":
        column = params["column"]
        value = row.get(column)
        new_row[column] = None if _is_null(value) else _cast_value(str(value), params["to_type"], params)
        new_schema[column] = params["to_type"]
    elif op == "normalize_datetime":
        column = params["column"]
        value = row.get(column)
        new_row[column] = None if _is_null(value) else _normalize_datetime(str(value), params["to_tz"])
        new_schema[column] = "datetime"
    elif op == "convert_unit":
        column = params["column"]
        value = row.get(column)
        if _is_null(value):
            new_row[column] = None
        else:
            text = str(value)
            from_unit, to_unit = params["from_unit"], params["to_unit"]
            try:
                number = Decimal(text)
                if from_unit == to_unit:
                    new_row[column] = text  # 恒等换算保留原精度，不做乘法或展开指数
                else:
                    converted = number * _UNIT_FACTORS[(from_unit, to_unit)]
                    new_row[column] = format(converted.normalize(), "f")
            except (InvalidOperation, ValueError, KeyError) as error:
                raise _RowReject("cast_failed") from error
        new_schema[column] = "decimal"
    elif op == "map_enum":
        column = params["column"]
        value = row.get(column)
        if _is_null(value):
            new_row[column] = None
        else:
            mapping = params["mapping"]
            mode = params["unmapped"]
            if str(value) in mapping:
                new_row[column] = mapping[str(value)]
            elif mode == "error":
                raise _RowReject("enum_unmapped")
        new_schema[column] = schema.get(column, "string")
    return new_row, new_schema


def _apply_join(
    step: dict[str, Any],
    rows: list[tuple[int, dict[str, Any]]],
    schema: dict[str, str],
    tables: dict[str, list[dict[str, Any]]],
    *,
    max_output_rows: int,
) -> tuple[list[tuple[int, dict[str, Any]]], dict[str, str]] | None:
    """产出左行与 right_columns 声明列。超预算时返回 None，不交付部分行集。"""
    params = step["params"]
    right_table = params["right_table"]
    right_key = params["right_key"]
    left_key = params["left_key"]
    cardinality = params["cardinality"]
    right_columns = list(params.get("right_columns") or [])

    if right_table not in tables:
        raise _ContractViolation("snapshot_table_missing")
    right_rows = tables[right_table]
    for column in right_columns:
        if right_rows and column not in right_rows[0]:
            raise _ContractViolation("unknown_right_column")
        if column in schema:
            raise _ContractViolation("duplicate_column")  # 声明即契约：冲突不静默改名
    if right_rows and right_key not in right_rows[0]:
        # 右表缺声明的键列＝契约违反（fail-fast）：否则右表全部键为空，
        # 幸存左行被静默判为「无匹配」，产出全 null 右列（17 号 §3.2 声明即契约）。
        raise _ContractViolation("unknown_right_column")

    index: dict[Any, list[dict[str, Any]]] = {}
    for right_row in right_rows:
        key = right_row.get(right_key)
        if _is_null(key):
            continue  # 空键不参与连接：null 不等于 null（17 号 §3.1 空值口径）
        index.setdefault(key, []).append(right_row)

    out: list[tuple[int, dict[str, Any]]] = []
    for row_index, row in rows:
        left_value = row.get(left_key)
        matches = [] if _is_null(left_value) else index.get(left_value, [])
        if len(matches) > 1 and cardinality == "one_to_one":
            raise _ContractViolation("cardinality_violation")
        if len(out) + max(1, len(matches)) > max_output_rows:
            return None
        if not matches:
            out.append((row_index, {**row, **{c: None for c in right_columns}}))
            continue
        for right_row in matches:
            out.append((row_index, {**row, **{c: right_row.get(c) for c in right_columns}}))

    new_schema = dict(schema)
    for column in right_columns:
        new_schema[column] = "string"  # 行集无类型元数据：右列保守 string（17 号编码期细化）
    return out, new_schema


class _ContractViolation(Exception):
    """集合级契约违反（fail-fast；run 终态 failed）。"""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def execute_plan(
    plan: dict[str, Any],
    tables: dict[str, list[dict[str, Any]]],
    *,
    max_input_rows: int = TRANSFORM_MAX_INPUT_ROWS,
    max_output_rows: int = TRANSFORM_MAX_OUTPUT_ROWS,
    max_reject_rows: int = TRANSFORM_MAX_REJECT_ROWS,
) -> dict[str, Any]:
    """执行已校验计划（纯函数；17 号 §2/§3 全语义）。

    ``tables`` = 同源表行集 map（主表=``plan.source.table``；join 右表限同
    map——v1 限同 source 内表，17 号 §6.1）。返回 run 结果（终态/产出/账本/
    守恒/质量报告/血缘），零落库零 I/O。
    """
    report = validate_plan(plan)
    if not report["valid"]:
        raise TransformExecutionError(f"invalid_transform_plan: {report['errors'][:3]}")

    ledger: list[dict[str, Any]] = []
    rejected: list[int] = []
    overflow: list[int] = []
    quality_report: dict[str, dict[str, Any]] = {}
    lineage: list[dict[str, Any]] = []

    main_table = str(plan.get("source", {}).get("table") or "")
    if main_table not in tables:
        return _failed_result("main_table_missing", ledger, rejected, overflow, quality_report, lineage, 0)

    input_rows: list[dict[str, Any]] = list(tables[main_table])
    input_count = len(input_rows)
    if input_count > max_input_rows:
        return {
            "status": "budget_exhausted",
            "failure_reason": "max_input_rows",
            "output_rows": [],
            "output_row_count": 0,
            "output_columns": [],
            "reject_ledger": ledger,
            "rejected_row_count": 0,
            "overflow_count": 0,
            "quality_report": quality_report,
            "lineage": lineage,
            "conservation": {"input_rows": input_count, "output_rows": 0, "rejected_rows": 0, "overflow_count": 0, "ok": True},
        }

    schema: dict[str, str] = {
        str(col["name"]): str(col["type"]) for col in plan.get("input", {}).get("columns") or []
    }
    current: list[tuple[int, dict[str, Any]]] = [(i, dict(row)) for i, row in enumerate(input_rows)]

    def _reject(row_index: int, reason: str, column: str) -> None:
        _ledger_add(
            ledger, rejected, overflow, row_index, reason, column, max_reject_rows=max_reject_rows
        )

    def _quality_entry(row_index: int, reason: str, column: str) -> None:
        """质量违反记录（非拒绝）：行保留输出，条目入账本供断言器复算。

        不变量（bug④ 修复，17 号 §3.3/§2.4）：质量行**未被拒绝** → 不登记进
        ``rejected``/``overflow``（overflow 语义＝仅「被拒行」超细目封顶的计数；
        质量行保留在输出，从未真拒/溢出，不得计入）。细目条目共享拒行细目封顶
        预算（口径同 rejected，按 ``len(rejected)`` 判）；封顶则降级为计数（
        ``quality_report.violations`` 兜底），绝不进 overflow。
        """
        if len(rejected) <= max_reject_rows:
            ledger.append({"row_index": row_index, "reason": reason, "column": column})

    output_budget_exhausted = False
    steps_by_id = {step["id"]: step for step in plan["steps"]}
    for step_id in report["dependency_graph"]["topological_order"]:
        step = steps_by_id[step_id]
        op = str(step.get("op"))
        step_in = len(current)
        rejected_before = len(rejected)

        if plan.get("policies", {}).get("null_handling") == "reject" and op in (
            "select",
            "rename",
            "cast",
            "normalize_datetime",
            "convert_unit",
            "map_enum",
            "dedup",
        ):
            # null_handling 预检面＝变换/去重引用列；join/assert_quality 不预检
            # （join null→left join 语义；assert_quality 的 null 是断言对象本身）
            next_current: list[tuple[int, dict[str, Any]]] = []
            for row_index, row in current:
                null_col = _null_columns(row, _step_columns(step))
                if null_col is None:
                    next_current.append((row_index, row))
                else:
                    _reject(row_index, "null_policy", null_col)
            current = next_current

        try:
            if op == "dedup":
                keys = [str(k) for k in step["params"]["keys"]]
                seen_keys: set[tuple[Any, ...]] = set()
                kept: list[tuple[int, dict[str, Any]]] = []
                for row_index, row in current:
                    key = tuple(row.get(k) for k in keys)
                    if key not in seen_keys:
                        seen_keys.add(key)
                        kept.append((row_index, row))
                    elif _dedup_mode(plan) == "error":
                        return _failed_result(
                            "duplicate_key", ledger, rejected, overflow, quality_report, lineage, input_count
                        )
                    else:
                        _reject(row_index, "duplicate_key", "、".join(keys))
                current = kept
            elif op == "join":
                joined = _apply_join(step, current, schema, tables, max_output_rows=max_output_rows)
                if joined is None:
                    output_budget_exhausted = True
                    break
                current, schema = joined
            elif op == "assert_quality":
                params = step["params"]
                kind, column = str(params["kind"]), str(params["column"])
                mode = str(plan.get("policies", {}).get("reject_record") or "collect")
                violations = 0
                if kind == "not_null":
                    bad_rows = [row_index for row_index, row in current if _is_null(row.get(column))]
                else:  # unique
                    seen_values: set[Any] = set()
                    bad_rows = []
                    for row_index, row in current:
                        value_key = row.get(column)
                        if value_key in seen_values:
                            bad_rows.append(row_index)
                        else:
                            seen_values.add(value_key)
                violations = len(bad_rows)
                if mode == "collect":
                    reason = "quality_not_null" if kind == "not_null" else "quality_unique"
                    for row_index in bad_rows:
                        _quality_entry(row_index, reason, column)
                quality_report[str(step.get("id"))] = {"kind": kind, "column": column, "violations": violations}
            else:
                # 行级算子
                next_current = []
                for row_index, row in current:
                    try:
                        new_row, new_schema = _apply_row_step(step, schema, row, tables)
                        schema = new_schema
                        next_current.append((row_index, new_row))
                    except _RowReject as reject:
                        _reject(row_index, reject.reason, str(step.get("params", {}).get("column") or ""))
                current = next_current
        except _ContractViolation as violation:
            return _failed_result(
                violation.reason, ledger, rejected, overflow, quality_report, lineage, input_count
            )

        lineage.append(
            {
                "step_id": str(step.get("id")),
                "op": op,
                "input_rows": step_in,
                "output_rows": len(current),
                "rejected_rows": len(rejected) - rejected_before,
            }
        )

    if output_budget_exhausted or len(current) > max_output_rows:
        return {
            "status": "budget_exhausted",
            "failure_reason": "max_output_rows",
            "output_rows": [],
            "output_row_count": 0,
            "output_columns": [dict(name=name, type=ctype) for name, ctype in schema.items()],
            "reject_ledger": ledger,
            "rejected_row_count": len(rejected),
            "overflow_count": len(overflow),
            "quality_report": quality_report,
            "lineage": lineage,
            "conservation": {
                "input_rows": input_count,
                "output_rows": 0,
                "rejected_rows": len(rejected),
                "overflow_count": len(overflow),
                "ok": True,
            },
        }

    output_rows = [row for _, row in current]
    output_count = len(output_rows)
    rejected_count = len(rejected)
    overflow_count = len(overflow)
    # 弱守恒（17 号 §3.4 编码期细化）：join many_to_one 合法展开使产出可多于
    # 输入——机检钉=「无行丢失」：每条输入行要么产出、要么拒绝（细目+溢出）。
    ok = output_count >= input_count - rejected_count

    return {
        "status": "succeeded" if ok else "internal_inconsistency",
        "failure_reason": None if ok else "conservation_violated",
        "output_rows": output_rows,
        "output_row_count": output_count,
        "output_columns": [dict(name=name, type=ctype) for name, ctype in schema.items()],
        "reject_ledger": ledger,
        "rejected_row_count": rejected_count,
        "overflow_count": overflow_count,
        "quality_report": quality_report,
        "lineage": lineage,
        "conservation": {
            "input_rows": input_count,
            "output_rows": output_count,
            "rejected_rows": rejected_count,
            "overflow_count": overflow_count,
            "ok": ok,
        },
    }


def _dedup_mode(plan: dict[str, Any]) -> str:
    return str(plan.get("policies", {}).get("duplicate_key") or "keep_first")


def _failed_result(
    reason: str,
    ledger: list[dict[str, Any]],
    rejected: list[int],
    overflow: list[int],
    quality_report: dict[str, dict[str, Any]],
    lineage: list[dict[str, Any]],
    input_count: int,
) -> dict[str, Any]:
    return {
        "status": "failed",
        "failure_reason": reason,
        "output_rows": [],
        "output_row_count": 0,
        "output_columns": [],
        "reject_ledger": ledger,
        "rejected_row_count": len(rejected),
        "overflow_count": len(overflow),
        "quality_report": quality_report,
        "lineage": lineage,
        "conservation": {
            "input_rows": input_count,
            "output_rows": 0,
            "rejected_rows": len(rejected),
            "overflow_count": len(overflow),
            "ok": True,
        },
    }
