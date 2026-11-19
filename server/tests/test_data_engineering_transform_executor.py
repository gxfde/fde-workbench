"""AF2-WP3：编译与隔离执行器（17 号 v1.0 已批规格实现；甲案=worker 固定算子）。

纯函数 ``execute_plan``（transform_executor）＝语义表单一真身（17 号 §3）的
运行时实现：九算子固定语义 + 拒绝账本 reason 码闭集 + 行数守恒机检钉 +
两级血缘 + 资源上限诚实终态。路由面＝执行入口三面（POST runs 幂等提交 /
GET 清单 / GET 详情）+ files 版本锚输入通道。

核心纪律钉：
- **账本零行值原文**（17 号 §3.3 / 04 §3.2）：条目键集精确
  ``{row_index, reason, column}``；
- **行数守恒机检钉**（T3 ``data_eng.row_conservation`` 对齐；17 号 §3.4
  编码期细化＝弱守恒「无行丢失」：join many_to_one 合法展开可产出多于
  输入——机检=每条输入行要么产出要么拒绝，破坏＝internal_inconsistency）；
- **同源校验**（17 号 §2.2）：计划来源画像与执行输入快照锚一致——指纹
  不一致或通道不符＝``snapshot_mismatch`` 拒绝（快照漂移防线）；
- **诚实终态**（17 号 §2.4）：上限触顶＝``budget_exhausted`` 非静默截断；
- **fail-fast 契约违反**（17 号 §3.2）：dedup error=``duplicate_key``、
  one_to_one 基数违反=``cardinality_violation``、右表缺=
  ``snapshot_table_missing``、右列名冲突=``duplicate_column``、右列不在
  右表=``unknown_right_column``——均 run 终态 ``failed`` 零产出，非账本
  条目；join 产出=左行+``right_columns`` 显式声明右列（最小暴露）；
- **计划=不可信候选**（17 号 §4.1）：执行入口强制先过 WP2 ``validate_plan``。
"""
from __future__ import annotations

import hashlib
import io
import uuid
from datetime import date

import pytest

from conftest import INITIAL_PASSWORD as PASSWORD
from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from fde_api.data_engineering.models import DataProfile, TransformPlan, TransformRun
from fde_api.data_engineering.transform_executor import execute_plan
from fde_api.data_engineering.transform_plan import PLAN_VERSION, validate_plan
from fde_api.files.models import ProjectFile, ProjectFileVersion
from fde_api.workbench.models import Project

# ---- 计划骨架（与 WP2 测试同构；执行器复用同一校验器） ------------------------

INPUT_COLUMNS = [
    {"name": "eq_id", "type": "string"},
    {"name": "defect_pct", "type": "number"},
    {"name": "measured_at", "type": "datetime"},
    {"name": "length_mm", "type": "number"},
    {"name": "operator_id", "type": "string"},
]

POLICIES = {
    "null_handling": "reject",
    "reject_record": "collect",
    "duplicate_key": "keep_first",
}


def _plan(**overrides):
    plan = {
        "plan_version": PLAN_VERSION,
        "source": {"profile_id": str(uuid.uuid4()), "table": "equipment"},
        "input": {"columns": [dict(c) for c in INPUT_COLUMNS]},
        "policies": dict(POLICIES),
        "relations": [],
        "steps": [
            {"id": "s1", "op": "select", "params": {"columns": ["eq_id", "defect_pct"]}},
        ],
        "output": {"columns": [{"name": "eq_id", "type": "string"}, {"name": "defect_pct", "type": "number"}]},
    }
    plan.update(overrides)
    return plan


def _rows(specs: list[dict[str, str]]) -> dict[str, list[dict[str, str | None]]]:
    return {"equipment": [dict(r) for r in specs]}


BASE_ROW = {
    "eq_id": "EQ-1",
    "defect_pct": "3.14159",
    "measured_at": "2026-01-02T08:00:00",
    "length_mm": "1500",
    "operator_id": "A",
}


def _ledger(report: dict) -> list[dict]:
    return report["reject_ledger"]


def _reasons(report: dict) -> set[str]:
    return {entry["reason"] for entry in report["reject_ledger"]}


# ---- 纯函数面：行级算子语义（17 号 §3.1） -------------------------------------


def test_happy_path_select_cast_succeeds() -> None:
    plan = _plan(
        steps=[
            {"id": "s1", "op": "select", "params": {"columns": ["eq_id", "defect_pct"]}},
            {"id": "s2", "op": "cast", "params": {"column": "defect_pct", "to_type": "decimal", "scale": 2, "rounding": "half_up"}, "depends_on": ["s1"]},
        ],
        output={"columns": [{"name": "eq_id", "type": "string"}, {"name": "defect_pct", "type": "decimal"}]},
    )
    report = execute_plan(plan, _rows([BASE_ROW]))

    assert report["status"] == "succeeded", report
    assert report["output_rows"] == [{"eq_id": "EQ-1", "defect_pct": "3.14"}]
    assert report["output_columns"] == [{"name": "eq_id", "type": "string"}, {"name": "defect_pct", "type": "decimal"}]
    assert report["reject_ledger"] == []
    assert report["conservation"] == {"input_rows": 1, "output_rows": 1, "rejected_rows": 0, "overflow_count": 0, "ok": True}


