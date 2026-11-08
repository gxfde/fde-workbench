"""确定性文本重叠匹配（V3.2 G9 接线轮 · Rubric 覆盖度校准）。

**为什么不用精确子串**：G8 验收实测发现 18 次模拟同分——因为规则层用
「Rubric 文本 ⊆ 产物文本」的**精确匹配**判覆盖。Rubric 写的是「应当识别出
什么」，产物写的是「实际说了什么」，两者措辞天然不同 ⇒ 精确匹配恒为 0 ⇒
判据恒为 0 ⇒ 规则层测不出「问得深 ↔ 知道得多 ↔ 产出更全」。

**替代口径**：确定性的**字面重叠率**（中文按字二元组、英文按词），Rubric 侧
的成分有多大比例出现在候选文本里。命中阈值是**可解释的常量**，不是黑箱：
``MATCH_THRESHOLD`` 写死在代码里、可被变异验证。

**边界（诚实）**：这是**字面**重叠，不是语义理解——同义改写仍会漏判。语义层面的
判断由模型层（L-B）承担；规则层只保证「同义不同词」的常见情形能测出来，且
结果**可复算**（同一对文本永远同一结论）。
"""
from __future__ import annotations

import re

# 命中阈值：Rubric 侧成分被覆盖的比例下限。
# **校准依据（2026-11-08 实测）**：对 6 个内置案例的 18 条 must_identify 与
# 其 5 条隐藏事实逐条求重叠率——命中项区间 0.25–0.69，非命中项 0.00–0.14。
# 取 0.25（低于它会开始把 must_produce 的交付物条目误判为命中）。
# 该常量**只适用于 must_identify（事实类）**；must_produce（交付物类）不走字面
# 匹配——交付物本就不该与事实同形（见 evaluation_rules 的分口径处理）。
MATCH_THRESHOLD = 0.25
# 至少共享的字二元组数（低于此视为偶然共现）
MIN_SHARED_BIGRAMS = 2
# 参与匹配的字符（中文）窗口
_CJK = re.compile(r"[一-鿿]+")
# 参与匹配的 ASCII 词
_ASCII_WORD = re.compile(r"[a-z0-9_]+")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _features(text: str) -> set[str]:
    """文本特征集：中文字二元组 + ASCII 词。"""
    normalized = _normalize(text)
    features: set[str] = set()
    for run in _CJK.findall(normalized):
        if len(run) == 1:
            features.add(run)
            continue
        for index in range(len(run) - 1):
            features.add(run[index : index + 2])
    features.update(_ASCII_WORD.findall(normalized))
    return features


def overlap_ratio(rubric_item: str, candidate_text: str) -> float:
    """Rubric 条目在候选文本中的字面覆盖率（0–1）。

    候选文本为空 ⇒ 0（**不命中**）。Rubric 条目无有效成分 ⇒ 0。
    """
    rubric_features = _features(rubric_item)
    if not rubric_features:
        return 0.0
    candidate_features = _features(candidate_text)
    if not candidate_features:
        return 0.0
    shared = rubric_features & candidate_features
    if not shared:
        return 0.0
    return round(len(shared) / len(rubric_features), 4)


def matches(rubric_item: str, candidate_text: str) -> bool:
    """是否命中：覆盖率达标 **且** 共享量不低于偶然共现下限。"""
    rubric_features = _features(rubric_item)
    candidate_features = _features(candidate_text)
    if not rubric_features or not candidate_features:
        return False
    shared = rubric_features & candidate_features
    if len(shared) < MIN_SHARED_BIGRAMS:
        # 极短 Rubric 条目（如单字）放宽：共享 1 个成分即算命中
        if len(rubric_features) > 1:
            return False
    return overlap_ratio(rubric_item, candidate_text) >= MATCH_THRESHOLD


def best_match(rubric_item: str, candidates: list[str]) -> tuple[str | None, float]:
    """在候选文本里找与 Rubric 条目最匹配的一条（返回文本与覆盖率）。"""
    best_text: str | None = None
    best_ratio = 0.0
    for candidate in candidates:
        ratio = overlap_ratio(rubric_item, candidate)
        if ratio > best_ratio:
            best_ratio = ratio
            best_text = candidate
    if best_text is not None and best_ratio >= MATCH_THRESHOLD:
        return best_text, best_ratio
    return None, round(best_ratio, 4)
