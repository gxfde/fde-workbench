"""资料只读画像器（AF2-WP1：03 §77 / 15 号 §3 WP1 行）。

纯函数：文件字节 → 画像报告。四纪律（测试钉 ``test_data_engineering_profile``）：

- **只读**：解析全在内存；不触碰 files 域状态、不写任何源数据（AF2 源
  数据零覆盖红线的前置面）；
- **产物 = 统计 + 掩码样本 + 指纹**：原始敏感行不出现在产物里（04 §3.2
  「工程日志只存引用、统计和错误类别」的资料侧落法）；``input_sha256``
  逐字节指纹使快照可复验；
- **关系候选只登记**：status 恒 ``candidate``，键空间封闭（无生产态）——
  未知关联不能自动变成生产 Join（03 §77 验收行）；
- **行数守恒**：解析失败行进 ``error_rows`` 如实计数，不静默丢行美化
  统计（05 §3 分母完整性同源纪律）；超行数上限截断时 ``truncated``
  如实标注。

类型推断词表与本体词表（ontology-service validation.py / 工具描述）对齐：
``string | number | boolean | date | datetime``（enum/ref 由 WP2 受限 Join
与候选生成阶段再判，画像不做弱推断）。
"""
from __future__ import annotations

import csv
import io
import re
from hashlib import sha256
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

MAX_PROFILE_BYTES = 5 * 1024 * 1024  # 5 MB——画像对象是资料样本不是全量库
MAX_ROWS = 10_000
SAMPLE_ROW_LIMIT = 5
SUPPORTED_SUFFIXES = {".csv", ".xlsx"}

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?$")
_INT = re.compile(r"^[+-]?\d+$")
_FLOAT = re.compile(r"^[+-]?(\d+\.\d+|\.\d+|\d+\.)([eE][+-]?\d+)?$")
_BOOL = re.compile(r"^(true|false)$", re.IGNORECASE)


class ProfileError(ValueError):
    """画像输入违例（超大/格式不支持/解析不可用）——路由层转 400。"""


def profile_bytes(*, filename: str, data: bytes) -> dict[str, Any]:
    """文件字节 → 画像报告（纯函数；bytes 不落库、不触碰任何域状态）。

    返回形状::

        {
          "source_name": str, "input_sha256": str,
          "row_limit": int, "truncated": bool,
          "tables": [{"name": str, "row_count": int, "error_rows": int,
                      "columns": [{"name": str, "inferred_type": str,
                                   "null_count": int, "unique_count": int}]}],
          "relation_candidates": [{"left_table", "right_table", "left_column",
                                   "right_column", "basis", "status": "candidate",
                                   "overlap_ratio": float}],
          "samples": {表名: [掩码行 dict]},
        }
    """
    if len(data) > MAX_PROFILE_BYTES:
        raise ProfileError("file_too_large", f"画像输入超上限（>{MAX_PROFILE_BYTES} 字节）")
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ProfileError("unsupported_file_type", f"仅支持 {sorted(SUPPORTED_SUFFIXES)}")

    tables = _parse_csv(data, Path(filename).stem) if suffix == ".csv" else _parse_xlsx(data)
    for table in tables:
        _decorate(table)

    report: dict[str, Any] = {
        "source_name": filename,
        "input_sha256": sha256(data).hexdigest(),
        "row_limit": MAX_ROWS,
        "truncated": any(table["truncated"] for table in tables),
        "tables": [
            {
                "name": table["name"],
                "row_count": table["row_count"],
                "error_rows": table["error_rows"],
                "columns": table["columns"],
            }
            for table in tables
        ],
        "relation_candidates": _relation_candidates(tables),
        "samples": {},
    }
    for table in tables:
        report["samples"][table["name"]] = [
            {column: row.get(column) for column in table["column_names"]}
            for row in table["sample_rows"]
        ]
    return report


# ---- 解析（内存只读） ---------------------------------------------------------


def _parse_csv(data: bytes, name: str) -> list[dict[str, Any]]:
    text = data.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration as error:
        raise ProfileError("empty_file", "空文件无可画像内容") from error
    header = [column.strip() or f"col_{index}" for index, column in enumerate(header)]

    rows: list[dict[str, str]] = []
    error_rows = 0
    truncated = False
    for fields in reader:
        if not fields or (len(fields) == 1 and not fields[0].strip()):
            continue  # 空行不算数据行
        if len(rows) >= MAX_ROWS:
            truncated = True
            break
        if len(fields) != len(header):
            error_rows += 1  # 列数错位 = 解析失败行，如实计数（不丢行）
            continue
        rows.append(dict(zip(header, fields)))

    return [_table(name, header, rows, error_rows, truncated)]