def test_cast_decimal_rounding_modes() -> None:
    for rounding, expected in (("half_up", "3"), ("half_even", "2"), ("floor", "2"), ("ceiling", "3")):
        plan = _plan(
            steps=[{"id": "s1", "op": "cast", "params": {"column": "defect_pct", "to_type": "decimal", "scale": 0, "rounding": rounding}}],
            output={"columns": [{"name": "eq_id", "type": "string"}, {"name": "defect_pct", "type": "decimal"}, {"name": "measured_at", "type": "datetime"}, {"name": "length_mm", "type": "number"}, {"name": "operator_id", "type": "string"}]},
        )
        report = execute_plan(plan, _rows([{**BASE_ROW, "defect_pct": "2.5"}]))

        assert report["status"] == "succeeded", rounding
        assert report["output_rows"][0]["defect_pct"] == expected, rounding


def test_cast_decimal_rejects_nonfinite_and_out_of_precision_values() -> None:
    plan = _plan(
        steps=[{"id": "s1", "op": "cast", "params": {"column": "defect_pct", "to_type": "decimal", "scale": 2, "rounding": "half_up"}}],
        output={"columns": [{"name": "defect_pct", "type": "decimal"}]},
    )
    report = execute_plan(plan, _rows([{**BASE_ROW, "defect_pct": value} for value in ("NaN", "Infinity", "1e30", "2.5")]))

    assert report["status"] == "succeeded"
    assert [row["defect_pct"] for row in report["output_rows"]] == ["2.50"]
    assert report["reject_ledger"] == [
        {"row_index": index, "reason": "cast_failed", "column": "defect_pct"} for index in range(3)
    ]


def test_cast_decimal_with_null_scale_records_cast_failed() -> None:
    plan = _plan(
        input={"columns": [{"name": "defect_pct", "type": "number"}]},
        steps=[{"id": "s1", "op": "cast", "params": {"column": "defect_pct", "to_type": "decimal", "scale": None, "rounding": "half_up"}}],
        output={"columns": [{"name": "defect_pct", "type": "decimal"}]},
    )
    assert validate_plan(plan)["valid"] is True

    report = execute_plan(plan, _rows([{"defect_pct": "2.5"}]))

    assert report["status"] == "succeeded"
    assert report["output_rows"] == []
    assert report["rejected_row_count"] == 1
    assert report["reject_ledger"] == [{"row_index": 0, "reason": "cast_failed", "column": "defect_pct"}]


def test_cast_integer_parses_and_rejects_non_integer() -> None:
    plan = _plan(
        steps=[{"id": "s1", "op": "cast", "params": {"column": "defect_pct", "to_type": "integer"}}],
        output={"columns": [{"name": "eq_id", "type": "string"}, {"name": "defect_pct", "type": "integer"}, {"name": "measured_at", "type": "datetime"}, {"name": "length_mm", "type": "number"}, {"name": "operator_id", "type": "string"}]},
    )
    good = execute_plan(plan, _rows([{**BASE_ROW, "defect_pct": "42"}]))

    assert good["status"] == "succeeded"
    assert good["output_rows"][0]["defect_pct"] == "42"

    bad = execute_plan(plan, _rows([{**BASE_ROW, "defect_pct": "1.5"}]))

    assert bad["status"] == "succeeded"  # 行级拒绝不推翻执行
    assert "cast_failed" in _reasons(bad)
    assert bad["output_rows"] == []
    assert bad["conservation"]["ok"] is True


def test_cast_integer_and_number_reject_nonfinite_values() -> None:
    for target in ("integer", "number"):
        plan = _plan(
            steps=[{"id": "s1", "op": "cast", "params": {"column": "defect_pct", "to_type": target}}],
            output={"columns": [{"name": "defect_pct", "type": target}]},
        )
        values = ["Infinity", "NaN", "42"]
        if target == "number":
            values.insert(2, "1e500")
        report = execute_plan(plan, _rows([{**BASE_ROW, "defect_pct": value} for value in values]))
        assert report["status"] == "succeeded"
        assert report["rejected_row_count"] == len(values) - 1
        assert [row["defect_pct"] for row in report["output_rows"]] == ["42" if target == "integer" else 42.0]
        assert set(_reasons(report)) == {"cast_failed"}


def test_cast_boolean_from_integer() -> None:
    """cast boolean：来源须 integer（17 号 §3.1 / WP2 兼容矩阵）——"1"/"0" 两值域。"""
    plan = _plan(
        input={"columns": [
            {"name": "eq_id", "type": "string"},
            {"name": "defect_pct", "type": "number"},
            {"name": "measured_at", "type": "datetime"},
            {"name": "length_mm", "type": "number"},
            {"name": "operator_id", "type": "integer"},
        ]},
        steps=[{"id": "s1", "op": "cast", "params": {"column": "operator_id", "to_type": "boolean"}}],
        output={"columns": [{"name": "eq_id", "type": "string"}, {"name": "defect_pct", "type": "number"}, {"name": "measured_at", "type": "datetime"}, {"name": "length_mm", "type": "number"}, {"name": "operator_id", "type": "boolean"}]},
    )
    report = execute_plan(plan, _rows([{**BASE_ROW, "operator_id": "1"}, {**BASE_ROW, "eq_id": "EQ-2", "operator_id": "0"}]))

    assert [row["operator_id"] for row in report["output_rows"]] == ["true", "false"]


