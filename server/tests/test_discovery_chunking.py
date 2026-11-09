"""V31-P1b：大纪要分段抽取的切片规划与合并（纯函数层）。

覆盖两件事：
- ``chunking.plan_chunks``：按行切片，不丢行、不重排、行号口径可用；
- ``merge.merge_chunk_drafts``：片内行号回基成全文绝对行号，跨片去重，
  需求引用的片内下标重基到合并后的事实表。

背景见 ``fde_api/discovery/chunking.py`` 模块注释（供应商 completion 硬顶
16,384 tokens，全文成抽必被思考挤爆）。
"""
from __future__ import annotations

import pytest

from fde_api.discovery.chunking import plan_chunks, split_chunk
from fde_api.discovery.merge import merge_chunk_drafts, rebase_locator


def _fact(subject: str, line: int, fact_type: str = "process", predicate: str = "当前步骤"):
    return {
        "fact_type": fact_type,
        "subject": subject,
        "predicate": predicate,
        "object_value": {"值": subject},
        "confidence": 0.9,
        "source_locator": {"type": "line", "line": line},
        "inference": False,
        "needs_clarification": False,
    }


def _requirement(title: str, indexes: list[int]):
    return {
        "title": title,
        "description": None,
        "requirement_type": "functional",
        "priority": "high",
        "acceptance_criteria": ["可验证标准"],
        "source_fact_indexes": indexes,
    }


# --- plan_chunks -------------------------------------------------------------


def test_plan_chunks_respects_line_limit_and_keeps_order() -> None:
    content = "\n".join(f"第{i}行" for i in range(1, 91))

    chunks = plan_chunks(content, max_lines=40, max_chars=10000)

    assert [c.index for c in chunks] == [0, 1, 2]
    assert [c.line_count for c in chunks] == [40, 40, 10]
    assert chunks[0].start_line == 1 and chunks[0].end_line == 40
    assert chunks[1].start_line == 41 and chunks[1].end_line == 80
    assert chunks[2].start_line == 81 and chunks[2].end_line == 90
    # 拼接回原文：不丢行、不重排、不改字
    assert "\n".join(c.text for c in chunks) == content


def test_plan_chunks_respects_char_limit() -> None:
    content = "\n".join("x" * 100 for _ in range(10))

    chunks = plan_chunks(content, max_lines=100, max_chars=250)

    assert len(chunks) > 1
    assert all(len(c.text) <= 250 for c in chunks)
    assert "\n".join(c.text for c in chunks) == content


def test_plan_chunks_single_oversized_line_owns_its_chunk() -> None:
    content = "短行\n" + "y" * 900 + "\n尾行"

    chunks = plan_chunks(content, max_lines=10, max_chars=100)

    assert len(chunks) == 3
    assert chunks[1].text == "y" * 900  # 超长单行不被切开（行号口径不能破）
    assert chunks[1].start_line == 2 and chunks[1].end_line == 2
    assert chunks[2].start_line == 3


def test_plan_chunks_empty_content_returns_no_chunks() -> None:
    assert plan_chunks("") == []


@pytest.mark.parametrize("kwargs", [{"max_lines": 0}, {"max_chars": 0}, {"max_lines": -1}])
def test_plan_chunks_rejects_non_positive_limits(kwargs) -> None:
    with pytest.raises(ValueError):
        plan_chunks("正文", **kwargs)


def test_rebase_line_maps_chunk_local_to_absolute() -> None:
    chunks = plan_chunks("\n".join(f"行{i}" for i in range(1, 61)), max_lines=40, max_chars=10000)

    assert chunks[0].rebase_line(1) == 1
    assert chunks[0].rebase_line(40) == 40
    assert chunks[1].rebase_line(1) == 41
    assert chunks[1].rebase_line(20) == 60


# --- merge_chunk_drafts ------------------------------------------------------


def test_merge_rebases_line_numbers_across_chunks() -> None:
    chunks = plan_chunks("\n".join(f"行{i}" for i in range(1, 61)), max_lines=40, max_chars=10000)

    merged = merge_chunk_drafts([
        (chunks[0], {"facts": [_fact("询盘处理", 1)], "requirements": []}),
        (chunks[1], {"facts": [_fact("排程现状", 3)], "requirements": []}),
    ])

    assert [f["source_locator"]["line"] for f in merged["facts"]] == [1, 43]


