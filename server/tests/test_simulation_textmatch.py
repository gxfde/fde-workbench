"""确定性文本重叠匹配（G9 接线轮 · Rubric 覆盖度校准）。

钉住：
1. 阈值是**写死的可解释常量**（变异可见），不是黑箱；
2. 对内置 6 案例的 must_identify，命中率达到实测口径（≥ 70%）；
3. must_produce（交付物类）**不走**字面匹配——交付物本就不该与事实同形；
4. 改写措辞后仍能命中（这正是替换精确子串的目的）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from fde_api.simulation.scenarios.loader import list_case_files, load_case_file
from fde_api.simulation.textmatch import (
    MATCH_THRESHOLD,
    MIN_SHARED_BIGRAMS,
    best_match,
    matches,
    overlap_ratio,
)


def test_threshold_is_a_documented_constant():
    assert 0.0 < MATCH_THRESHOLD < 1.0
    assert MATCH_THRESHOLD == 0.25
    assert MIN_SHARED_BIGRAMS >= 1


def test_overlap_is_zero_for_empty_candidate():
    assert overlap_ratio("跨系统主键缺失", "") == 0.0
    assert matches("跨系统主键缺失", "") is False


def test_overlap_is_zero_for_disjoint_text():
    assert overlap_ratio("跨系统主键缺失", "今天天气不错适合出门散步喝茶看书") == 0.0


def test_rewritten_wording_still_matches():
    """替换精确子串的目的：措辞不同也要能测出来。"""
    rubric = "跨系统主键缺失（MES 批次号 ↔ 质量库供应商批号无共同主键）"
    paraphrase = "MES 的批次号和质量库的供应商批号两边对不上，没有共同的主键可以关联"

    assert matches(rubric, paraphrase) is True


def test_builtin_cases_hit_rate_is_at_or_above_seventy_percent():
    """实测口径：6 案例 × must_identify，命中率 ≥ 70%（其余交给模型层）。"""
    hits = 0
    total = 0
    for path in list_case_files():
        case = load_case_file(path)
        facts = [
            str(fact.get("text") or "")
            for fact in ((case["content"].get("hidden") or {}).get("facts") or [])
        ]
        for target in case["reference"]["rubric"]["must_identify"]:
            total += 1
            if any(matches(str(target), fact) for fact in facts):
                hits += 1
    assert total > 0
    assert hits / total >= 0.7, f"命中率 {hits}/{total} 低于 0.7"


def test_facts_and_deliverables_use_two_different_criteria():
    """事实类（must_identify）与交付物类（must_produce）**走两套判据**。

    - 事实类：字面重叠匹配（在「已确认问题/根因」文本上）；
    - 交付物类：在**交付正文**上找（方案/产物里有没有真正产出那件事）。

    这条区分是必要的：交付物条目若拿去与事实文本做字面匹配，会把「提到了客户
    画像」误判成「产出了线索采集去重流程」。
    """
    from fde_api.simulation.evaluation_rules import score_criteria

    rubric = {
        "must_identify": ["跨系统主键缺失（MES 批次号 ↔ 质量库供应商批号无共同主键）"],
        "must_avoid": [],
        "must_produce": ["数据接入与主键映射方案"],
    }
    judge_view = {"reference": {"rubric": rubric}}

    with_paraphrase = score_criteria(
        traces=[],
        artifacts={
            "analysis": {
                "root_causes": [
                    {"text": "MES 的批次号和质量库的供应商批号两边对不上，没有共同的主键"}
                ],
                "requirements": [{"key": "REQ-1"}],
            },
            "design": {
                "solution_sections": [{"heading": "数据接入与主键映射方案"}],
                "tasks": [{"key": "TASK-1"}],
                "acceptance_criteria": [{"key": "AC-1", "requirement_key": "REQ-1"}],
            },
        },
        judge_view=judge_view,
    )
    by_key = {item.key: item for item in with_paraphrase}

    # 事实类：改写措辞仍命中（精确子串做不到）
    assert by_key["D1-01"].score > 0
    assert by_key["D1-01"].verified is True
    # 交付物类：在交付正文里找到 ⇒ 命中
    assert by_key["D3-01"].score == 1.0


def test_best_match_returns_the_closest_candidate():
    rubric = "跨系统主键缺失（MES 批次号 ↔ 质量库供应商批号无共同主键）"
    candidates = [
        "生产车间今天完成了 1200 件垫片",
        "MES 与质量库之间没有共同主键：批次号格式两套",
    ]

    text, ratio = best_match(rubric, candidates)

    assert text == candidates[1]
    assert ratio >= MATCH_THRESHOLD


def test_best_match_returns_none_when_nothing_is_close():
    text, ratio = best_match("跨系统主键缺失", ["今天天气不错", "午饭吃什么"])

    assert text is None
    assert ratio < MATCH_THRESHOLD