def test_normalize_datetime_localizes_and_rejects_invalid() -> None:
    plan = _plan(
        steps=[{"id": "s1", "op": "normalize_datetime", "params": {"column": "measured_at", "to_tz": "Asia/Shanghai"}}],
        output={"columns": [{"name": "eq_id", "type": "string"}, {"name": "defect_pct", "type": "number"}, {"name": "measured_at", "type": "datetime"}, {"name": "length_mm", "type": "number"}, {"name": "operator_id", "type": "string"}]},
    )
    report = execute_plan(
        plan,
        _rows([{**BASE_ROW, "measured_at": "2026-01-02T08:00:00"}, {**BASE_ROW, "eq_id": "EQ-2", "measured_at": "2026-01-02"}]),
    )

    assert report["status"] == "succeeded"
    values = [row["measured_at"] for row in report["output_rows"]]
    assert values[0].startswith("2026-01-02T08:00:00+08:00")
    assert values[1].startswith("2026-01-02T00:00:00+08:00")  # date→当日零点

    bad = execute_plan(plan, _rows([{**BASE_ROW, "measured_at": "not-a-date"}]))

    assert "datetime_failed" in _reasons(bad)


def test_convert_unit_mm_to_m_exact_decimal() -> None:
    plan = _plan(
        steps=[
            {"id": "s1", "op": "select", "params": {"columns": ["eq_id", "length_mm"]}},
            {"id": "s2", "op": "convert_unit", "params": {"column": "length_mm", "from_unit": "mm", "to_unit": "m"}, "depends_on": ["s1"]},
        ],
        output={"columns": [{"name": "eq_id", "type": "string"}, {"name": "length_mm", "type": "decimal"}]},
    )
    report = execute_plan(plan, _rows([BASE_ROW]))

    assert report["output_rows"] == [{"eq_id": "EQ-1", "length_mm": "1.5"}]  # 1500mm→1.5m，Decimal 精确
    assert report["output_columns"][1]["type"] == "decimal"


def test_convert_unit_same_unit_is_identity() -> None:
    plan = _plan(
        input={"columns": [{"name": "length_mm", "type": "number"}]},
        steps=[{"id": "s1", "op": "convert_unit", "params": {"column": "length_mm", "from_unit": "mm", "to_unit": "mm"}}],
        output={"columns": [{"name": "length_mm", "type": "decimal"}]},
    )
    report = execute_plan(plan, _rows([{"length_mm": "1500.12345678901234567890123456780"}, {"length_mm": "bad"}]))

    assert report["status"] == "succeeded"
    assert report["output_rows"] == [{"length_mm": "1500.12345678901234567890123456780"}]
    assert report["output_columns"] == [{"name": "length_mm", "type": "decimal"}]
    assert report["reject_ledger"] == [{"row_index": 1, "reason": "cast_failed", "column": "length_mm"}]


def test_map_enum_hit_unmapped_error_and_keep() -> None:
    steps = [{"id": "s1", "op": "map_enum", "params": {"column": "operator_id", "mapping": {"A": "alpha"}, "unmapped": "error"}}]
    plan = _plan(steps=steps)

    hit = execute_plan(plan, _rows([BASE_ROW]))

    assert hit["output_rows"][0]["operator_id"] == "alpha"

    miss = execute_plan(plan, _rows([{**BASE_ROW, "operator_id": "B"}]))

    assert "enum_unmapped" in _reasons(miss)
    assert miss["output_rows"] == []

    keep_plan = _plan(steps=[{"id": "s1", "op": "map_enum", "params": {"column": "operator_id", "mapping": {"A": "alpha"}, "unmapped": "keep"}}])
    kept = execute_plan(keep_plan, _rows([{**BASE_ROW, "operator_id": "B"}]))

    assert kept["output_rows"][0]["operator_id"] == "B"


def test_null_handling_reject_and_keep_null() -> None:
    cast_step = {"id": "s1", "op": "cast", "params": {"column": "defect_pct", "to_type": "integer"}}
    plan = _plan(steps=[cast_step], output={"columns": [{"name": "eq_id", "type": "string"}, {"name": "defect_pct", "type": "integer"}, {"name": "measured_at", "type": "datetime"}, {"name": "length_mm", "type": "number"}, {"name": "operator_id", "type": "string"}]})

    rejected = execute_plan(plan, _rows([{**BASE_ROW, "defect_pct": ""}]))

    assert "null_policy" in _reasons(rejected)
    assert rejected["output_rows"] == []

    keep_plan = _plan(
        steps=[cast_step],
        policies={**POLICIES, "null_handling": "keep_null"},
        output={"columns": [{"name": "eq_id", "type": "string"}, {"name": "defect_pct", "type": "integer"}, {"name": "measured_at", "type": "datetime"}, {"name": "length_mm", "type": "number"}, {"name": "operator_id", "type": "string"}]},
    )
    kept = execute_plan(keep_plan, _rows([{**BASE_ROW, "defect_pct": ""}]))

    assert kept["output_rows"][0]["defect_pct"] is None
    assert kept["reject_ledger"] == []


# ---- 纯函数面：集合级算子语义（17 号 §3.2） -----------------------------------


def test_dedup_keep_first_with_ledger() -> None:
    plan = _plan(
        steps=[{"id": "s1", "op": "dedup", "params": {"keys": ["eq_id"]}}],
        output={"columns": [{"name": "eq_id", "type": "string"}, {"name": "defect_pct", "type": "number"}, {"name": "measured_at", "type": "datetime"}, {"name": "length_mm", "type": "number"}, {"name": "operator_id", "type": "string"}]},
    )
    rows = _rows([BASE_ROW, {**BASE_ROW, "defect_pct": "9.9"}, {**BASE_ROW, "eq_id": "EQ-2"}])
    report = execute_plan(plan, rows)

    assert report["status"] == "succeeded"
    assert report["output_row_count"] == 2
    ledger = _ledger(report)
    assert [entry["reason"] for entry in ledger] == ["duplicate_key"]
    assert ledger[0]["row_index"] == 1  # 第二次出现被拒（原输入行号）


