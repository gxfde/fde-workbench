"""场景版本化（V3.2 G2，G1 §4.4）。

一行 = 一个不可变版本快照；内容变更**不原地改**，而是追加新版本行。
纯函数：版本推导与新行字段派生都不碰数据库（服务层负责落库）。
"""
from __future__ import annotations

from typing import Any, Iterable


def next_version(versions: Iterable[int]) -> int:
    """下一个版本号 = 既有最大版本 + 1（无既有版本则 1）。"""
    highest = 0
    for value in versions:
        if isinstance(value, int) and value > highest:
            highest = value
    return highest + 1


def derive_next_row(
    existing: dict[str, Any],
    updates: dict[str, Any],
    *,
    next_version_number: int,
) -> dict[str, Any]:
    """由既有版本行 + 变更字典派生新版本行。

    不可变字段（``scenario_key`` / ``id`` / ``created_at`` / ``created_by``）
    不随版本复制；``version`` 走新号。可变更字段白名单：

    ``name`` / ``industry`` / ``variant`` / ``difficulty`` / ``split`` /
    ``status`` / ``tags`` / ``content_json`` / ``reference_json`` /
    ``rubric_version`` / ``source_kind`` / ``source_ref`` / ``note``

    白名单外的键被**静默忽略**（不猜、不透传）——避免调用方借 PATCH 写入
    id/key 等身份字段。
    """
    mutable_fields = (
        "name",
        "industry",
        "variant",
        "difficulty",
        "split",
        "status",
        "tags",
        "content_json",
        "reference_json",
        "rubric_version",
        "source_kind",
        "source_ref",
        "note",
    )
    row: dict[str, Any] = {
        "scenario_key": existing["scenario_key"],
        "name": existing["name"],
        "industry": existing["industry"],
        "variant": existing["variant"],
        "difficulty": existing["difficulty"],
        "split": existing["split"],
        "status": existing["status"],
        "tags": list(existing.get("tags") or []),
        "content_json": dict(existing.get("content_json") or {}),
        "reference_json": (
            dict(existing["reference_json"]) if existing.get("reference_json") else None
        ),
        "rubric_version": existing.get("rubric_version") or "rubric-v1",
        "source_kind": existing.get("source_kind") or "manual",
        "source_ref": existing.get("source_ref"),
        "note": existing.get("note"),
        "version": next_version_number,
    }
    for key in mutable_fields:
        if key in updates:
            row[key] = updates[key]
    return row