def test_merge_dedupes_identical_facts_across_chunks() -> None:
    chunks = plan_chunks("\n".join(f"行{i}" for i in range(1, 61)), max_lines=40, max_chars=10000)

    merged = merge_chunk_drafts([
        (chunks[0], {"facts": [_fact("询盘处理", 1)], "requirements": []}),
        (chunks[1], {"facts": [_fact("询盘处理", 2)], "requirements": []}),
    ])

    assert len(merged["facts"]) == 1
    assert merged["facts"][0]["source_locator"]["line"] == 1  # 保留首次


def test_merge_dedupes_requirements_by_title() -> None:
    chunks = plan_chunks("\n".join(f"行{i}" for i in range(1, 61)), max_lines=40, max_chars=10000)

    merged = merge_chunk_drafts([
        (chunks[0], {"facts": [_fact("询盘处理", 1)], "requirements": [_requirement("补齐下游链路", [0])]}),
        (chunks[1], {"facts": [_fact("排程现状", 1)], "requirements": [_requirement("补齐下游链路", [0])]}),
    ])

    assert len(merged["requirements"]) == 1
    assert merged["requirements"][0]["source_fact_indexes"] == [0]


def test_merge_remaps_requirement_fact_indexes_to_merged_table() -> None:
    chunks = plan_chunks("\n".join(f"行{i}" for i in range(1, 61)), max_lines=40, max_chars=10000)

    merged = merge_chunk_drafts([
        (chunks[0], {"facts": [_fact("询盘处理", 1)], "requirements": []}),
        (chunks[1], {"facts": [_fact("排程现状", 1), _fact("交付节奏", 2), _fact("验收口径", 3)],
                     "requirements": [_requirement("补齐下游链路", [0, 2])]}),
    ])

    # 片内下标 0→合并表 1、2→合并表 3（片 2 有三条事实）
    assert merged["requirements"][0]["source_fact_indexes"] == [1, 3]


def test_merge_drops_references_to_deduplicated_facts() -> None:
    chunks = plan_chunks("\n".join(f"行{i}" for i in range(1, 61)), max_lines=40, max_chars=10000)

    merged = merge_chunk_drafts([
        (chunks[0], {"facts": [_fact("询盘处理", 1)], "requirements": []}),
        (chunks[1], {"facts": [_fact("询盘处理", 2), _fact("排程现状", 3)],
                     "requirements": [_requirement("补齐下游链路", [0])]}),
    ])

    # 片 1 的第 0 条与片 0 重复被丢 → 引用一并丢弃（需求转入无来源态）
    assert merged["requirements"][0]["source_fact_indexes"] == []


def test_rebase_locator_keeps_non_line_locators() -> None:
    chunk = plan_chunks("甲\n乙\n丙", max_lines=1, max_chars=100)[0]

    assert rebase_locator({"type": "char_span", "start": 0, "end": 10}, chunk) == {
        "type": "char_span", "start": 0, "end": 10}
    assert rebase_locator({"type": "line", "line": 1}, chunk) == {"type": "line", "line": 1}


# --- split_chunk（自适应降片长） ---------------------------------------------


def test_split_chunk_halves_by_line_and_keeps_line_ranges() -> None:
    chunk = plan_chunks("\n".join(f"行{i}" for i in range(1, 11)), max_lines=10, max_chars=1000)[0]

    halves = split_chunk(chunk)

    assert halves is not None
    left, right = halves
    assert left.text == "\n".join(f"行{i}" for i in range(1, 6))
    assert right.text == "\n".join(f"行{i}" for i in range(6, 11))
    assert left.start_line == 1 and left.end_line == 5
    assert right.start_line == 6 and right.end_line == 10


def test_split_chunk_returns_none_for_single_line() -> None:
    chunk = plan_chunks("只有一行", max_lines=25, max_chars=1600)[0]

    assert split_chunk(chunk) is None