def test_dedup_error_fails_fast() -> None:
    plan = _plan(
        steps=[{"id": "s1", "op": "dedup", "params": {"keys": ["eq_id"]}}],
        policies={**POLICIES, "duplicate_key": "error"},
        output={"columns": [{"name": "eq_id", "type": "string"}, {"name": "defect_pct", "type": "number"}, {"name": "measured_at", "type": "datetime"}, {"name": "length_mm", "type": "number"}, {"name": "operator_id", "type": "string"}]},
    )
    report = execute_plan(plan, _rows([BASE_ROW, {**BASE_ROW, "defect_pct": "9.9"}]))

    assert report["status"] == "failed"
    assert report["failure_reason"] == "duplicate_key"
    assert report["output_rows"] == []


def _join_plan(cardinality: str):
    return _plan(
        source={"profile_id": str(uuid.uuid4()), "table": "work_order"},
        input={"columns": [{"name": "wo_id", "type": "string"}, {"name": "eq_id", "type": "string"}]},
        relations=[{"left_table": "work_order", "right_table": "equipment", "left_column": "eq_id", "right_column": "eq_id", "basis": "declared_by_plan"}],
        steps=[
            {"id": "s1", "op": "join", "params": {"left_key": "eq_id", "right_table": "equipment", "right_key": "eq_id", "cardinality": cardinality, "basis": "declared_by_plan", "right_columns": ["defect_pct"]}},
        ],
        output={"columns": [{"name": "wo_id", "type": "string"}, {"name": "eq_id", "type": "string"}, {"name": "defect_pct", "type": "string"}]},
    )


JOIN_TABLES = {
    "work_order": [
        {"wo_id": "WO-1", "eq_id": "EQ-1"},
        {"wo_id": "WO-2", "eq_id": "EQ-X"},  # 右表无匹配 → left join null
    ],
    "equipment": [
        {"eq_id": "EQ-1", "defect_pct": "0.1"},
        {"eq_id": "EQ-1", "defect_pct": "0.2"},  # EQ-1 右侧两条
    ],
}


def test_join_many_to_one_expands_and_left_join_null() -> None:
    plan = _join_plan("many_to_one")
    report = execute_plan(plan, JOIN_TABLES, max_output_rows=3)

    assert report["status"] == "succeeded", report
    rows = report["output_rows"]
    assert [row["wo_id"] for row in rows] == ["WO-1", "WO-1", "WO-2"]
    assert rows[1]["defect_pct"] == "0.2"
    assert rows[2]["defect_pct"] is None  # 左 join：右列 null


def test_join_intermediate_output_budget_preserves_completed_step_stats() -> None:
    plan = _join_plan("many_to_one")
    join = plan["steps"][0]
    plan["steps"] = [
        {"id": "quality", "op": "assert_quality", "params": {"kind": "not_null", "column": "eq_id"}},
        {"id": "select", "op": "select", "params": {"columns": ["wo_id", "eq_id"]}, "depends_on": ["quality"]},
        {**join, "depends_on": ["select"]},
        {"id": "dedup", "op": "dedup", "params": {"keys": ["wo_id"]}, "depends_on": [join["id"]]},
    ]
    tables = {
        **JOIN_TABLES,
        "work_order": [*JOIN_TABLES["work_order"], {"wo_id": "WO-3", "eq_id": ""}, {"wo_id": "WO-4", "eq_id": ""}],
    }

    report = execute_plan(plan, tables, max_output_rows=2, max_reject_rows=1)

    assert (report["status"], report["failure_reason"]) == ("budget_exhausted", "max_output_rows")
    assert report["output_rows"] == []
    assert report["output_row_count"] == 0
    assert report["quality_report"] == {"quality": {"kind": "not_null", "column": "eq_id", "violations": 2}}
    assert report["reject_ledger"] == [
        {"row_index": 2, "reason": "quality_not_null", "column": "eq_id"},
        {"row_index": 3, "reason": "quality_not_null", "column": "eq_id"},
        {"row_index": 2, "reason": "null_policy", "column": "eq_id"},
    ]
    assert report["rejected_row_count"] == 2
    assert report["overflow_count"] == 1
    assert [node["step_id"] for node in report["lineage"]] == ["quality", "select"]
    assert report["conservation"] == {"input_rows": 4, "output_rows": 0, "rejected_rows": 2, "overflow_count": 1, "ok": True}


def test_join_declared_key_absent_in_right_table_fails_fast() -> None:
    """右表缺声明的键列＝契约违反（fail-fast）：否则右表全部键为空，
    幸存左行被误判为「无匹配」，静默产出全 null 右列（17 号 §3.2 声明即契约）。"""
    plan = _join_plan("many_to_one")
    tables = {**JOIN_TABLES, "equipment": [{"defect_pct": "0.1"}]}  # 右表无 eq_id 列

    report = execute_plan(plan, tables)

    assert report["status"] == "failed"
    assert report["failure_reason"] == "unknown_right_column"
    assert report["output_rows"] == []