def _parse_xlsx(data: bytes) -> list[dict[str, Any]]:
    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as error:  # noqa: BLE001 - openpyxl 异常族收敛为 ProfileError
        raise ProfileError("unreadable_workbook", f"工作簿不可解析：{error}") from error
    tables: list[dict[str, Any]] = []
    try:
        for sheet in workbook.worksheets:
            iterator = sheet.iter_rows(values_only=True)
            header_row = next(iterator, None)
            if header_row is None:
                tables.append(_table(sheet.title, [], [], 0, False))
                continue
            header = [
                str(column).strip() or f"col_{index}" if column is not None else f"col_{index}"
                for index, column in enumerate(header_row)
            ]
            rows: list[dict[str, Any]] = []
            error_rows = 0
            truncated = False
            for values in iterator:
                if all(value is None or str(value).strip() == "" for value in values):
                    continue
                if len(rows) >= MAX_ROWS:
                    truncated = True
                    break
                if len(values) != len(header):
                    error_rows += 1
                    continue
                rows.append({
                    column: "" if value is None else str(value)
                    for column, value in zip(header, values)
                })
            tables.append(_table(sheet.title, header, rows, error_rows, truncated))
    finally:
        workbook.close()
    return tables


def _table(
    name: str,
    header: list[str],
    rows: list[dict[str, Any]],
    error_rows: int,
    truncated: bool,
) -> dict[str, Any]:
    return {
        "name": name,
        "column_names": header,
        "rows": rows,
        "row_count": len(rows),
        "error_rows": error_rows,
        "truncated": truncated,
        "columns": [],
        "sample_rows": [],
    }


# ---- 统计/推断/候选（纯函数） --------------------------------------------------


def _infer_column_type(values: list[str]) -> str:
    """非空值的类型推断（全空列 → string 兜底）。"""
    if not values:
        return "string"
    checks = (
        (_BOOL, "boolean"),
        (_INT, "number"),
        (_FLOAT, "number"),
        (_ISO_DATETIME, "datetime"),
        (_ISO_DATE, "date"),
    )
    for pattern, inferred in checks:
        if all(pattern.match(value.strip()) for value in values):
            return inferred
    return "string"


def _decorate(table: dict[str, Any]) -> None:
    """就地补全 columns 统计与脱敏样本（profile_bytes 的收尾步）。"""
    from fde_api.data_engineering.masking import mask_sample_rows

    columns: list[dict[str, Any]] = []
    non_empty: dict[str, list[str]] = {}
    for name in table["column_names"]:
        values = [str(row.get(name, "")) for row in table["rows"]]
        present = [value for value in values if value.strip() != ""]
        non_empty[name] = present
        columns.append({
            "name": name,
            "inferred_type": _infer_column_type(present),
            "null_count": len(values) - len(present),
            "unique_count": len(set(present)),
        })
    table["columns"] = columns
    table["sample_rows"] = mask_sample_rows(
        {column["name"]: column["inferred_type"] for column in columns},
        table["rows"][:SAMPLE_ROW_LIMIT],
    )


def _relation_candidates(tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """跨表同名列 + 类型兼容 → 关系候选（双向登记，方向留给人工/WP2 裁决）。

    只登记：status 恒 ``candidate``；键空间封闭（测试钉
    ``test_relation_candidates_have_no_production_state``）——画像产物上
    不存在任何生产态或翻转通道。
    """
    candidates: list[dict[str, Any]] = []
    for left in tables:
        for right in tables:
            if left is right:
                continue
            left_types = {column["name"]: column for column in left["columns"]}
            right_types = {column["name"]: column for column in right["columns"]}
            for name, left_column in left_types.items():
                right_column = right_types.get(name)
                if right_column is None or right_column["inferred_type"] != left_column["inferred_type"]:
                    continue
                overlap = _overlap_ratio(left["rows"], right["rows"], name)
                candidates.append({
                    "left_table": left["name"],
                    "right_table": right["name"],
                    "left_column": name,
                    "right_column": name,
                    "basis": "same_name_type_compatible",
                    "status": "candidate",
                    "overlap_ratio": overlap,
                })
    return candidates


def _overlap_ratio(
    left_rows: list[dict[str, Any]], right_rows: list[dict[str, Any]], name: str
) -> float:
    left_values = {str(row.get(name, "")).strip() for row in left_rows} - {""}
    right_values = {str(row.get(name, "")).strip() for row in right_rows} - {""}
    if not left_values:
        return 0.0
    return round(len(left_values & right_values) / len(left_values), 4)