def test_join_null_keys_never_match() -> None:
    """空键（None/空串＝null，17 号 §3.1）不参与连接：null 不等于 null——
    否则空键左行会命中空键右行，产出虚假匹配行。"""
    plan = _join_plan("many_to_one")
    tables = {
        "work_order": [{"wo_id": "WO-1", "eq_id": ""}, {"wo_id": "WO-2"}],
        "equipment": [{"eq_id": "", "defect_pct": "0.9"}],
    }

    report = execute_plan(plan, tables)

    assert report["status"] == "succeeded"
    assert report["output_row_count"] == 2
    assert [row["wo_id"] for row in report["output_rows"]] == ["WO-1", "WO-2"]
    assert all(row["defect_pct"] is None for row in report["output_rows"])


def test_join_one_to_one_violation_fails() -> None:
    report = execute_plan(_join_plan("one_to_one"), JOIN_TABLES)

    assert report["status"] == "failed"
    assert report["failure_reason"] == "cardinality_violation"
    assert report["output_rows"] == []


def test_join_right_table_missing_and_column_conflict() -> None:
    missing = execute_plan(_join_plan("many_to_one"), {"work_order": JOIN_TABLES["work_order"]})

    assert missing["status"] == "failed"
    assert missing["failure_reason"] == "snapshot_table_missing"

    conflict_plan = _plan(
        source={"profile_id": str(uuid.uuid4()), "table": "work_order"},
        input={"columns": [{"name": "wo_id", "type": "string"}, {"name": "eq_id", "type": "string"}]},
        relations=[{"left_table": "work_order", "right_table": "equipment", "left_column": "eq_id", "right_column": "eq_id", "basis": "declared_by_plan"}],
        steps=[
            {"id": "s1", "op": "join", "params": {"left_key": "eq_id", "right_table": "equipment", "right_key": "eq_id", "cardinality": "many_to_one", "basis": "declared_by_plan", "right_columns": ["wo_id"]}},
        ],
        output={"columns": [{"name": "wo_id", "type": "string"}, {"name": "eq_id", "type": "string"}]},
    )
    conflict_tables = {
        "work_order": [{"wo_id": "WO-1", "eq_id": "EQ-1"}],
        "equipment": [{"eq_id": "EQ-1", "wo_id": "CLASH"}],  # 声明的右列名 wo_id 与左表列冲突
    }
    report = execute_plan(conflict_plan, conflict_tables)

    assert report["status"] == "failed"
    assert report["failure_reason"] == "duplicate_column"


def test_assert_quality_collect_continues_and_counts() -> None:
    q_plan = _plan(
        steps=[{"id": "s1", "op": "assert_quality", "params": {"kind": "not_null", "column": "operator_id"}}],
        output={"columns": [{"name": "eq_id", "type": "string"}, {"name": "defect_pct", "type": "number"}, {"name": "measured_at", "type": "datetime"}, {"name": "length_mm", "type": "number"}, {"name": "operator_id", "type": "string"}]},
    )
    rows = _rows([BASE_ROW, {**BASE_ROW, "eq_id": "EQ-2", "operator_id": ""}])
    report = execute_plan(q_plan, rows)

    assert report["status"] == "succeeded"
    assert report["output_row_count"] == 2  # collect：违反行保留输出（「继续」语义）
    assert _reasons(report) == {"quality_not_null"}
    assert report["quality_report"]["s1"] == {"kind": "not_null", "column": "operator_id", "violations": 1}
    # 守恒：质量违反是记录不是拒绝——不计入 rejected_rows
    assert report["conservation"]["rejected_rows"] == 0
    assert report["conservation"]["ok"] is True

    count_plan = _plan(
        steps=[{"id": "s1", "op": "assert_quality", "params": {"kind": "not_null", "column": "operator_id"}}],
        policies={**POLICIES, "reject_record": "count"},
        output={"columns": [{"name": "eq_id", "type": "string"}, {"name": "defect_pct", "type": "number"}, {"name": "measured_at", "type": "datetime"}, {"name": "length_mm", "type": "number"}, {"name": "operator_id", "type": "string"}]},
    )
    counted = execute_plan(count_plan, rows)

    assert counted["reject_ledger"] == []  # count：只计数不落账本条目
    assert counted["quality_report"]["s1"]["violations"] == 1


# ---- 纯函数面：守恒机检钉 / 账本形状 / 上限诚实终态 / 血缘 --------------------


def test_ledger_entries_have_no_row_values() -> None:
    plan = _plan(
        steps=[{"id": "s1", "op": "cast", "params": {"column": "defect_pct", "to_type": "integer"}}],
        output={"columns": [{"name": "eq_id", "type": "string"}, {"name": "defect_pct", "type": "integer"}, {"name": "measured_at", "type": "datetime"}, {"name": "length_mm", "type": "number"}, {"name": "operator_id", "type": "string"}]},
    )
    report = execute_plan(plan, _rows([{**BASE_ROW, "defect_pct": "not-a-number", "eq_id": "SECRET-ID"}]))

    assert report["reject_ledger"], "应有一条拒绝"
    for entry in report["reject_ledger"]:
        assert set(entry) == {"row_index", "reason", "column"}, entry  # 键集精确＝零行值原文
        assert "SECRET-ID" not in str(entry)


def test_input_row_limit_budget_exhausted() -> None:
    report = execute_plan(_plan(), _rows([BASE_ROW] * 3), max_input_rows=2)

    assert report["status"] == "budget_exhausted"
    assert report["output_rows"] == []
    assert report["failure_reason"] == "max_input_rows"


def test_output_row_limit_budget_exhausted() -> None:
    report = execute_plan(_plan(), _rows([BASE_ROW] * 2), max_output_rows=1)

    assert report["status"] == "budget_exhausted"
    assert report["failure_reason"] == "max_output_rows"


def test_reject_overflow_counts_only() -> None:
    plan = _plan(
        steps=[{"id": "s1", "op": "cast", "params": {"column": "defect_pct", "to_type": "integer"}}],
        output={"columns": [{"name": "eq_id", "type": "string"}, {"name": "defect_pct", "type": "integer"}, {"name": "measured_at", "type": "datetime"}, {"name": "length_mm", "type": "number"}, {"name": "operator_id", "type": "string"}]},
    )
    rows = _rows([{**BASE_ROW, "defect_pct": "x"}, {**BASE_ROW, "eq_id": "EQ-2", "defect_pct": "y"}, {**BASE_ROW, "eq_id": "EQ-3", "defect_pct": "2"}])
    report = execute_plan(plan, rows, max_reject_rows=1)

    assert report["status"] == "succeeded"
    assert len(report["reject_ledger"]) == 1  # 细目封顶
    assert report["overflow_count"] == 1  # 溢出只计数
    assert report["conservation"] == {"input_rows": 3, "output_rows": 1, "rejected_rows": 2, "overflow_count": 1, "ok": True}


def test_quality_entry_does_not_count_into_overflow_at_cap() -> None:
    # bug④ 复现（17 号 §3.3）：质量条目登记若借道「拒绝登记+回退」，顶过细目封顶时
    # 质量行索引会残留 overflow——质量行从未被拒，overflow_count 不得计入。
    plan = _plan(
        steps=[
            {"id": "s1", "op": "cast", "params": {"column": "defect_pct", "to_type": "integer"}},
            {"id": "s2", "op": "assert_quality", "params": {"kind": "not_null", "column": "operator_id"}, "depends_on": ["s1"]},
        ],
        output={"columns": [{"name": "eq_id", "type": "string"}, {"name": "defect_pct", "type": "integer"}, {"name": "measured_at", "type": "datetime"}, {"name": "length_mm", "type": "number"}, {"name": "operator_id", "type": "string"}]},
    )
    rows = _rows([
        {**BASE_ROW, "defect_pct": "3.14159"},  # row0：cast 失败 → 拒绝（占细目 1/1 封顶）
        {**BASE_ROW, "eq_id": "EQ-2", "defect_pct": "2", "operator_id": ""},  # row1：cast 通过 + 质量违反（collect 保留）
        {**BASE_ROW, "eq_id": "EQ-3", "defect_pct": "y"},  # row2：cast 失败 → 拒绝（超封顶，入 overflow）
    ])
    report = execute_plan(plan, rows, max_reject_rows=1)

    assert report["status"] == "succeeded"
    assert report["output_row_count"] == 1  # collect：质量违反行保留输出
    assert report["rejected_row_count"] == 2  # row0/row2 真拒绝（无界计数）
    assert report["overflow_count"] == 1  # 仅 row2；质量行不得计入（bug④ 旧实现=2）
    assert len(report["reject_ledger"]) == 1  # 细目封顶：仅 row0；质量条目顶封顶不落账本（quality_report 计数兜底）
    assert report["quality_report"]["s2"] == {"kind": "not_null", "column": "operator_id", "violations": 1}
    assert report["conservation"] == {"input_rows": 3, "output_rows": 1, "rejected_rows": 2, "overflow_count": 1, "ok": True}


def test_lineage_per_step_stats() -> None:
    plan = _plan(
        steps=[
            {"id": "s1", "op": "select", "params": {"columns": ["eq_id", "defect_pct"]}},
            {"id": "s2", "op": "cast", "params": {"column": "defect_pct", "to_type": "decimal", "scale": 2, "rounding": "half_up"}, "depends_on": ["s1"]},
        ],
        output={"columns": [{"name": "eq_id", "type": "string"}, {"name": "defect_pct", "type": "decimal"}]},
    )
    report = execute_plan(plan, _rows([BASE_ROW, {**BASE_ROW, "eq_id": "EQ-2", "defect_pct": "bad"}]))

    lineage = report["lineage"]
    assert [node["step_id"] for node in lineage] == ["s1", "s2"]
    assert lineage[0]["op"] == "select"
    assert lineage[0]["input_rows"] == 2
    assert lineage[0]["rejected_rows"] == 0
    assert lineage[1]["input_rows"] == 2  # s1 后两行全部存活
    assert lineage[1]["rejected_rows"] == 1  # "bad" 在 s2 cast 拒绝
    assert report["conservation"] == {"input_rows": 2, "output_rows": 1, "rejected_rows": 1, "overflow_count": 0, "ok": True}


def test_invalid_plan_rejected_at_execution_gate() -> None:
    """17 号 §4.1：计划=不可信候选——执行入口强制先过 WP2 静态校验。"""
    plan = _plan(steps=[{"id": "s1", "op": "python_eval", "params": {"code": "1"}}])
    assert validate_plan(plan)["valid"] is False

    with pytest.raises(Exception) as excinfo:
        execute_plan(plan, _rows([BASE_ROW]))
    assert "invalid_transform_plan" in str(excinfo.value)


# ---- 路由面：执行入口三面 + files 版本锚输入通道 ------------------------------


def _make_user(db_session, role: str) -> User:
    user = User(
        username=f"{role}.{uuid.uuid4().hex}",
        display_name=role,
        role=role,
        password_hash=hash_password(PASSWORD),
        must_change_password=False,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return user


def _make_project(db_session, leader: User) -> Project:
    project = Project(
        project_code=f"TE-{uuid.uuid4().hex[:8]}",
        name="Transform executor project",
        enterprise_code="Example·行业·城市",
        planned_start_date=date(2026, 9, 1),
        leader_user_id=leader.id,
        status="active",
        template_snapshot={},
    )
    db_session.add(project)
    db_session.commit()
    return project


def _persist_plan(
    db_session, actor: User, project: Project, plan: dict | None = None, *, profile_id: str | None = None
) -> TransformPlan:
    body = plan or _plan()
    if profile_id:
        body = {**body, "source": {**body["source"], "profile_id": profile_id}}
    row = TransformPlan(
        project_id=project.id,
        plan_version=PLAN_VERSION,
        status="validated",
        source_profile_id=str(body["source"]["profile_id"]),
        source_table=str(body["source"]["table"]),
        plan_json=body,
        validation_json=validate_plan(body),
        created_by_user_id=actor.id,
    )
    db_session.add(row)
    db_session.commit()
    return row


def _seed_csv_version(db_session, project: Project, actor: User, csv_text: str, *, status: str = "available"):
    """files 版本锚工厂（沿 test_file_previews 模式：版本行 + 本地 storage 直写）。"""
    from fde_api.files.names import attachment_key, extension_of, safe_filename
    from fde_api.extensions import object_storage

    filename = "equipment.csv"
    file_id, version_id = uuid.uuid4().hex, uuid.uuid4().hex
    project_file = ProjectFile(
        id=file_id,
        project=project,
        category="attachment",
        display_name=filename,
        description="",
        created_by_user_id=actor.id,
    )
    db_session.add(project_file)
    db_session.flush()

    safe = safe_filename(filename)
    storage_key = attachment_key(project.id, file_id, "v1", safe)
    data = csv_text.encode("utf-8")
    version = ProjectFileVersion(
        id=version_id,
        project_file=project_file,
        version_number=1,
        source="upload",
        original_filename=filename,
        safe_filename=safe,
        extension=extension_of(filename),
        mime_type="text/csv",
        bucket="local",
        storage_key=storage_key,
        size_bytes=len(data),
        etag="",
        sha256=hashlib.sha256(data).hexdigest(),
        uploaded_by_user_id=actor.id,
        status=status,
        scan_status="clean",
        preview_status="none",
    )
    db_session.add(version)
    db_session.flush()
    project_file.current_version_id = version.id
    db_session.commit()

    object_storage.current.put_stream(storage_key, io.BytesIO(data), "text/csv", {})
    return version


def _seed_file_profile(
    db_session, project: Project, actor: User, input_sha256: str, *, source_kind: str = "file"
) -> DataProfile:
    """画像锚工厂（17 号 §2.2 同源校验：input_sha256=执行输入快照钉）。"""
    row = DataProfile(
        project_id=project.id,
        source_name="equipment.csv",
        input_sha256=input_sha256,
        source_kind=source_kind,
        tables_json=[],
        relation_candidates_json=[],
        samples_json={},
        created_by_user_id=actor.id,
    )
    db_session.add(row)
    db_session.commit()
    return row


def _headers(user: User, settings, idem: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {issue_access_token(user, settings)}"}
    if idem:
        headers["Idempotency-Key"] = idem
    return headers


def test_submit_run_persists_and_responds(client, db_session, settings) -> None:
    leader = _make_user(db_session, "project_lead")
    project = _make_project(db_session, leader)
    version = _seed_csv_version(db_session, project, leader, "eq_id,defect_pct\nEQ-1,3.14159\nEQ-2,0.5\n")
    profile = _seed_file_profile(db_session, project, leader, version.sha256 or "")
    plan_row = _persist_plan(db_session, leader, project, profile_id=profile.id)

    response = client.post(
        f"/api/v1/projects/{project.id}/transform-plans/{plan_row.id}/runs",
        json={"input": {"kind": "file_version", "file_version_id": version.id}},
        headers=_headers(leader, settings, idem="run-" + uuid.uuid4().hex),
    )
    assert response.status_code == 201, response.get_data(as_text=True)
    payload = response.get_json()["data"]
    assert payload["status"] == "succeeded"
    assert payload["plan_id"] == plan_row.id
    assert payload["output_row_count"] == 2
    assert payload["reject_ledger"] == []
    assert payload["conservation"]["ok"] is True
    assert payload["input_anchor"]["file_version_id"] == version.id
    assert [node["step_id"] for node in payload["lineage"]] == ["s1"]
    assert payload["output_rows"] == []  # Row values are only available through the bounded preview.

    run_row = db_session.get(TransformRun, payload["id"])
    assert run_row is not None
    assert run_row.plan_id == plan_row.id
    assert run_row.status == "succeeded"

    detail = client.get(
        f"/api/v1/projects/{project.id}/transform-runs/{payload['id']}",
        headers=_headers(leader, settings),
    )
    assert detail.status_code == 200
    listing = client.get(
        f"/api/v1/projects/{project.id}/transform-runs",
        headers=_headers(leader, settings),
    )
    assert listing.status_code == 200
    assert payload["id"] in [item["id"] for item in listing.get_json()["data"]]


def test_submit_run_idempotent_replay(client, db_session, settings) -> None:
    leader = _make_user(db_session, "project_lead")
    project = _make_project(db_session, leader)
    version = _seed_csv_version(db_session, project, leader, "eq_id,defect_pct\nEQ-1,3.14159\n")
    profile = _seed_file_profile(db_session, project, leader, version.sha256 or "")
    plan_row = _persist_plan(db_session, leader, project, profile_id=profile.id)

    idem = "run-" + uuid.uuid4().hex
    first = client.post(
        f"/api/v1/projects/{project.id}/transform-plans/{plan_row.id}/runs",
        json={"input": {"kind": "file_version", "file_version_id": version.id}},
        headers=_headers(leader, settings, idem=idem),
    )
    replay = client.post(
        f"/api/v1/projects/{project.id}/transform-plans/{plan_row.id}/runs",
        json={"input": {"kind": "file_version", "file_version_id": version.id}},
        headers=_headers(leader, settings, idem=idem),
    )

    assert first.status_code == 201
    assert replay.status_code == 201
    assert replay.get_json()["data"]["id"] == first.get_json()["data"]["id"]
    assert db_session.query(TransformRun).count() == 1


def test_submit_run_unknown_or_unavailable_version(client, db_session, settings) -> None:
    leader = _make_user(db_session, "project_lead")
    project = _make_project(db_session, leader)
    plan_row = _persist_plan(db_session, leader, project)

    missing = client.post(
        f"/api/v1/projects/{project.id}/transform-plans/{plan_row.id}/runs",
        json={"input": {"kind": "file_version", "file_version_id": uuid.uuid4().hex}},
        headers=_headers(leader, settings, idem="run-" + uuid.uuid4().hex),
    )
    assert missing.status_code == 404

    deprecated = _seed_csv_version(db_session, project, leader, "eq_id,defect_pct\nEQ-1,1\n", status="deprecated")
    unavailable = client.post(
        f"/api/v1/projects/{project.id}/transform-plans/{plan_row.id}/runs",
        json={"input": {"kind": "file_version", "file_version_id": deprecated.id}},
        headers=_headers(leader, settings, idem="run-" + uuid.uuid4().hex),
    )
    assert unavailable.status_code == 400


def test_submit_run_requires_membership(client, db_session, settings) -> None:
    leader = _make_user(db_session, "project_lead")
    project = _make_project(db_session, leader)
    plan_row = _persist_plan(db_session, leader, project)
    outsider = _make_user(db_session, "fde_engineer")

    response = client.post(
        f"/api/v1/projects/{project.id}/transform-plans/{plan_row.id}/runs",
        json={"input": {"kind": "file_version", "file_version_id": uuid.uuid4().hex}},
        headers=_headers(outsider, settings, idem="run-" + uuid.uuid4().hex),
    )
    assert response.status_code == 404  # S-01 不泄露存在性


def test_submit_run_profile_missing_rejected(client, db_session, settings) -> None:
    """17 号 §2.2：计划来源画像缺失＝404（存在性隐藏沿项目域惯例），零执行零落库。"""
    leader = _make_user(db_session, "project_lead")
    project = _make_project(db_session, leader)
    plan_row = _persist_plan(db_session, leader, project)  # source.profile_id=随机（无画像行）
    version = _seed_csv_version(db_session, project, leader, "eq_id,defect_pct\nEQ-1,1\n")

    response = client.post(
        f"/api/v1/projects/{project.id}/transform-plans/{plan_row.id}/runs",
        json={"input": {"kind": "file_version", "file_version_id": version.id}},
        headers=_headers(leader, settings, idem="run-" + uuid.uuid4().hex),
    )
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "transform_profile_not_found"
    assert db_session.query(TransformRun).count() == 0


def test_submit_run_snapshot_mismatch_rejected(client, db_session, settings) -> None:
    """17 号 §2.2：输入文件版本指纹≠画像钉 input_sha256 ⇒ snapshot_mismatch 拒绝（快照漂移防线）。"""
    leader = _make_user(db_session, "project_lead")
    project = _make_project(db_session, leader)
    profile = _seed_file_profile(db_session, project, leader, "b" * 64)  # 画像钉≠实际文件指纹
    plan_row = _persist_plan(db_session, leader, project, profile_id=profile.id)
    version = _seed_csv_version(db_session, project, leader, "eq_id,defect_pct\nEQ-1,3.14159\n")

    response = client.post(
        f"/api/v1/projects/{project.id}/transform-plans/{plan_row.id}/runs",
        json={"input": {"kind": "file_version", "file_version_id": version.id}},
        headers=_headers(leader, settings, idem="run-" + uuid.uuid4().hex),
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "snapshot_mismatch"
    assert db_session.query(TransformRun).count() == 0


def test_submit_run_connector_profile_file_input_mismatch(client, db_session, settings) -> None:
    """17 号 §2.2：connector 画像不接 file_version 输入通道（source_kind 二态不符）。"""
    leader = _make_user(db_session, "project_lead")
    project = _make_project(db_session, leader)
    profile = _seed_file_profile(db_session, project, leader, "c" * 64, source_kind="connector")
    plan_row = _persist_plan(db_session, leader, project, profile_id=profile.id)
    version = _seed_csv_version(db_session, project, leader, "eq_id,defect_pct\nEQ-1,1\n")

    response = client.post(
        f"/api/v1/projects/{project.id}/transform-plans/{plan_row.id}/runs",
        json={"input": {"kind": "file_version", "file_version_id": version.id}},
        headers=_headers(leader, settings, idem="run-" + uuid.uuid4().hex),
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "snapshot_mismatch"
    assert db_session.query(TransformRun).count() == 0
